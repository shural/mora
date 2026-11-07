"""server.audio — media ingest / slicing / ASR for Mora.

Public interface (frozen with the Lead's FastAPI app):

    probe(url)                      -> dict
    download(url, dest, progress)   -> dict
    fetch_captions(url, workdir)    -> list[dict] | None
    slice_audio(src, start, end, dest) -> None
    transcribe(audio, language="ja")-> dict
    health()                        -> dict

Extra helper: ``extract_audio_to_wav(src, dest)`` (used by transcribe, exposed
for reuse).

Importing this package is cheap: no torch / faster_whisper / network import
happens at import time, and missing optional dependencies turn into
``{"ok": False, "reason": ...}`` values instead of import errors.
"""
from __future__ import annotations

from .asr import transcribe
from .ffmpeg import extract_audio_to_wav, slice_audio
from .healthcheck import health
from ._proc import AudioError
from .ytdlp import download, fetch_captions, probe

__all__ = [
    "AudioError",
    "probe",
    "download",
    "fetch_captions",
    "slice_audio",
    "transcribe",
    "extract_audio_to_wav",
    "health",
]
