"""Health checks for the audio module.  Must never raise."""
from __future__ import annotations

import os
import re
from pathlib import Path

from ._proc import FFMPEG, YTDLP, run
from . import asr


def _ytdlp() -> dict:
    try:
        out = run([YTDLP, "--version"], timeout=15, what="yt-dlp --version")
        version = out.splitlines()[-1].strip() if out else ""
        return {"ok": bool(version), "version": version}
    except Exception as exc:  # noqa: BLE001 - health must never raise
        return {"ok": False, "version": "", "reason": str(exc)}


def _ffmpeg() -> dict:
    try:
        out = run([FFMPEG, "-version"], timeout=15, what="ffmpeg -version")
        first = out.splitlines()[0] if out else ""
        match = re.search(r"ffmpeg version\s+(\S+)", first)
        return {"ok": bool(first), "version": match.group(1) if match else first}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "version": "", "reason": str(exc)}


def _whisper() -> dict:
    result: dict = {"ok": False, "model": asr.MODEL_NAME}
    try:
        installed = asr.backend_available()
        cached = asr.model_present()
        result["ok"] = bool(installed and cached)
        if not installed:
            result["reason"] = "faster-whisper is not installed"
        elif not cached:
            result["reason"] = (
                f"whisper model '{asr.MODEL_NAME}' is not cached "
                f"(expected under {_hf_home()}/hub/models--Systran--faster-whisper-{asr.MODEL_NAME})"
            )
    except Exception as exc:  # noqa: BLE001
        result["reason"] = str(exc)
    return result


def _hf_home() -> str:
    return os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")


def health() -> dict:
    ytdlp = _ytdlp()
    ffmpeg = _ffmpeg()
    whisper = _whisper()
    return {
        "ok": bool(ytdlp.get("ok") and ffmpeg.get("ok") and whisper.get("ok")),
        "ytdlp": ytdlp,
        "ffmpeg": ffmpeg,
        "whisper": whisper,
    }
