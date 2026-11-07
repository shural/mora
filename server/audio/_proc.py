"""Subprocess + ffprobe plumbing shared by the audio module.

This module only imports the standard library.  Every subprocess invocation is
listed here so timeouts / no-shell / stderr capture are uniform.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Callable, Iterable, Sequence


class AudioError(RuntimeError):
    """Raised for any audio/media operation that failed.

    The message always includes the tail of the child process stderr so the
    FastAPI layer can hand a useful ``detail`` string to the browser.
    """


def _find_tool(name: str, env_var: str, fallbacks: Sequence[str]) -> str:
    override = os.environ.get(env_var)
    if override:
        return override
    found = shutil.which(name)
    if found:
        return found
    for candidate in fallbacks:
        if Path(candidate).exists():
            return candidate
    return name


YTDLP = _find_tool("yt-dlp", "MORA_YTDLP", ("/opt/homebrew/bin/yt-dlp",))
FFMPEG = _find_tool("ffmpeg", "MORA_FFMPEG", ("/opt/homebrew/bin/ffmpeg",))
FFPROBE = _find_tool("ffprobe", "MORA_FFPROBE", ("/opt/homebrew/bin/ffprobe",))


def _tail(text: str, limit: int = 1800) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return "…" + text[-limit:]


def run(
    cmd: Iterable[object],
    *,
    timeout: float,
    what: str,
    cwd: Path | None = None,
) -> str:
    """Run a command, return stdout.  Raises AudioError on failure/timeout."""
    argv = [str(part) for part in cmd]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise AudioError(f"{what}: executable not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError(f"{what}: timed out after {timeout:g}s") from exc
    except OSError as exc:
        raise AudioError(f"{what}: could not start {argv[0]}: {exc}") from exc

    if proc.returncode != 0:
        detail = _tail(proc.stderr) or _tail(proc.stdout) or "(no output)"
        raise AudioError(f"{what} failed (exit {proc.returncode}): {detail}")
    return (proc.stdout or "").strip()


def run_raw(
    cmd: Iterable[object],
    *,
    timeout: float,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """Like run() but returns the CompletedProcess even for non-zero exits."""
    argv = [str(part) for part in cmd]
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise AudioError(f"executable not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError(f"timed out after {timeout:g}s") from exc
    except OSError as exc:
        raise AudioError(f"could not start {argv[0]}: {exc}") from exc


def run_streaming(
    cmd: Iterable[object],
    *,
    timeout: float,
    what: str,
    on_line: Callable[[str], None],
    cwd: Path | None = None,
) -> None:
    """Run a command, streaming its combined stdout+stderr to ``on_line``.

    yt-dlp writes ``[download] xx.x%`` progress to *stdout* while warnings and
    errors go to stderr, so both streams are merged into one pipe (this also
    avoids pipe deadlocks).
    """
    argv = [str(part) for part in cmd]
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(cwd) if cwd else None,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise AudioError(f"{what}: executable not found: {argv[0]}") from exc
    except OSError as exc:
        raise AudioError(f"{what}: could not start {argv[0]}: {exc}") from exc

    tail: deque[str] = deque(maxlen=60)

    def reader() -> None:
        assert proc.stdout is not None
        fd = proc.stdout.fileno()
        buf = b""
        while True:
            try:
                chunk = os.read(fd, 8192)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while True:
                match = re.search(rb"[\r\n]", buf)
                if not match:
                    break
                raw, buf = buf[: match.start()], buf[match.end() :]
                if not raw:
                    continue
                line = raw.decode("utf-8", "replace")
                tail.append(line)
                try:
                    on_line(line)
                except Exception:  # progress callbacks must never kill the job
                    pass
        if buf:
            line = buf.decode("utf-8", "replace")
            tail.append(line)
            try:
                on_line(line)
            except Exception:
                pass

    thread = threading.Thread(target=reader, name="mora-audio-stderr", daemon=True)
    thread.start()
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        raise AudioError(f"{what}: timed out after {timeout:g}s") from exc
    finally:
        thread.join(timeout=5)
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except OSError:
                pass

    if code != 0:
        detail = _tail("\n".join(tail)) or "(no output)"
        raise AudioError(f"{what} failed (exit {code}): {detail}")


def probe_media(path: Path, *, timeout: float = 20) -> dict:
    """Return ffprobe JSON for a media file."""
    out = run(
        [
            FFPROBE,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=timeout,
        what=f"ffprobe {path.name}",
    )
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise AudioError(f"ffprobe returned unparsable JSON for {path}") from exc


def media_duration(path: Path, *, timeout: float = 20) -> float:
    """Duration in seconds, from the container or the first stream."""
    info = probe_media(path, timeout=timeout)
    candidates = [info.get("format", {}).get("duration")]
    for stream in info.get("streams", []):
        candidates.append(stream.get("duration"))
    for value in candidates:
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    raise AudioError(f"could not determine duration of {path}")


def audio_stream(path: Path, *, timeout: float = 20) -> dict:
    """First audio stream of a media file (ffprobe dict)."""
    info = probe_media(path, timeout=timeout)
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "audio":
            return stream
    raise AudioError(f"{path.name}: no audio stream found")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
