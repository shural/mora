"""Lyrics lookup by song name. No file, no paste.

Primary source: QQ Music's public lyric endpoint — licensed catalogue, huge
Japanese coverage, and it returns **timestamped LRC**, so a typed song name
yields lyrics that are already in sync with the audio.

Everything here is best-effort: no provider reachable -> None -> the caller
falls back to captions, then to ASR alignment of the vocal.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://y.qq.com/",
    "Accept": "application/json, text/plain, */*",
}
# QQ serves the same API from several edges and they fail independently:
# c.y.qq.com started returning 500 while szc.y.qq.com kept working. Try the
# healthy ones first and remember which are down.
QQ_HOSTS = ["https://szc.y.qq.com", "https://c.y.qq.com"]
QQ_SEARCH_PATH = "/soso/fcgi-bin/client_search_cp"
# oldest endpoint: still serves when the others 500, but omits `language`
QQ_SEARCH_ALT = "https://c.y.qq.com/soso/fcgi-bin/search_for_qq_cp"
QQ_LYRIC = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
TIMEOUT = 15

# metadata lines the model should not learn from
CREDIT_RE = re.compile(
    r"^[\[\(【]?\s*(作词|作詞|作曲|编曲|編曲|词|曲|演唱|原唱|混音|母带|制作人|"
    r"和声|合声|吉他|贝斯|鼓|弦乐|录音|监制|出品|发行|OP|SP|词：|曲：|编曲：)"
)
# "Strings Arrange：河野圭" / "Guitar：秋山浩徳" — English instrument credits
CREDIT_LATIN_RE = re.compile(
    r"^\s*[A-Za-z][A-Za-z0-9 .&/'()・,\-]{1,40}\s*[:：]\s*\S"
)
# credit keywords anywhere on a short line
CREDIT_ANY_RE = re.compile(
    r"(arrange?ment?|programming|producer|guitar|bass|drums?|strings?|piano|"
    r"keyboard|synth(esizer)?|chorus|recorded|mixing|master(ing|ed)?|"
    r"composed|lyrics?|vocals?)\s*[:：]",
    re.I,
)
_LYRIC_CHAR = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\u4e00-\u9fff]")
KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa]")


@dataclass
class Candidate:
    source: str
    id: str
    title: str
    artist: str
    album: str = ""
    lines: list[dict[str, Any]] = field(default_factory=list)
    trans: dict[str, str] = field(default_factory=dict)
    has_japanese: bool = False
    language: int = 0
    duration: float = 0.0
    pubtime: int = 0
    score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "timed": bool(self.lines),
            "duration": self.duration,
            "japanese": self.has_japanese,
        }


def _get(url: str, timeout: int = TIMEOUT) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\s\u3000_\-–—・.,'\"!?！？()（）\[\]【】&/]+", "", s)


def _clean_artist(artist: str) -> str:
    """'CHAGE and ASKA (恰克与飞鸟)' -> 'CHAGE and ASKA' — search engines choke on the rest."""
    a = re.sub(r"[\(（\[【].*?[\)）\]】]", "", artist or "")
    a = re.sub(r"\s+", " ", a).strip(" /-")
    return a or (artist or "")


def _looks_japanese(text: str) -> bool:
    return len(KANA_RE.findall(text or "")) >= 8


# ------------------------------------------------------------------ LRC


def _is_credit(body: str) -> bool:
    """True for '词：飛鳥涼' / 'Guitar：秋山浩徳' / 'Strings Arrange：河野圭'."""
    if CREDIT_RE.match(body):
        return True
    if len(body) <= 60:
        if CREDIT_LATIN_RE.match(body):
            return True
        if CREDIT_ANY_RE.search(body):
            # a real lyric line rarely names an instrument followed by a colon
            return True
    return False


_TIME_RE = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")


def parse_lrc(text: str) -> list[dict[str, Any]]:
    """LRC text -> [{'start','text'}] sorted, credits and title lines dropped."""
    rows: list[tuple[float, str]] = []
    for raw in (text or "").replace("\r", "").split("\n"):
        stamps = _TIME_RE.findall(raw)
        if not stamps:
            continue
        body = _TIME_RE.sub("", raw).strip()
        body = body.strip("　 \t")
        if not body:
            continue
        if _is_credit(body):
            continue
        for mm, ss in stamps:
            try:
                t = int(mm) * 60 + float(ss.replace(":", "."))
            except ValueError:
                continue
            rows.append((t, body))
    rows.sort(key=lambda r: r[0])

    if rows and rows[0][0] < 3.0:
        head = rows[0][1]
        if " - " in head or "｜" in head or head.lower().count(" - ") >= 1:
            rows = rows[1:]

    # merge duplicate timestamps, drop near-duplicates
    merged: list[tuple[float, str]] = []
    for t, body in rows:
        if merged and abs(merged[-1][0] - t) < 0.05:
            if len(body) > len(merged[-1][1]):
                merged[-1] = (t, body)
            continue
        merged.append((t, body))

    out: list[dict[str, Any]] = []
    for i, (t, body) in enumerate(merged):
        end = merged[i + 1][0] if i + 1 < len(merged) else t + 5.0
        out.append({"start": round(t, 2), "end": round(max(end, t + 0.6), 2), "text": body})
    return out


def _parse_trans(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in parse_lrc(text):
        out[f"{row['start']:.2f}"] = row["text"]
    return out


# ------------------------------------------------------------------ QQ Music

def _parse_songs(songs: list[dict[str, Any]]) -> list[Candidate]:
    out: list[Candidate] = []
    for s in songs:
        title = str(s.get("songname") or s.get("title") or s.get("name") or "").strip()
        singers = s.get("singer") or []
        artist = " / ".join(str(x.get("name") or "") for x in singers).strip(" /")
        mid = str(s.get("songmid") or s.get("mid") or "")
        if not mid or not title:
            continue
        album = s.get("albumname") or (s.get("album") or {}).get("name") or ""
        out.append(Candidate(
            source="qq",
            id=mid,
            title=title,
            artist=artist,
            album=str(album),
            language=int(s.get("language") or 0),
            duration=float(s.get("interval") or 0),
            pubtime=int(s.get("pubtime") or 0),
        ))
    return out


_cache: dict[str, tuple[float, Any]] = {}
_host_down_until: dict[str, float] = {}
NOW = lambda: time.time()


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and NOW() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (NOW(), value)
    return value


def _search_urls(q: str, limit: int) -> list[str]:
    urls = [
        f"{host}{QQ_SEARCH_PATH}?w={q}&format=json&n={limit}&p=1&cr=1&new_json=1"
        for host in QQ_HOSTS
        if NOW() >= _host_down_until.get(host, 0.0)
    ]
    urls.append(f"{QQ_SEARCH_ALT}?w={q}&format=json&n={limit}&p=1")
    return urls


def _qq_search(query: str, limit: int = 12) -> list[Candidate]:
    """Search across QQ edges, with a circuit breaker per host."""
    def run() -> list[Candidate]:
        q = urllib.parse.quote(query)
        last: Exception | None = None
        for url in _search_urls(q, limit):
            host = url.split("/soso/")[0]
            try:
                data = json.loads(_get(url))
            except Exception as e:  # noqa: BLE001
                last = e
                _host_down_until[host] = NOW() + 300
                continue
            songs = (((data.get("data") or {}).get("song") or {}).get("list")) or []
            cands = _parse_songs(songs)
            if cands:
                return cands
        if last is not None:
            raise last
        return []

    return _cached(f"search:{query}:{limit}", 300.0, run)


def _qq_lyric_cached(mid: str) -> dict[str, str]:
    return _cached(f"lyric:{mid}", 3600.0, lambda: _qq_lyric(mid))


def _score(query: str, title: str, artist: str) -> float:
    q, t, a = _norm(query), _norm(title), _norm(artist)
    if not q:
        return 0.0
    score = 0.0
    if q == t:
        score += 100
    elif q.startswith(t) or t.startswith(q):
        score += 60
    elif q in t or t in q:
        score += 40
    # the query may carry "<title> <artist>" — the artist part should still hit
    for token in re.split(r"[\s,、]+", query):
        nt = _norm(token)
        if len(nt) >= 2 and (nt in t or nt in a):
            score += 12
    if a and a in q:
        score += 25
    return score


def _qq_lyric(mid: str) -> dict[str, str]:
    url = (
        QQ_LYRIC
        + "?songmid=" + urllib.parse.quote(mid)
        + "&format=json&nobase64=1&g_tk=5381&loginUin=0&hostUin=0&inCharset=utf8&outCharset=utf-8&notice=0&platform=yqq&needNewCode=0"
    )
    data = json.loads(_get(url))
    return {"lyric": str(data.get("lyric") or ""), "trans": str(data.get("trans") or "")}


# ------------------------------------------------------------------ public

def search(query: str, limit: int = 12) -> list[Candidate]:
    """Lyric candidates in the provider's own order. Never raises.

    QQ already ranks by popularity/relevance, which is exactly the ranking a
    human would want (`夜に駆ける` -> YOASOBI before four utaite covers).
    Re-sorting by our own title-equality score breaks that, so we don't.
    """
    try:
        return _qq_search(query, limit)
    except Exception:
        return []


def resolve(query: str, hint: str = "", max_probe: int = 4) -> Candidate | None:
    """Best candidate *with usable lyrics*, preferring the canonical artist.

    Two collisions to survive:
      1. Same title, different language (`Say Yes` matched a Chinese cover).
      2. Same title, dozens of covers (夜に駆ける returns 4 utaite before YOASOBI).
    (`hint` is the title/uploader of the audio we actually downloaded — if a
    candidate's artist or title appears in it, that is almost always the one.)
    """
    cands = search(query)
    if not cands:
        return None
    # QQ tags Japanese tracks with language == 3. This is the cheapest way to
    # tell the original SAY YES (CHAGE and ASKA) from the Korean/Chinese covers
    # that share the title, before spending a request on each lyric.
    has_language = any(c.language for c in cands)
    jp = [c for c in cands if c.language == 3]
    if jp:
        cands = jp + [c for c in cands if c.language != 3]
    if not has_language:
        # The fallback endpoint carries no language tag, so we cannot pick the
        # Japanese original that way. Release year is the next best signal:
        # among same-title results the original is the oldest (SAY YES -> 1991).
        qn = _norm(query)

        def rank(cand: Candidate) -> tuple[int, int]:
            tn = _norm(cand.title)
            # containment, not equality: the original often carries a subtitle
            # ("夜に駆ける (向夜晚奔去)") while covers use the bare title.
            related = 0 if (qn and (qn in tn or tn in qn)) else 1
            return (related, cand.pubtime or 9_999_999_999)
        cands.sort(key=rank)
        max_probe = max(max_probe, 6)
    if hint:
        fuzzy = _norm(hint)
        for i, cand in enumerate(cands):
            a, t = _norm(cand.artist), _norm(cand.title)
            if a and len(a) >= 3 and a in fuzzy:
                cand.score += 90
            elif t and len(t) >= 2 and t in fuzzy:
                cand.score += 25
        # stable: provider relevance still breaks ties
        cands.sort(key=lambda c: -c.score)
    fallback: Candidate | None = None
    for cand in cands[:max_probe]:
        try:
            payload = _qq_lyric_cached(cand.id)
        except Exception:
            continue
        rows = parse_lrc(payload["lyric"])
        if not rows:
            continue
        text = "\n".join(r["text"] for r in rows)
        cand.lines = rows
        cand.trans = _parse_trans(payload["trans"])
        cand.has_japanese = _looks_japanese(text)
        if cand.has_japanese:
            return cand
        if fallback is None:
            fallback = cand
    return fallback


def health() -> dict[str, Any]:
    try:
        cands = _qq_search("夜に駆ける", 3)
        return {"ok": bool(cands), "provider": "qq", "sample": [c.title for c in cands[:3]]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "provider": "qq", "reason": str(e)}
