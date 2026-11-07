"""faster-whisper ASR with a lazy, process-wide model singleton.

Importing this module must stay cheap: neither ``faster_whisper`` nor ``torch``
is imported until the first transcription call.

VAD policy (learned from real sung audio): Silero VAD is a *speech* detector and
gates out sung vocals, which is exactly our use case (karaoke auto-sync and
sing-back).  We therefore transcribe with ``vad_filter=False`` first and only
fall back to ``vad_filter=True`` when the no-VAD pass produced zero segments —
never the other way around.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import threading
from pathlib import Path

from ._proc import AudioError
from .ffmpeg import extract_audio_to_wav, media_duration

MODEL_NAME = "small"
MODEL_DEVICE = "cpu"
MODEL_COMPUTE_TYPE = "int8"

# VAD retry parameters: a lower speech threshold keeps quiet sung phrases.
_VAD_PARAMETERS = {
    "threshold": 0.3,
    "min_silence_duration_ms": 2000,
    "speech_pad_ms": 300,
}

_model = None
_model_lock = threading.Lock()


def model_present() -> bool:
    """True when the cached CTranslate2 model files are on disk."""
    hf_home = os.environ.get("HF_HOME") or os.path.join(Path.home(), ".cache", "huggingface")
    repo = Path(hf_home) / "hub" / f"models--Systran--faster-whisper-{MODEL_NAME}"
    if not repo.is_dir():
        return False
    for snapshot in (repo / "snapshots").glob("*"):
        if (snapshot / "model.bin").is_file():
            return True
    return False


def backend_available() -> bool:
    try:
        return importlib.util.find_spec("faster_whisper") is not None
    except (ImportError, ValueError):
        return False


def get_model():
    """Load (once) and return the shared WhisperModel."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        if not backend_available():
            raise AudioError("faster-whisper is not installed in this Python environment")
        if not model_present():
            raise AudioError(f"whisper model '{MODEL_NAME}' is not cached on disk")
        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415 (heavy, lazy)
        except Exception as exc:  # pragma: no cover - depends on environment
            raise AudioError(f"could not import faster_whisper: {exc}") from exc
        try:
            _model = WhisperModel(
                MODEL_NAME, device=MODEL_DEVICE, compute_type=MODEL_COMPUTE_TYPE
            )
        except Exception as exc:  # pragma: no cover - depends on environment
            raise AudioError(f"could not load whisper model '{MODEL_NAME}': {exc}") from exc
        return _model


def _round(value) -> float:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return 0.0


def _collect(model, wav: Path, language: str, *, vad_filter: bool) -> tuple[list[dict], object]:
    kwargs = {
        "language": language or None,
        "vad_filter": vad_filter,
        "beam_size": 5,
        "word_timestamps": True,
    }
    if vad_filter:
        kwargs["vad_parameters"] = dict(_VAD_PARAMETERS)
    segments_iter, info = model.transcribe(str(wav), **kwargs)
    segments: list[dict] = []
    for seg in segments_iter:
        text = (seg.text or "").strip()
        if not text:
            continue
        item = {
            "start": _round(seg.start),
            "end": _round(seg.end),
            "text": text,
        }
        words = getattr(seg, "words", None)
        if words:
            item["words"] = [
                {
                    "start": _round(word.start),
                    "end": _round(word.end),
                    "word": (word.word or ""),
                    "probability": round(float(word.probability or 0.0), 4),
                }
                for word in words
            ]
        segments.append(item)
    return segments, info


def transcribe(audio_path: Path, language: str = "ja") -> dict:
    """Transcribe a wav/webm/m4a recording to text + timed segments.

    Returns ``{'text', 'segments': [{'start','end','text', 'words'?}], 'lang'}``
    where ``words`` is present only when the backend supplies word timings.
    ``vad_filter=True`` is used only as a retry after an empty no-VAD pass.
    """
    audio = Path(audio_path)
    if not audio.exists():
        raise AudioError(f"transcribe: audio file not found: {audio}")
    if audio.stat().st_size == 0:
        raise AudioError(f"transcribe: audio file is empty: {audio}")

    try:
        duration = media_duration(audio)
    except AudioError:
        duration = 0.0

    with tempfile.TemporaryDirectory(prefix="mora-asr-") as tmpdir:
        wav = Path(tmpdir) / "input16k.wav"
        extract_audio_to_wav(audio, wav)
        model = get_model()
        try:
            segments, info = _collect(model, wav, language, vad_filter=False)
            if not segments:
                segments, info = _collect(model, wav, language, vad_filter=True)
        except AudioError:
            raise
        except Exception as exc:  # pragma: no cover - backend specific
            raise AudioError(f"whisper transcription failed: {exc}") from exc

    detected = getattr(info, "language", None) or language or ""
    text = "".join(seg["text"] for seg in segments).strip()
    if len(segments) > 1 and detected and not detected.startswith("ja"):
        text = " ".join(seg["text"] for seg in segments).strip()
    return {
        "text": text,
        "segments": segments,
        "lang": detected,
        "duration": _round(duration),
    }
