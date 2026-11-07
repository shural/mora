"""Song persistence. One JSON document per song under data/songs/<id>/song.json."""
from __future__ import annotations

import json
import re
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SONGS = DATA / "songs"
CACHE = DATA / "cache"

_lock = threading.RLock()
TZ = timezone(timedelta(hours=8))


def now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def _dir(song_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", song_id):
        raise ValueError("bad song id")
    return SONGS / song_id


def song_dir(song_id: str) -> Path:
    return _dir(song_id)


def audio_path(song_id: str) -> Path | None:
    d = _dir(song_id)
    for name in ("audio.m4a", "audio.mp3", "audio.wav", "audio.webm"):
        p = d / name
        if p.exists():
            return p
    return None


def new_id(title: str) -> str:
    base = unicodedata.normalize("NFKD", title or "song")
    base = re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower()[:32] or "song"
    candidate = base
    n = 2
    while (_dir(candidate) / "song.json").exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def save_song(song: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        d = _dir(song["id"])
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "song.json.tmp"
        tmp.write_text(json.dumps(song, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(d / "song.json")
    return song


def get_song(song_id: str) -> dict[str, Any]:
    p = _dir(song_id) / "song.json"
    if not p.exists():
        raise KeyError(song_id)
    with _lock:
        return json.loads(p.read_text("utf-8"))


def list_songs() -> list[dict[str, Any]]:
    out = []
    if not SONGS.exists():
        return out
    for d in sorted(SONGS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        p = d / "song.json"
        if not p.is_file():
            continue
        try:
            s = json.loads(p.read_text("utf-8"))
        except Exception:
            continue
        out.append(summary(s))
    return out


def summary(song: dict[str, Any]) -> dict[str, Any]:
    lines = song.get("lines", [])
    hue = abs(hash(song["id"])) % 360
    return {
        "id": song["id"],
        "title": song.get("title") or song["id"],
        "artist": song.get("artist") or "",
        "duration": song.get("duration") or 0,
        "audioUrl": f"/api/media/{song['id']}/audio",
        "coverUrl": song.get("coverUrl"),
        "linesTotal": len(lines),
        "cards": len(song.get("cards", [])),
        "synced": bool(song.get("synced")),
        "thumbHue": hue,
    }


def delete_song(song_id: str) -> None:
    import shutil
    d = _dir(song_id)
    if d.exists():
        shutil.rmtree(d)


# ------------------------------------------------------------------ cards

def _card_id(song_id: str, token_id: str) -> str:
    return f"{song_id}:{token_id}"


def ensure_card(song: dict[str, Any], line_id: str, token_id: str) -> dict[str, Any]:
    line = next((l for l in song["lines"] if l["id"] == line_id), None)
    if line is None:
        raise KeyError("line")
    tok = next((t for t in line["tokens"] if t["id"] == token_id), None)
    if tok is None:
        raise KeyError("token")
    cid = _card_id(song["id"], token_id)
    for c in song.get("cards", []):
        if c["id"] == cid:
            return c
    # Cut a ~3s window centred on where this word is actually sung, not the
    # whole line: a 14s prompt is not a flashcard, it's a listening exercise.
    # Card headword = dictionary form. The song sings 迷わ (the -zu form of 迷う);
    # a flashcard should teach 迷う, with the sung form kept alongside.
    head_surface, head_kana, head_romaji = tok["surface"], tok["kana"], tok["romaji"]
    lemma = tok.get("dictForm")
    if lemma and lemma != tok["surface"]:
        try:
            from . import jp
            parts = jp.tokenize_line(str(lemma), "c")
            if len(parts) == 1 and parts[0].get("kana"):
                head_surface = str(lemma)
                head_kana = parts[0]["kana"]
                head_romaji = parts[0]["romaji"]
        except Exception:  # noqa: BLE001
            pass

    start, end = 0.0, 1.5
    if float(line["start"]) >= 0 and float(line["end"]) > float(line["start"]):
        idx = next(i for i, t in enumerate(line["tokens"]) if t["id"] == token_id)
        before = sum(len(t.get("morae") or []) for t in line["tokens"][:idx])
        total = max(1, sum(len(t.get("morae") or []) for t in line["tokens"]))
        n = max(1, len(tok.get("morae") or []))
        frac = (before + n / 2) / total
        center = float(line["start"]) + (float(line["end"]) - float(line["start"])) * frac
        start = max(0.0, center - 1.5)
        end = start + 3.0
        dur = float(song.get("duration") or 0)
        if dur and end > dur:
            end = dur
            start = max(0.0, end - 3.0)
    card = {
        "id": cid,
        "songId": song["id"],
        "lineId": line_id,
        "tokenId": token_id,
        "surface": head_surface,
        "kana": head_kana,
        "romaji": head_romaji,
        "asSung": tok["surface"] if head_surface != tok["surface"] else None,
        "glossZh": tok.get("glossZh"),
        "lineText": line["text"],
        "start": round(start, 2),
        "end": round(end, 2),
        "sliceUrl": f"/api/media/{song['id']}/slice?start={start:.2f}&end={end:.2f}&format=wav",
        "due": now(),
        "interval": 0,
        "ease": 2.5,
        "reps": 0,
        "lapses": 0,
        "createdAt": now(),
    }
    song.setdefault("cards", []).append(card)
    tok["saved"] = True
    return card


def drop_card(song: dict[str, Any], card_id: str) -> None:
    song["cards"] = [c for c in song.get("cards", []) if c["id"] != card_id]
    for line in song["lines"]:
        for t in line["tokens"]:
            if _card_id(song["id"], t["id"]) == card_id:
                t["saved"] = False


def review_card(card: dict[str, Any], grade: int) -> dict[str, Any]:
    """SM-2 lite. grade: 0 again, 1 hard, 2 good, 3 easy."""
    ease = float(card.get("ease", 2.5))
    interval = float(card.get("interval", 0))
    reps = int(card.get("reps", 0))
    if grade <= 0:
        interval = 10 / (60 * 24)
        reps = 0
        ease = max(1.3, ease - 0.2)
        card["lapses"] = int(card.get("lapses", 0)) + 1
    else:
        if reps == 0:
            interval = 1 if grade >= 2 else 0.5
        else:
            interval = max(1.0, interval * ease * (0.75 if grade == 1 else 1.0))
        if grade == 3:
            ease = min(3.2, ease + 0.08)
        reps += 1
    card["ease"] = round(ease, 2)
    card["interval"] = round(interval, 3)
    card["reps"] = reps
    card["due"] = (datetime.now(TZ) + timedelta(days=interval)).isoformat(timespec="seconds")
    return card


# ------------------------------------------------------------------ helpers

def empty_song(song_id: str, title: str, artist: str, duration: float,
               source_url: str | None, cover_url: str | None) -> dict[str, Any]:
    return {
        "id": song_id,
        "title": title or song_id,
        "artist": artist or "",
        "duration": duration or 0.0,
        "audioUrl": f"/api/media/{song_id}/audio",
        "coverUrl": cover_url,
        "sourceUrl": source_url,
        "offset": 0.0,
        "synced": False,
        "lyricsSource": "none",
        "createdAt": now(),
        "cards": [],
        "lines": [],
    }


def build_lines(texts: list[str], timings: list[tuple[float, float]] | None = None) -> list[dict[str, Any]]:
    from . import jp
    lines: list[dict[str, Any]] = []
    for i, text in enumerate(texts):
        start, end = (timings[i] if timings and i < len(timings) else (-1.0, -1.0))
        lines.append({
            "id": f"l{i}",
            "text": text,
            "start": float(start),
            "end": float(end),
            "glossZh": None,
            "naturalness": None,
            "note": None,
            "tokens": jp.tokenize_line(text, f"l{i}"),
        })
    return lines


def remap_timings(song: dict[str, Any]) -> None:
    """Proportionally redistribute existing line times over the new lines."""
    olds = [l for l in song["lines"] if l["start"] >= 0]
    if not olds:
        return
    t0 = min(l["start"] for l in olds)
    t1 = max(l["end"] for l in olds)
    weights = [max(1, len(l["text"])) for l in song["lines"]]
    total = sum(weights)
    cursor = t0
    span = max(0.5, t1 - t0)
    for line, w in zip(song["lines"], weights):
        dur = span * w / total
        line["start"] = round(cursor, 2)
        line["end"] = round(cursor + dur, 2)
        cursor += dur
    song["synced"] = True


def mark_synced(song: dict[str, Any]) -> None:
    song["synced"] = bool(song["lines"]) and all(l["start"] >= 0 for l in song["lines"])
