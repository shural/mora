"""ffmpeg-based audio transforms: browser normalisation, slicing, ASR prep."""
from __future__ import annotations

from pathlib import Path

from ._proc import (
    AudioError,
    FFMPEG,
    audio_stream,
    ensure_dir,
    media_duration,
    run,
)

# Browsers (Safari + Chrome) both play AAC in an MP4 container reliably.
WEB_SAMPLE_RATE = 44_100
# Cards / ASR use narrow-band mono; whisper wants 16 kHz, slices 22.05 kHz.
SLICE_SAMPLE_RATE = 22_050
ASR_SAMPLE_RATE = 16_000
FADE_SECONDS = 0.03


def _run_ffmpeg(
    args: list[str], *, timeout: float, what: str, dest: Path | None = None
) -> None:
    if dest is not None:
        ensure_dir(dest.parent)
    try:
        run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], timeout=timeout, what=what)
    except AudioError:
        if dest is not None:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    if dest is not None and (not dest.exists() or dest.stat().st_size == 0):
        raise AudioError(f"{what}: ffmpeg produced no output at {dest}")


def normalise_for_web(src: Path, dest: Path) -> Path:
    """Decode any yt-dlp container to 44.1 kHz mono AAC in a .m4a.

    Falls back to mp3 (libmp3lame, 128k) when the local ffmpeg build has no AAC
    encoder; in that case the returned path ends in ``.mp3``.
    """
    src, dest = Path(src), Path(dest)
    ensure_dir(dest.parent)
    m4a_tmp = dest.with_name(dest.stem + ".tmp.m4a")
    try:
        _run_ffmpeg(
            [
                "-i",
                str(src),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(WEB_SAMPLE_RATE),
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                str(m4a_tmp),
            ],
            timeout=300,
            what="ffmpeg normalise (aac)",
            dest=m4a_tmp,
        )
        _replace(m4a_tmp, dest)
        return dest
    except AudioError:
        m4a_tmp.unlink(missing_ok=True)

    mp3_dest = dest.with_suffix(".mp3")
    mp3_tmp = mp3_dest.with_name(mp3_dest.stem + ".tmp.mp3")
    _run_ffmpeg(
        [
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(WEB_SAMPLE_RATE),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            "-f",
            "mp3",
            str(mp3_tmp),
        ],
        timeout=300,
        what="ffmpeg normalise (mp3 fallback)",
        dest=mp3_tmp,
    )
    _replace(mp3_tmp, mp3_dest)
    return mp3_dest


def _replace(tmp: Path, dest: Path) -> None:
    tmp.replace(dest)


def clamp_range(src: Path, start: float, end: float) -> tuple[float, float, float]:
    """Validate/clamp [start, end) against the media duration.

    Returns ``(start, end, duration)``.  ``start`` is clamped to >= 0 and the
    caller-supplied ``end`` is clamped to the media duration; a non-positive or
    out-of-media range raises a clear error instead of letting ffmpeg hang.
    """
    try:
        start = float(start)
        end = float(end)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"start/end must be numbers, got {start!r}/{end!r}") from exc
    if end != end or start != start:  # NaN
        raise ValueError("start/end must be finite numbers")
    if end <= start:
        raise ValueError(f"end ({end:g}s) must be greater than start ({start:g}s)")
    duration = media_duration(Path(src))
    if duration <= 0:
        raise AudioError(f"{src}: media has non-positive duration")
    if start >= duration - 0.01:
        raise AudioError(
            f"start {start:g}s is at/after the media duration ({duration:g}s)"
        )
    start = max(0.0, start)
    end = min(duration, end)
    if end - start < 0.02:
        raise AudioError(
            f"requested range {start:g}-{end:g}s is too short after clamping"
        )
    return start, end, duration


def slice_audio(src: Path, start: float, end: float, dest: Path) -> None:
    """Cut ``[start, end]`` to a 22.05 kHz mono wav with a 30 ms fade in/out."""
    src, dest = Path(src), Path(dest)
    if not src.exists():
        raise AudioError(f"slice_audio: source not found: {src}")
    start, end, _duration = clamp_range(src, start, end)
    length = end - start
    fade = min(FADE_SECONDS, length / 4.0)
    fade_out_start = max(0.0, length - fade)
    ensure_dir(dest.parent)
    _run_ffmpeg(
        [
            # input seek + -t: unambiguous, and ffmpeg's default accurate_seek
            # decodes up to the requested position for sample-accurate cuts.
            "-ss",
            f"{start:.4f}",
            "-t",
            f"{length:.4f}",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SLICE_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            "-af",
            f"afade=t=in:st=0:d={fade:.4f},afade=t=out:st={fade_out_start:.4f}:d={fade:.4f}",
            str(dest),
        ],
        timeout=120,
        what="ffmpeg slice",
        dest=dest,
    )
    actual = media_duration(dest, timeout=20)
    if abs(actual - length) > 0.15:
        raise AudioError(
            f"ffmpeg slice produced {actual:.3f}s but requested {length:.3f}s"
        )


def extract_audio_to_wav(src: Path, dest: Path) -> Path:
    """Decode any upload (webm/opus, m4a, mp4 …) to 16 kHz mono PCM wav."""
    src, dest = Path(src), Path(dest)
    if not src.exists():
        raise AudioError(f"extract_audio_to_wav: source not found: {src}")
    ensure_dir(dest.parent)
    _run_ffmpeg(
        [
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(ASR_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(dest),
        ],
        timeout=300,
        what="ffmpeg extract wav",
        dest=dest,
    )
    return dest


def describe(path: Path) -> dict:
    """Compact stream info used by selftest / diagnostics."""
    stream = audio_stream(Path(path))
    return {
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
        "duration": float(stream.get("duration") or 0.0),
    }
