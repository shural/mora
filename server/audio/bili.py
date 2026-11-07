"""Bilibili fallback path.

On this network (and on many datacenter / VPN egresses) bilibili.com serves the
video *webpage* with ``HTTP 412`` while the public JSON API keeps working.  The
yt-dlp BiliBili extractor needs the webpage, so when it fails we resolve the
video through ``api.bilibili.com`` directly:

    view     -> title / owner / duration / cover / cid
    playurl  -> DASH audio URLs (m4s, fMP4/AAC)
    player/v2-> CC subtitle JSON

Downloads must be requested with ``Range: bytes=0-``; without it the media CDN
answers ``567`` for this kind of request, while a ranged request returns 206.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from typing import Callable

from ._proc import AudioError, ensure_dir
from . import ffmpeg as ff

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_API = "https://api.bilibili.com"
_BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AV_RE = re.compile(r"/av(\d+)")
_HTTP_TIMEOUT = 25

# Bilibili's WAF answers HTTP 412 to API calls that carry no browser cookie
# (``buvid3``).  The public fingerprint endpoint hands out a device id; a random
# ``buvid3`` is also accepted, so bootstrap never blocks the job.
_cookie_jar = CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookie_jar))
_cookie_lock = threading.Lock()
_cookie_ready = False
_FINGERPRINT_URL = f"{_API}/x/frontend/finger/spi"


def _set_cookie(name: str, value: str) -> None:
    _cookie_jar.set_cookie(
        Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=".bilibili.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
    )


def _refresh_cookies() -> None:
    global _cookie_ready
    with _cookie_lock:
        got_buvid = False
        try:
            req = urllib.request.Request(
                _FINGERPRINT_URL,
                headers={"User-Agent": _UA, "Referer": "https://www.bilibili.com/"},
            )
            with _opener.open(req, timeout=_HTTP_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace") or "{}")
            data = payload.get("data") or {}
            if data.get("b_3"):
                _set_cookie("buvid3", data["b_3"])
                got_buvid = True
            if data.get("b_4"):
                _set_cookie("buvid4", data["b_4"])
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            pass
        if not got_buvid:
            # An arbitrary buvid3 is accepted by the API (verified on this box).
            _set_cookie("buvid3", f"{uuid.uuid4()!s}infoc".upper())
        try:
            req = urllib.request.Request(
                "https://www.bilibili.com/",
                headers={"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml"},
            )
            with _opener.open(req, timeout=_HTTP_TIMEOUT) as resp:
                resp.read(4096)
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        _cookie_ready = True


def is_bilibili(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(str(url)).netloc.lower()
    except ValueError:
        return False
    return "bilibili.com" in host or host.endswith("b23.tv")


def _headers(referer: str = "https://www.bilibili.com/") -> dict:
    return {
        "User-Agent": _UA,
        "Referer": referer,
        "Origin": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ja,en;q=0.8,zh;q=0.6",
    }


def _get(url: str, *, referer: str = "https://www.bilibili.com/", timeout: float = _HTTP_TIMEOUT) -> bytes:
    if not _cookie_ready:
        _refresh_cookies()
    for attempt in (1, 2):
        req = urllib.request.Request(url, headers=_headers(referer))
        try:
            with _opener.open(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 412) and attempt == 1:
                _refresh_cookies()
                continue
            raise AudioError(f"Bilibili request failed: HTTP {exc.code} for {url}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AudioError(f"Bilibili request failed: {exc} (for {url})") from exc
    raise AudioError(f"Bilibili request failed: HTTP 412 for {url}")


def _get_json(url: str, params: dict, *, referer: str) -> dict:
    sep = "&" if "?" in url else "?"
    full = url + sep + urllib.parse.urlencode(params)
    raw = _get(full, referer=referer)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise AudioError(f"Bilibili returned non-JSON for {url}") from exc
    if not isinstance(data, dict):
        raise AudioError(f"Bilibili returned unexpected JSON for {url}")
    if data.get("code") != 0:
        raise AudioError(
            f"Bilibili API error {data.get('code')}: {data.get('message') or 'unknown'} ({url})"
        )
    return data


def _resolve_target(url: str) -> tuple[dict, str]:
    """Return (video_page_url, referer) — follows b23.tv short links."""
    url = str(url).strip()
    if "b23.tv" in urllib.parse.urlparse(url).netloc.lower():
        req = urllib.request.Request(
            url, headers={"User-Agent": _UA, "Referer": "https://www.bilibili.com/"}
        )
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                url = resp.geturl() or url
        except urllib.error.HTTPError as exc:  # redirect still tells us the target
            url = getattr(exc, "url", url) or url
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AudioError(f"Bilibili short link could not be resolved: {exc}") from exc
    if not (re.search(r"/(BV[0-9A-Za-z]{10})", url) or _AV_RE.search(url)):
        raise AudioError(f"not a Bilibili video URL: {url}")
    page = f"https://www.bilibili.com/video/{_video_key(url)}"
    return page, page


def _video_key(url: str) -> str:
    match = _BV_RE.search(url)
    if match:
        return match.group(1)
    match = _AV_RE.search(url)
    if match:
        return f"av{match.group(1)}"
    raise AudioError(f"could not find a BV/av id in {url}")


def _view_params(key: str) -> dict:
    return {"bvid": key} if key.startswith("BV") else {"aid": key[2:]}


def _view(url: str) -> tuple[dict, str]:
    page, referer = _resolve_target(url)
    key = _video_key(page)
    data = _get_json(f"{_API}/x/web-interface/view", _view_params(key), referer=referer)
    info = data.get("data") or {}
    if not info:
        raise AudioError(f"Bilibili view API returned no data for {key}")
    return info, referer


def probe(url: str) -> dict:
    info, referer = _view(url)
    bvid = info.get("bvid") or _video_key(referer)
    thumbnail = _https(info.get("pic"))
    return {
        "ok": True,
        "title": info.get("title") or "",
        "uploader": (info.get("owner") or {}).get("name") or "",
        "duration": float(info.get("duration") or 0),
        "webpage_url": f"https://www.bilibili.com/video/{bvid}",
        "thumbnail": thumbnail,
    }


def _https(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://"):
        return "https://" + url[len("http://"):]
    return url


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]*>", "", str(text or "")).strip()


def _duration_to_seconds(value) -> float:
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    parts = text.split(":")
    try:
        total = 0.0
        for part in parts:
            total = total * 60 + float(part)
        return total
    except ValueError:
        return 0.0


def search_probe(query: str, *, limit: int = 10) -> dict:
    """Resolve a ``bilisearchN:…`` keyword to the first Bilibili video."""
    query = str(query or "").strip()
    if not query:
        raise AudioError("empty Bilibili search query")
    params = {
        "search_type": "video",
        "keyword": query,
        "page": 1,
        "page_size": limit,
    }
    data = _get_json(f"{_API}/x/web-interface/search/type", params, referer="https://www.bilibili.com/")
    result = (data.get("data") or {}).get("result") or []
    for item in result:
        bvid = item.get("bvid") or ""
        if not bvid:
            continue
        duration = _duration_to_seconds(item.get("duration"))
        if duration <= 0:
            continue
        thumbnail = _https(item.get("pic"))
        return {
            "ok": True,
            "title": _strip_tags(item.get("title")) or bvid,
            "uploader": str(item.get("author") or ""),
            "duration": duration,
            "webpage_url": f"https://www.bilibili.com/video/{bvid}",
            "thumbnail": thumbnail,
        }
    raise AudioError(f"Bilibili search returned no video for {query!r}")


def _pick_audio(dash: dict) -> dict:
    audios = dash.get("audio") or []
    if not audios:
        raise AudioError("Bilibili playurl returned no DASH audio streams")
    return max(audios, key=lambda a: int(a.get("bandwidth") or 0))


def _playurl(info: dict, referer: str) -> dict:
    cid = int(info.get("cid") or 0)
    if not cid:
        pages = info.get("pages") or []
        cid = int((pages[0] or {}).get("cid") or 0) if pages else 0
    if not cid:
        raise AudioError("Bilibili video has no cid")
    params = _view_params(str(info.get("bvid") or "av" + str(info.get("aid"))))
    params.update({"cid": cid, "fnval": 16, "fnver": 0, "fourk": 1})
    data = _get_json(f"{_API}/x/player/playurl", params, referer=referer)
    return data.get("data") or {}


def _download_url(url: str, dest: Path, *, referer: str, progress: Callable[[float, str], None], timeout: float = 900) -> Path:
    req = urllib.request.Request(
        url, headers={**_headers(referer), "Range": "bytes=0-"}
    )
    ensure_dir(dest.parent)
    deadline = time.monotonic() + timeout
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            total = 0
            content_range = resp.headers.get("Content-Range") or ""
            match = re.search(r"/(\d+)$", content_range)
            if match:
                total = int(match.group(1))
            else:
                total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            tmp = dest.with_name(dest.name + ".part")
            with open(tmp, "wb") as fh:
                while True:
                    if time.monotonic() > deadline:
                        raise AudioError(f"Bilibili audio download timed out after {timeout:g}s")
                    chunk = resp.read(262_144)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if total > 0:
                        progress(min(95.0, done * 95.0 / total), f"下载中 {done * 100 // total}%")
            if done == 0:
                raise AudioError("Bilibili audio download produced an empty file")
            tmp.replace(dest)
            return dest
    except urllib.error.HTTPError as exc:
        raise AudioError(f"Bilibili CDN refused the audio download: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AudioError(f"Bilibili audio download failed: {exc}") from exc


def download(url: str, dest: Path, progress: Callable[[float, str], None]) -> dict:
    progress = progress or (lambda _p, _m: None)
    dest = Path(dest)
    ensure_dir(dest)
    info, referer = _view(url)
    bvid = info.get("bvid") or _video_key(referer)
    title = info.get("title") or ""
    artist = (info.get("owner") or {}).get("name") or ""
    duration = float(info.get("duration") or 0)
    thumbnail = _https(info.get("pic"))

    progress(1.0, "解析中 1%")
    payload = _playurl(info, referer)
    dash = payload.get("dash") or {}
    src = dest / "audio_src.m4s"
    if dash:
        audio = _pick_audio(dash)
        download_url = audio.get("baseUrl") or audio.get("url")
        backups = audio.get("backupUrl") or []
        if not download_url:
            raise AudioError("Bilibili DASH audio stream has no URL")
        try:
            _download_url(download_url, src, referer=referer, progress=progress)
        except AudioError:
            if not backups:
                raise
            _download_url(backups[0], src, referer=referer, progress=progress)
    else:
        durl = payload.get("durl") or []
        if not durl:
            raise AudioError("Bilibili playurl returned neither DASH nor durl data")
        best = max(durl, key=lambda item: int(item.get("size") or 0))
        _download_url(best.get("url") or best.get("backup_url") or "", src, referer=referer, progress=progress)

    progress(96.0, "转码中 96%")
    out = ff.normalise_for_web(src, dest / "audio.m4a")
    src.unlink(missing_ok=True)
    progress(100.0, "完成 100%")
    return {
        "path": str(out),
        "title": title,
        "artist": artist,
        "duration": duration,
        "thumbnail": thumbnail,
        "webpage_url": f"https://www.bilibili.com/video/{bvid}",
    }


def captions(url: str) -> list[dict] | None:
    info, referer = _view(url)
    # player/v2 carries the CC subtitle list (playurl does not).
    page_key = str(info.get("bvid") or _video_key(referer))
    params = _view_params(page_key)
    cid = int(info.get("cid") or 0)
    if not cid:
        pages = info.get("pages") or []
        cid = int((pages[0] or {}).get("cid") or 0) if pages else 0
    params["cid"] = cid
    try:
        data = _get_json(f"{_API}/x/player/v2", params, referer=referer)
    except AudioError:
        return None
    subtitles = ((data.get("data") or {}).get("subtitle") or {}).get("subtitles") or []
    if not subtitles:
        return None

    def score(item: dict) -> tuple[int, int]:
        lang = str(item.get("lan") or "").lower()
        prefer = 2 if lang.startswith("ja") else (1 if lang.startswith("zh") else 0)
        return (prefer, 1 if item.get("subtitle_url") else 0)

    best = max(subtitles, key=score)
    sub_url = best.get("subtitle_url") or ""
    if sub_url.startswith("//"):
        sub_url = "https:" + sub_url
    if not sub_url:
        return None
    try:
        raw = _get(sub_url, referer=referer, timeout=_HTTP_TIMEOUT)
        body = (json.loads(raw.decode("utf-8", "replace")) or {}).get("body") or []
    except (AudioError, json.JSONDecodeError):
        return None
    out: list[dict] = []
    for item in body:
        try:
            start = float(item.get("from"))
            end = float(item.get("to"))
        except (TypeError, ValueError):
            continue
        text = str(item.get("content") or "").strip()
        if text and end > start:
            out.append({"start": start, "end": end, "text": text})
    out.sort(key=lambda cue: cue["start"])
    return out or None
