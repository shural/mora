#!/usr/bin/env python
"""Verify that a song's line timings actually land on the sung vocal.

Transcribes the audio once, then for each lyric line compares the morae heard
inside [start, end] against the morae that should be there. Also sweeps a global
offset, because the usual failure isn't random error — it's a constant shift
when the audio is a different master / has an extra intro.

    .venv/bin/python scripts/verify_sync.py <song_id> [--sweep 4]
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import kana_diff, store  # noqa: E402
from server.audio import transcribe  # noqa: E402
from server.main import _heard_morae  # noqa: E402


def norm(m: str) -> str:
    return {"ー": "う"}.get(m, m)


def ratio(expected: list[str], heard: list[str]) -> float:
    if not expected:
        return 0.0
    a = [norm(x) for x in expected]
    b = [norm(x) for x in heard]
    return difflib.SequenceMatcher(a=a, b=b, autojunk=False).ratio()


def heard_in_window(heard, lo: float, hi: float) -> list[str]:
    return [m for m, t in heard if lo <= t < hi]


def score(song, heard, offset: float) -> tuple[float, list[float]]:
    """offset is an *extra* shift on top of the song's own stored offset."""
    base_off = float(song.get("offset") or 0.0)
    per = []
    for line in song["lines"]:
        a, b = float(line["start"]) + base_off + offset, float(line["end"]) + base_off + offset
        if a < 0:
            continue
        exp = [m for t in line["tokens"] for m in t.get("morae") or []]
        got = heard_in_window(heard, a, b)
        per.append(ratio(exp, got))
    if not per:
        return 0.0, []
    return sum(per) / len(per), per


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("song_id")
    ap.add_argument("--sweep", type=float, default=4.0, help="max |offset| seconds")
    args = ap.parse_args()

    song = store.get_song(args.song_id)
    audio = store.audio_path(args.song_id)
    if not audio:
        print("no audio")
        return 1
    print(f"{song['title']} — {song['artist']}  ({song['duration']:.0f}s, {len(song['lines'])} lines)")
    print(f"timingSource={song.get('timingSource')}  lyricsSource={song.get('lyricsSource')}  offset={song.get('offset') or 0:+.2f}s")

    print("transcribing…")
    result = transcribe(audio, language="ja")
    heard = list(zip(*_heard_morae(result)))
    heard = [(m, t) for m, t in heard]
    print(f"  heard {len(heard)} morae, {len(result.get('segments') or [])} segments\n")

    base, per = score(song, heard, 0.0)
    print(f"baseline mean line match: {base * 100:.1f}%")
    for i, line in enumerate(song["lines"]):
        if i < len(per):
            bar = "█" * int(per[i] * 20)
            print(f"  {line['start']:7.2f} {per[i] * 100:5.1f}% {bar:<20} {line['text'][:26]}")

    print("\nsweeping offset…")
    best_off, best_val = 0.0, base
    step = 0.25
    n = int(args.sweep / step)
    for i in range(-n, n + 1):
        off = round(i * step, 2)
        val, _ = score(song, heard, off)
        if val > best_val + 0.005:
            best_val, best_off = val, off
    print(f"  best offset {best_off:+.2f}s -> {best_val * 100:.1f}% (baseline {base * 100:.1f}%)")

    verdict = "OK" if best_val >= 0.55 else ("OFFSET" if best_val - base > 0.06 else "BROKEN")
    print(f"\nverdict: {verdict}")
    return 0 if verdict == "OK" else 2


if __name__ == "__main__":
    sys.exit(main())
