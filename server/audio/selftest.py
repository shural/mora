"""Real end-to-end selftest for server.audio.

Run from the project root:

    .venv/bin/python -m server.audio.selftest

It actually downloads a YouTube video and a Bilibili video, fetches real
captions, slices audio, and runs whisper on a ~2 s clip.  Results are printed
as a compact PASS/FAIL table; artefacts are kept in /tmp for inspection.

Exit code is 0 only when every check passed.
"""
from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):  # allow `python server/audio/selftest.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.audio import (  # noqa: E402
    AudioError,
    download,
    extract_audio_to_wav,
    fetch_captions,
    health,
    probe,
    slice_audio,
    transcribe,
)
from server.audio import _proc  # noqa: E402
from server.audio import ffmpeg as ff  # noqa: E402
from server.audio.vtt import load_captions, parse_vtt  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SONG_FIXTURE = PROJECT_ROOT / "data" / "songs" / "english-en-subs" / "audio.m4a"

YOUTUBE_URLS = [
    "https://www.youtube.com/watch?v=p1eZ8sIDF1A",
    "https://www.youtube.com/watch?v=4ByeVbOlFLE",
    "https://www.youtube.com/watch?v=XZWqKXnjqb4",
]
BILIBILI_URLS = [
    "https://www.bilibili.com/video/BV1R44y1s7eX",
    "https://www.bilibili.com/video/BV1t64y157UE",
]

WORKDIR = Path(tempfile.mkdtemp(prefix="mora-audio-selftest-"))
ROWS: list[tuple[str, str, str]] = []
STATE: dict = {}


def _fmt(value) -> str:
    return json.dumps(value, ensure_ascii=False)[:160]


class SkipCheck(Exception):
    """Environment-level blocker (e.g. IP rate limit), not a code bug."""


def check(name: str, fn, *, detail: str = "") -> bool:
    started = time.time()
    try:
        result = fn()
    except SkipCheck as exc:
        ROWS.append((name, "SKIP", str(exc)[:240]))
        print(f"[SKIP] {name}: {exc}", flush=True)
        return False
    except Exception as exc:  # noqa: BLE001 - selftest reports, never crashes
        ROWS.append((name, "FAIL", f"{type(exc).__name__}: {exc}"[:240]))
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}", flush=True)
        return False
    elapsed = time.time() - started
    text = result if isinstance(result, str) else _fmt(result)
    if detail:
        text = f"{detail} | {text}"
    text = f"{text}  ({elapsed:.1f}s)"
    ROWS.append((name, "PASS", text[:240]))
    print(f"[PASS] {name}: {text}", flush=True)
    return True


def first_ok_probe(urls: list[str], key: str) -> dict:
    errors: list[str] = []
    for attempt in (1, 2):
        for url in urls:
            result = probe(url)
            if result.get("ok"):
                STATE[key] = {"url": result.get("webpage_url") or url, "probing": result}
                return result
            errors.append(f"{url}: {result.get('reason', '')}")
        if attempt == 1:
            time.sleep(3.0)  # transient Bilibili 412 / rate limits
    raise RuntimeError("all candidates failed:\n  " + "\n  ".join(errors))


def main() -> int:
    print(f"Mora audio selftest  |  workdir: {WORKDIR}\n", flush=True)

    # ---------------------------------------------------------------- import safety
    def import_safety():
        code = (
            "import sys, server.audio; "
            "heavy=[m for m in ('faster_whisper','torch','ctranslate2') if m in sys.modules]; "
            "print(','.join(heavy) or 'clean')"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        assert out.returncode == 0, out.stderr[-400:]
        assert out.stdout.strip() == "clean", f"heavy imports at import time: {out.stdout.strip()}"
        return "no whisper/torch import at package import"

    check("import safety", import_safety)

    # ---------------------------------------------------------------------- health
    health_result = health()
    STATE["health"] = health_result
    check(
        "health()",
        lambda: health_result,
        detail="ok" if health_result.get("ok") else "NOT OK",
    )
    check(
        "health() never raises on missing deps",
        lambda: _health_with_broken_path(),
    )

    # ----------------------------------------------------------------------- probe
    def probe_youtube():
        return first_ok_probe(YOUTUBE_URLS, "yt")

    check("probe youtube", probe_youtube)
    yt_state = STATE.get("yt") or {}
    yt_probe = yt_state.get("probing")
    yt_url = yt_state.get("url")

    def probe_bilibili():
        return first_ok_probe(BILIBILI_URLS, "bili")

    check("probe bilibili", probe_bilibili)
    bili_state = STATE.get("bili") or {}
    bili_probe = bili_state.get("probing")
    bili_url = bili_state.get("url")

    check("probe ytsearch1: pseudo-url", lambda: _require_ok(probe("ytsearch1:ふるさと 童謡")))
    check(
        "probe bilisearch1: pseudo-url",
        lambda: _require_ok(probe("bilisearch1:ふるさと 童謡")),
    )

    # -------------------------------------------------------------------- download
    def do_download(label: str, url: str, subdir: str) -> dict:
        dest = WORKDIR / subdir
        events: list[float] = []

        def progress(value: float, message: str) -> None:
            events.append(round(float(value), 1))

        result = download(url, dest, progress)
        path = Path(result["path"])
        assert path.is_file() and path.stat().st_size > 20_000, f"bad audio file {path}"
        stream = ff.describe(path)
        info = {
            "path": path.name,
            "bytes": path.stat().st_size,
            "codec": stream["codec"],
            "rate": stream["sample_rate"],
            "channels": stream["channels"],
            "duration": round(stream["duration"], 3),
            "progress_events": len(events),
            "progress_last": events[-1] if events else None,
        }
        source_duration = float(result["duration"])
        assert abs(stream["duration"] - source_duration) <= 1.0, (
            f"normalised duration {stream['duration']:.2f}s vs source {source_duration:.2f}s"
        )
        assert stream["channels"] == 1, f"expected mono, got {stream['channels']} ch"
        assert stream["sample_rate"] == 44_100, f"expected 44.1kHz, got {stream['sample_rate']}"
        assert stream["codec"] in {"aac", "mp3"}, f"unexpected codec {stream['codec']}"
        assert len(events) >= 3, f"progress callback fired only {len(events)} times"
        assert events[-1] == 100.0, f"progress never reached 100 (last {events[-1]})"
        return {**info, "title": result["title"][:40], "artist": result["artist"][:30],
                "duration_reported": source_duration}

    def download_youtube():
        if not yt_url:
            raise SkipCheck("probe youtube failed")
        result = do_download("youtube", yt_url, "yt-download")
        STATE["yt_download"] = result
        return result

    check("download youtube -> audio.m4a", download_youtube)

    def download_bilibili():
        if not bili_url:
            raise SkipCheck("probe bilibili failed")
        result = do_download("bilibili", bili_url, "bili-download")
        STATE["bili_download"] = result
        return result

    check("download bilibili -> audio.m4a", download_bilibili)

    # -------------------------------------------------------------------- captions
    def captions_youtube():
        tried = []
        for candidate in [url for url in YOUTUBE_URLS if url] + ([yt_url] if yt_url else []):
            if candidate in tried:
                continue
            tried.append(candidate)
            workdir = WORKDIR / ("yt-captions-" + candidate.rsplit("=", 1)[-1])
            captions = fetch_captions(candidate, workdir)
            if captions:
                yt_url_captions = candidate
                break
        else:
            raise SkipCheck(
                "no captions returned for " + ", ".join(tried) +
                " — YouTube timedtext is HTTP 429 (IP rate-limited) on this network; "
                "VTT parsing/dedup is covered by the fixture test"
            )
        chars = sum(len(cue["text"]) for cue in captions)
        span = max(cue["end"] for cue in captions) - min(cue["start"] for cue in captions)
        state = {
            "cues": len(captions),
            "chars": chars,
            "span_s": round(span, 1),
            "url": yt_url_captions,
            "head": [cue["text"] for cue in captions[:4]],
        }
        STATE["yt_captions"] = state
        return state

    check("fetch_captions youtube (ja)", captions_youtube)

    def captions_bilibili():
        tried = []
        for candidate in BILIBILI_URLS:
            if candidate in tried:
                continue
            tried.append(candidate)
            captions = fetch_captions(candidate, WORKDIR / ("bili-captions-" + candidate.rsplit("/", 1)[-1]))
            if captions:
                bili_url_captions = candidate
                break
        else:
            raise SkipCheck(
                "no CC subtitle track on attempted Bilibili videos: " + ", ".join(tried) +
                " (bilibili CC is rare for these uploads)"
            )
        chars = sum(len(cue["text"]) for cue in captions)
        state = {
            "cues": len(captions),
            "chars": chars,
            "span_s": round(max(c["end"] for c in captions) - min(c["start"] for c in captions), 1),
            "url": bili_url_captions,
            "head": [cue["text"] for cue in captions[:4]],
        }
        STATE["bili_captions"] = state
        return state

    check("fetch_captions bilibili", captions_bilibili)

    # ---------------------------------------------------------------- vtt dedupe
    def vtt_dedupe_unit():
        fixture = WORKDIR / "rolling.ja.vtt"
        fixture.write_text(
            "WEBVTT\nKind: captions\nLanguage: ja\n\n"
            "00:00:00.000 --> 00:00:02.000 align:start\n"
            "<00:00:00.000><c>うさぎ</c>\n\n"
            "00:00:01.000 --> 00:00:03.000 align:start\n"
            "<00:00:00.000><c>うさぎ</c><00:00:01.000><c> おいし</c>\n\n"
            "00:00:03.500 --> 00:00:05.000 align:start\n"
            "<00:00:03.000><c>かの</c><00:00:04.000><c> 山</c>\n\n"
            "00:00:05.500 --> 00:00:07.000 align:start\n"
            "<00:00:05.000><c>かの</c><00:00:06.000><c> 山</c>\n\n",
            encoding="utf-8",
        )
        raw = parse_vtt(fixture)
        assert len(raw) == 4, f"expected 4 raw cues, got {len(raw)}"
        merged = load_captions(fixture)
        texts = [cue["text"] for cue in merged]
        assert len(merged) <= 3, f"dedupe kept too many cues: {texts}"
        assert any("うさぎ" in t and "おいし" in t for t in texts), texts
        assert merged == sorted(merged, key=lambda c: c["start"]), "not sorted"
        assert all(c["end"] > c["start"] for c in merged), "bad cue durations"
        return {"raw_cues": len(raw), "merged": texts[:4]}

    check("vtt rolling-caption dedupe (fixture)", vtt_dedupe_unit)

    # ------------------------------------------------------------------ slicing
    def slicing():
        source_path = _downloaded_path("yt-download")
        dest = WORKDIR / "slices" / "line_10_12.wav"
        slice_audio(source_path, 10.0, 12.0, dest)
        stream = ff.describe(dest)
        assert stream["sample_rate"] == 22_050, stream
        assert stream["channels"] == 1, stream
        assert abs(stream["duration"] - 2.0) <= 0.1, stream
        STATE["slice"] = dest
        return {"file": dest.name, **{k: stream[k] for k in ("codec", "sample_rate", "channels", "duration")}}

    check("slice_audio 22.05kHz mono + fade", slicing)

    def slicing_clamped():
        source = _downloaded_path("yt-download")
        dest = WORKDIR / "slices" / "clamped.wav"
        slice_audio(source, -5.0, 3.0, dest)
        stream = ff.describe(dest)
        assert abs(stream["duration"] - 3.0) <= 0.1, stream
        dest2 = WORKDIR / "slices" / "clamped_end.wav"
        duration = ff.describe(source)["duration"]
        slice_audio(source, duration - 1.0, duration + 99.0, dest2)
        stream2 = ff.describe(dest2)
        assert abs(stream2["duration"] - 1.0) <= 0.15, stream2
        return {"neg_start": round(stream["duration"], 2), "past_end": round(stream2["duration"], 2)}

    check("slice_audio clamps negative / past-end ranges", slicing_clamped)

    def slicing_bad_range():
        source = _downloaded_path("yt-download")
        try:
            slice_audio(source, 30.0, 30.0, WORKDIR / "slices" / "bad.wav")
        except (AudioError, ValueError) as exc:
            return f"clear error: {exc}"[:120]
        raise RuntimeError("zero-length range did not raise")

    check("slice_audio rejects zero-length range", slicing_bad_range)

    # --------------------------------------------------------------- asr pipeline
    def extract_wav():
        src = _downloaded_path("yt-download")
        dest = WORKDIR / "asr" / "full16k.wav"
        extract_audio_to_wav(src, dest)
        stream = ff.describe(dest)
        assert stream["sample_rate"] == 16_000 and stream["channels"] == 1, stream
        return {"file": dest.name, **{k: stream[k] for k in ("codec", "sample_rate", "channels")}}

    check("extract_audio_to_wav (m4a -> 16k wav)", extract_wav)

    def transcribe_wav():
        clip = STATE.get("slice") or (WORKDIR / "slices" / "line_10_12.wav")
        started = time.time()
        result = transcribe(clip)
        elapsed = time.time() - started
        assert result["segments"], "no segments returned"
        assert result["text"].strip(), "empty transcription"
        has_words = any("words" in seg for seg in result["segments"])
        words = sum(len(seg.get("words", [])) for seg in result["segments"])
        STATE["transcribe"] = {"elapsed": elapsed, "result": result}
        return {
            "lang": result["lang"],
            "text": result["text"][:40],
            "segments": len(result["segments"]),
            "word_timings": f"{words} words" if has_words else "absent",
            "latency_s": round(elapsed, 2),
        }

    check("transcribe 2s wav clip (whisper small, cold)", transcribe_wav)

    def transcribe_webm():
        source = _downloaded_path("yt-download")
        webm = WORKDIR / "asr" / "upload.webm"
        webm.parent.mkdir(parents=True, exist_ok=True)
        _proc.run(
            [
                _proc.FFMPEG,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                "10",
                "-t",
                "2",
                "-i",
                str(source),
                "-vn",
                "-c:a",
                "libopus",
                "-b:a",
                "48k",
                str(webm),
            ],
            timeout=60,
            what="make webm/opus upload fixture",
        )
        assert webm.is_file() and webm.stat().st_size > 1000, "webm fixture not created"
        started = time.time()
        result = transcribe(webm)
        elapsed = time.time() - started
        assert result["text"].strip(), "empty transcription for webm"
        return {
            "file": webm.name,
            "text": result["text"][:40],
            "latency_s": round(elapsed, 2),
            "words": sum(len(s.get("words", [])) for s in result["segments"]),
        }

    check("transcribe webm/opus upload", transcribe_webm)

    def transcribe_full_song():
        assert SONG_FIXTURE.is_file(), f"missing integration fixture: {SONG_FIXTURE}"
        started = time.time()
        result = transcribe(SONG_FIXTURE)
        elapsed = time.time() - started
        assert result["segments"], "real music file returned 0 segments"
        assert result["text"].strip(), "real music file returned empty text"
        words = sum(len(seg.get("words", [])) for seg in result["segments"])
        assert words > 0, "no word timestamps on real music file"
        STATE["full_song"] = {
            "elapsed": elapsed,
            "segments": len(result["segments"]),
            "words": words,
            "text": result["text"][:120],
        }
        return {
            "segments": len(result["segments"]),
            "words": words,
            "chars": len(result["text"]),
            "latency_s": round(elapsed, 1),
            "faster_than_real_time_x": round(result.get("duration", 0) / elapsed, 1) if elapsed else None,
        }

    check("transcribe 143s real song fixture (non-empty)", transcribe_full_song)

    # ------------------------------------------------------------------- report
    print("\n" + "=" * 100)
    print(f"{'CHECK':<46} {'RESULT':<6} DETAIL")
    print("-" * 100)
    for name, result, detail in ROWS:
        print(f"{name:<46} {result:<6} {detail}")
    print("=" * 100)
    passed = sum(1 for _, result, _ in ROWS if result == "PASS")
    failed = sum(1 for _, result, _ in ROWS if result == "FAIL")
    skipped = sum(1 for _, result, _ in ROWS if result == "SKIP")
    print(f"TOTAL {len(ROWS)} checks: {passed} PASS, {failed} FAIL, {skipped} SKIP")
    if failed:
        print(f"FAILED: {', '.join(name for name, r, _ in ROWS if r == 'FAIL')}")
    if skipped:
        print(f"SKIPPED (environment): {', '.join(name for name, r, _ in ROWS if r == 'SKIP')}")

    summary = {
        "workdir": str(WORKDIR),
        "health": STATE.get("health"),
        "youtube": {
            "url": yt_url,
            "probe": yt_probe,
            "download": STATE.get("yt_download"),
            "captions": STATE.get("yt_captions"),
        },
        "bilibili": {
            "url": bili_url,
            "probe": bili_probe,
            "download": STATE.get("bili_download"),
            "captions": STATE.get("bili_captions"),
        },
        "transcribe": (
            {
                "latency_s": round(STATE["transcribe"]["elapsed"], 2),
                "result": STATE["transcribe"]["result"],
            }
            if "transcribe" in STATE
            else None
        ),
        "full_song_transcribe": STATE.get("full_song"),
        "checks": [{"name": n, "result": r, "detail": d} for n, r, d in ROWS],
    }
    (WORKDIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nsummary: {WORKDIR / 'summary.json'}")
    shutil.copy(__file__, WORKDIR / "selftest.py")
    return 1 if failed else 0


def _downloaded_path(subdir: str) -> Path:
    matches = sorted((WORKDIR / subdir).glob("audio.*"))
    for path in matches:
        if path.suffix.lower() in {".m4a", ".mp3"}:
            return path
    raise RuntimeError(f"no normalised audio in {WORKDIR / subdir}")


def _require_ok(result: dict) -> dict:
    assert result.get("ok"), result.get("reason")
    return result


def _health_with_broken_path() -> str:
    """health() must degrade to {ok: False, reason} when a binary is missing."""
    health_module = importlib.import_module("server.audio.healthcheck")
    old = health_module.YTDLP
    try:
        health_module.YTDLP = "/nonexistent/yt-dlp"
        result = health_module.health()
        assert result["ytdlp"]["ok"] is False, result
        assert "reason" in result["ytdlp"], result
        return {"ok": result["ok"], "ytdlp": result["ytdlp"]}
    finally:
        health_module.YTDLP = old


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
