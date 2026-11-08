"""yt-dlp ingest: probe / download / captions, with retries tuned for this box.

Recon on this machine:
* YouTube's default player clients fail (403 / "Requested format is not
  available"); the ``android`` client works.  So a failed YouTube call is
  retried once with ``--extractor-args youtube:player_client=android``.
* Bilibili occasionally serves the video *webpage* with HTTP 412 while its JSON
  API is fine; bili.py is the fallback for that case.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable

from . import bili
from . import ffmpeg as ff
from ._proc import (
    YTDLP,
    AudioError,
    ensure_dir,
    run,
    run_raw,
    run_streaming,
)
from . import vtt

PROBE_TIMEOUT = 45
DOWNLOAD_TIMEOUT = 900
CAPTIONS_TIMEOUT = 180
_PROGRESS_RE = re.compile(r"\[download\]\s+([\d.]+)%")
_AUDIO_SUFFIXES = {
    ".mp4",
    ".m4a",
    ".mp3",
    ".webm",
    ".opus",
    ".aac",
    ".flac",
    ".ogg",
    ".wav",
    ".m4s",
    ".mkv",
    ".mov",
}
_SEARCH_PREFIXES = ("ytsearch", "bilisearch", "ytsearchdate", "bilisearchdate")


def _is_search(target: str) -> bool:
    return target.startswith(_SEARCH_PREFIXES) or "://" not in target


def _is_youtube(target: str) -> bool:
    if target.startswith("ytsearch"):
        return True
    return "youtube.com" in target or "youtu.be" in target


def _is_bilibili(target: str) -> bool:
    return bili.is_bilibili(target)


def _normalise_target(target: str) -> str:
    target = str(target or "").strip()
    if not target:
        raise AudioError("empty URL / search query")
    if _is_search(target) and not target.startswith(_SEARCH_PREFIXES):
        # Tolerate a scheme-less pasted URL.
        if target.startswith("BV") and "/" not in target:
            return f"https://www.bilibili.com/video/{target}"
        if any(
            marker in target
            for marker in ("youtube.com/", "youtu.be/", "bilibili.com/", "b23.tv/")
        ):
            return "https://" + target.lstrip("/")
        return f"ytsearch1:{target}"
    return target


def _base_args(target: str) -> list[str]:
    args = [YTDLP, "--no-update"]
    if not _is_search(target):
        args.append("--no-playlist")
    return args


def _android_args() -> list[str]:
    return ["--extractor-args", "youtube:player_client=android"]


def _parse_json(stdout: str):
    stdout = (stdout or "").strip()
    if not stdout:
        raise AudioError("yt-dlp returned no JSON")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
    raise AudioError("yt-dlp returned unparsable JSON: " + stdout[:300])


def _pick_entry(payload: dict) -> dict:
    """Search results arrive as a playlist; pick the first real video."""
    if not isinstance(payload, dict):
        raise AudioError("unexpected yt-dlp JSON payload")
    entries = payload.get("entries")
    if entries is None:
        return payload
    for entry in entries or []:
        if isinstance(entry, dict):
            return entry
    raise AudioError("search returned no playable video")


def _meta_from_video(data: dict) -> dict:
    title = data.get("title") or data.get("fulltitle") or ""
    uploader = (
        data.get("uploader")
        or data.get("channel")
        or data.get("artist")
        or data.get("creator")
        or ""
    )
    duration = data.get("duration")
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    webpage_url = (
        data.get("webpage_url")
        or data.get("original_url")
        or data.get("url")
        or ""
    )
    return {
        "title": title,
        "uploader": uploader,
        "duration": duration,
        "webpage_url": webpage_url,
        "thumbnail": data.get("thumbnail"),
    }


def _probe_ytdlp(target: str) -> dict:
    cmd = _base_args(target) + ["--dump-single-json", "--skip-download", target]
    try:
        stdout = run(cmd, timeout=PROBE_TIMEOUT, what="yt-dlp probe")
    except AudioError:
        if not _is_youtube(target):
            raise
        cmd = _base_args(target) + _android_args() + [
            "--dump-single-json",
            "--skip-download",
            target,
        ]
        stdout = run(cmd, timeout=PROBE_TIMEOUT, what="yt-dlp probe (android client)")
    data = _pick_entry(_parse_json(stdout))
    meta = _meta_from_video(data)
    return {"ok": True, **meta}


def probe(url: str) -> dict:
    """Metadata only (no download).  Accepts URLs and ytsearch:/bilisearch:."""
    failure = {"ok": False, "title": None, "uploader": None, "duration": None,
               "webpage_url": None, "thumbnail": None, "reason": ""}
    try:
        target = _normalise_target(url)
    except AudioError as exc:
        failure["reason"] = str(exc)
        return failure
    try:
        result = _probe_ytdlp(target)
        if not str(result.get("webpage_url") or "").strip():
            # e.g. a Bilibili search entry whose %(url)s field came back empty:
            # fail loudly instead of handing the ingest layer an unusable result.
            raise AudioError(
                "yt-dlp probe returned a video without a usable URL (empty search result)"
            )
        return result
    except AudioError as exc:
        failure["reason"] = str(exc)
        if _is_bilibili(target):
            try:
                result = bili.probe(target)
                return result
            except AudioError as bili_exc:
                failure["reason"] = f"{exc}; bilibili API fallback: {bili_exc}"
        elif target.startswith("bilisearch"):
            match = re.match(r"bilisearch(?:date)?\d*:(.*)", target)
            if match:
                try:
                    return bili.search_probe(match.group(1))
                except AudioError as bili_exc:
                    failure["reason"] = f"{exc}; bilibili search fallback: {bili_exc}"
    return failure


def _make_progress(progress: Callable[[float, str], None] | None):
    last = {"value": 0.0}

    def emit(value: float, message: str) -> None:
        if progress is None:
            return
        try:
            value = max(0.0, min(100.0, float(value)))
            # Never let a retry move the job's progress bar backwards.
            last["value"] = max(last["value"], value)
            progress(last["value"], str(message))
        except Exception:
            pass

    return emit


def _find_source(dest: Path) -> Path | None:
    candidates: list[Path] = []
    for item in dest.iterdir():
        if not item.is_file():
            continue
        name = item.name
        if name.endswith((".info.json", ".part", ".ytdl", ".temp")):
            continue
        if item.suffix.lower() in _AUDIO_SUFFIXES:
            candidates.append(item)
    if not candidates:
        return None
    # Newest file wins (a stale audio.m4a from an earlier run must not be
    # mistaken for the fresh download); size breaks mtime ties.
    return max(candidates, key=lambda p: (p.stat().st_mtime, p.stat().st_size))


def _read_info_json(dest: Path) -> dict:
    for item in dest.glob("*.info.json"):
        try:
            return json.loads(item.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _cleanup_source(dest: Path, keep: Path) -> None:
    for item in dest.iterdir():
        if not item.is_file():
            continue
        if item.name.endswith((".info.json", ".part", ".ytdl", ".temp")):
            item.unlink(missing_ok=True)
        elif item.suffix.lower() in _AUDIO_SUFFIXES and item.resolve() != keep.resolve():
            item.unlink(missing_ok=True)


def _download_attempt(target: str, dest: Path, emit, *, android: bool) -> None:
    cmd = _base_args(target)
    if android:
        cmd += _android_args()
    cmd += [
        "-f",
        "bestaudio/best",
        "--newline",
        "--write-info-json",
        "-o",
        str(dest / "audio.%(ext)s"),
        target,
    ]

    def on_line(line: str) -> None:
        match = _PROGRESS_RE.search(line)
        if match:
            emit(min(92.0, float(match.group(1))), f"下载中 {match.group(1)}%")

    run_streaming(cmd, timeout=DOWNLOAD_TIMEOUT, what="yt-dlp download", on_line=on_line)


def download(url: str, dest: Path, progress: Callable[[float, str], None]) -> dict:
    """Download best audio to ``dest/audio.m4a`` and return song metadata."""
    dest = Path(dest)
    ensure_dir(dest)
    emit = _make_progress(progress)
    emit(0.0, "开始下载 0%")
    target = _normalise_target(url)
    # Fresh ingest: drop a previous result so _find_source can never pick it.
    for stale in (dest / "audio.m4a", dest / "audio.mp3", dest / "audio.webm", dest / "audio.wav"):
        stale.unlink(missing_ok=True)

    attempts: list[tuple[str, bool]] = [("default", False)]
    if _is_youtube(target):
        attempts.append(("android client", True))

    last_error: AudioError | None = None
    for label, android in attempts:
        try:
            _download_attempt(target, dest, emit, android=android)
            last_error = None
            break
        except AudioError as exc:
            last_error = exc
            # A failed first attempt may leave a partial file; yt-dlp resumes
            # via .part, but stale container files would confuse _find_source.
            for stale in dest.glob("audio.*"):
                if stale.suffix.lower() in _AUDIO_SUFFIXES:
                    stale.unlink(missing_ok=True)
            if label != "default":
                break

    info = _read_info_json(dest)
    source = _find_source(dest) if last_error is None else None
    if source is None:
        if _is_bilibili(target):
            emit(5.0, "切换 Bilibili API 5%")
            try:
                return bili.download(target, dest, emit)
            except AudioError as bili_exc:
                if last_error is None:
                    raise AudioError(f"download failed: {bili_exc}") from bili_exc
                raise AudioError(
                    f"download failed: {last_error}; bilibili API fallback: {bili_exc}"
                ) from bili_exc
        assert last_error is not None
        raise last_error

    emit(94.0, "封装中 94%")
    out = ff.normalise_for_web(source, dest / "audio.m4a")
    _cleanup_source(dest, keep=out)

    if info:
        meta = _meta_from_video(info)
        if meta["duration"] is None:
            meta["duration"] = float(ff.describe(out)["duration"])
    else:
        try:
            probed = probe(target)
        except AudioError:
            probed = {}
        if probed.get("ok"):
            meta = {
                "title": probed.get("title") or "",
                "uploader": probed.get("uploader") or "",
                "duration": probed.get("duration"),
                "webpage_url": probed.get("webpage_url") or str(url),
                "thumbnail": probed.get("thumbnail"),
            }
        else:
            meta = {
                "title": "",
                "uploader": "",
                "duration": float(ff.describe(out)["duration"]),
                "webpage_url": str(url),
                "thumbnail": None,
            }

    info_stream = ff.describe(out)
    if info_stream["channels"] < 1:
        raise AudioError(f"normalised audio has no audio stream: {out}")
    if meta["duration"] is None:
        meta["duration"] = info_stream["duration"]

    emit(100.0, "完成 100%")
    return {
        "path": str(out),
        "title": meta["title"],
        "artist": meta["uploader"],
        "duration": float(meta["duration"]),
        "thumbnail": meta["thumbnail"],
        "webpage_url": meta["webpage_url"] or str(url),
    }


def _vtt_files(workdir: Path) -> list[Path]:
    return sorted(workdir.rglob("*.vtt"))


def _best_captions(files: list[Path]) -> list[dict] | None:
    best: list[dict] | None = None
    best_chars = 0
    for path in files:
        try:
            cues = vtt.load_captions(path)
        except Exception:
            continue
        chars = sum(len(cue.get("text", "")) for cue in cues)
        if vtt.usable(cues) and chars > best_chars:
            best, best_chars = cues, chars
    return best


def _fetch_ytdlp_captions(target: str, workdir: Path) -> list[dict] | None:
    variants: list[tuple[str, ...]] = [
        ("--skip-download", "--write-subs"),
        ("--skip-download", "--write-auto-subs"),
    ]
    if _is_youtube(target):
        # Default clients fail on some videos here; android still resolves them.
        variants.append(
            (
                "--skip-download",
                "--write-auto-subs",
                *_android_args(),
            )
        )

    rate_limited = False

    def attempt(flags: tuple[str, ...]) -> list[dict] | None:
        nonlocal rate_limited
        cmd = _base_args(target) + list(flags) + [
            "--sub-langs",
            "ja,ja-JP,ja-orig",
            "--sub-format",
            "vtt",
            "-o",
            str(workdir / "%(id)s.%(ext)s"),
            target,
        ]
        try:
            proc = run_raw(cmd, timeout=CAPTIONS_TIMEOUT)
        except AudioError:
            return None
        found = _best_captions(_vtt_files(workdir))
        if found:
            return found
        stderr = (proc.stderr or "") + (proc.stdout or "")
        if "429" in stderr or "Too Many Requests" in stderr:
            # Google rate-limited this IP for the timedtext API; retrying the
            # other caption variants only burns time.
            rate_limited = True
        return None

    # Manual subtitles first, then auto-generated ones (separate runs so an
    # auto caption can never overwrite a higher-quality manual track).
    for flags in variants:
        found = attempt(flags)
        if found:
            return found
        if rate_limited:
            return None
    time.sleep(2.0)
    return attempt(variants[1])


def fetch_captions(url: str, workdir: Path) -> list[dict] | None:
    """Best available Japanese captions, or None."""
    workdir = Path(workdir)
    ensure_dir(workdir)
    target = _normalise_target(url)
    found: list[dict] | None = None
    try:
        found = _fetch_ytdlp_captions(target, workdir)
    except AudioError:
        found = None
    if found:
        return found
    if _is_bilibili(target):
        try:
            return bili.captions(target)
        except AudioError:
            return None
    return None
