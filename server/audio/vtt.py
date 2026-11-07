"""WebVTT caption parsing + de-duplication for YouTube's rolling captions."""
from __future__ import annotations

import html
import re
from pathlib import Path

_CUE_RE = re.compile(r"^\s*(\d{1,2}:)?\d{2}:\d{2}[.,]\d{1,3}\s*-->")
_TS_RE = re.compile(
    r"(\d{1,2}:)?(\d{2}):(\d{2})[.,](\d{1,3})\s*-->\s*(\d{1,2}:)?(\d{2}):(\d{2})[.,](\d{1,3})"
)
_TAG_RE = re.compile(r"<[^>]*>")
_SPACE_RE = re.compile(r"[ \t\u00a0]+")


def _parse_ts(hours: str | None, minutes: str, seconds: str, millis: str) -> float:
    h = int(hours[:-1]) if hours else 0
    return h * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, "0")) / 1000.0


def _clean_text(raw: str) -> str:
    raw = raw.replace("&nbsp;", " ")
    # <c>word</c>, <00:00:01.000>, <v Speaker>, <b>, … all vanish
    text = _TAG_RE.sub("", raw)
    text = html.unescape(text)
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


def parse_vtt(path: Path) -> list[dict]:
    """Parse a .vtt file into raw (un-deduped) cues."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    cues: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "-->" not in line:
            i += 1
            continue
        match = _TS_RE.search(line)
        if not match:
            i += 1
            continue
        start = _parse_ts(*match.groups()[:4])
        end = _parse_ts(*match.groups()[4:])
        i += 1
        body: list[str] = []
        while i < len(lines) and lines[i].strip():
            body.append(lines[i])
            i += 1
        # Skip caption "metadata" lines like "Kind:" / "Language:" (only at top).
        cleaned = " ".join(_clean_text(part) for part in body).strip()
        if cleaned and end > start:
            cues.append({"start": start, "end": end, "text": cleaned})
        i += 1
    return cues


def _overlap_merge(prev: str, nxt: str) -> str | None:
    """If ``nxt`` continues ``prev`` (rolling captions), return merged text."""
    if not prev or not nxt:
        return None
    if nxt == prev:
        return prev
    if nxt.startswith(prev):
        return nxt
    if prev.endswith(nxt):
        return prev
    # longest suffix of prev that is a prefix of nxt
    max_len = min(len(prev), len(nxt))
    for size in range(max_len, 1, -1):
        if prev.endswith(nxt[:size]) and size >= 2:
            return prev + nxt[size:]
    return None


def dedupe_cues(cues: list[dict], *, gap: float = 0.75) -> list[dict]:
    """Turn YouTube's overlapping rolling cues into clean, sorted segments.

    YouTube auto-captions repeat the previous line in the next cue, and grow
    line-by-line: ``A`` → ``A B`` → ``A B C``.  Consecutive identical or
    overlapping cues within ``gap`` seconds are folded into one segment.
    """
    ordered = sorted(cues, key=lambda c: (float(c["start"]), float(c["end"])))
    merged: list[dict] = []

    for cue in ordered:
        start, end = float(cue["start"]), float(cue["end"])
        text = str(cue["text"]).strip()
        if not text:
            continue
        end = max(end, start + 0.01)
        if not merged:
            merged.append({"start": start, "end": end, "text": text})
            continue

        prev = merged[-1]
        adjacent = start <= prev["end"] + gap
        overlap_text = _overlap_merge(prev["text"], text) if adjacent else None

        if overlap_text is not None:
            if len(overlap_text) >= len(prev["text"]):
                prev["text"] = overlap_text
            prev["end"] = max(prev["end"], end)
            continue

        merged.append({"start": start, "end": end, "text": text})

    # Drop exact duplicates that survived sorting; clamp monotonic start times.
    clean: list[dict] = []
    for cue in merged:
        if clean:
            prev = clean[-1]
            if cue["text"] == prev["text"] and cue["start"] <= prev["end"] + 0.2:
                prev["end"] = max(prev["end"], cue["end"])
                continue
            if cue["start"] < prev["start"]:
                cue["start"] = prev["start"]
            if cue["end"] <= cue["start"]:
                cue["end"] = cue["start"] + 0.01
        if not cue["text"]:
            continue
        clean.append(cue)
    return clean


def load_captions(path: Path) -> list[dict]:
    """Full pipeline for one .vtt file."""
    return dedupe_cues(parse_vtt(path))


def usable(segments: list[dict] | None) -> bool:
    if not segments:
        return False
    chars = sum(len(seg.get("text", "")) for seg in segments)
    return chars >= 2 and len(segments) >= 1
