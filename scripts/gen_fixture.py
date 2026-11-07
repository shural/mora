"""Regenerate the mock fixtures the frontend develops against.

Lyrics: 童謡「ふるさと」(高野辰之 1914, public domain).
Run: .venv/bin/python scripts/gen_fixture.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import jp  # noqa: E402

LINES = [
    ("兎追いしかの山", 12.40, 15.10, "追过兔子的那座山", "yellow",
     "「〜しか」是古语回想助动词「き」的连体形，现代日语不会这样说。"),
    ("小鮒釣りしかの川", 15.10, 18.20, "钓过小鲫鱼的那条河", "yellow",
     "同上，仍是文语过去式。「小鮒」读こぶな，是幼鲫鱼。"),
    ("夢は今もめぐりて", 18.20, 21.60, "梦境至今仍在心头萦绕", "yellow",
     "「めぐりて」是「めぐる」的文语て形；口语说「めぐって」。"),
    ("忘れがたき故郷", 21.60, 25.00, "难以忘怀的故乡", "yellow",
     "「〜がたき」＝「〜にくい」的古语形式。这里的「故郷」读ふるさと，不是词典的こきょう。"),
    ("如何にいます父母", 25.00, 28.90, "父母可还安好", "red",
     "整句是文语：「如何に」＝どう、「います」＝いらっしゃる。口语：両親は元気にしてるかな。"),
    ("恙なしや友がき", 28.90, 32.60, "朋友们可还无恙", "red",
     "「恙なし」＝つつがない（平安无事），「や」是文语疑问助词。口语：友達は元気かな。"),
    ("雨に風につけても", 32.60, 36.20, "无论是下雨还是刮风", "green",
     "「〜につけても」＝每当……就……，这个表达现代日语里还在用。"),
    ("思ひ出づる故郷", 36.20, 40.00, "总会想起的故乡", "yellow",
     "「思ひ出づる」是旧假名遣い，现代写作「思い出づる／思い出す」。「故郷」同样读ふるさと。"),
]

DURATION = 178.0


def main() -> None:
    lines = []
    for i, (text, start, end, gloss, naturalness, note) in enumerate(LINES):
        lid = f"l{i}"
        tokens = jp.tokenize_line(text, lid)
        # line-level pass: attach the line's naturalness to the tokens too,
        # so the study view can colour words without a second request.
        for t in tokens:
            t["naturalness"] = naturalness
        lines.append({
            "id": lid,
            "text": text,
            "start": start,
            "end": end,
            "glossZh": gloss,
            "naturalness": naturalness,
            "note": note,
            "tokens": tokens,
        })

    cards = []
    c1 = next(t for t in lines[3]["tokens"] if t["surface"] == "故郷")
    c1["glossZh"] = "故乡"
    c1["saved"] = True
    c2 = next(t for t in lines[5]["tokens"] if t["surface"].startswith("恙"))
    c2["glossZh"] = "无恙；平安无事"
    c2["saved"] = True
    cards = [
        {
            "id": "c1", "songId": "furusato", "lineId": "l3", "tokenId": c1["id"],
            "surface": c1["surface"], "kana": c1["kana"], "romaji": c1["romaji"],
            "glossZh": "故乡", "lineText": lines[3]["text"],
            "start": 22.4, "end": 23.6,
            "sliceUrl": "/api/media/furusato/slice?start=22.4&end=23.6&format=wav",
            "due": "2026-11-08T09:00:00+08:00", "interval": 1, "ease": 2.5,
            "reps": 1, "lapses": 0, "createdAt": "2026-11-07T20:00:00+08:00",
        },
        {
            "id": "c2", "songId": "furusato", "lineId": "l5", "tokenId": c2["id"],
            "surface": c2["surface"], "kana": c2["kana"], "romaji": c2["romaji"],
            "glossZh": "无恙；平安无事", "lineText": lines[5]["text"],
            "start": 29.2, "end": 30.4,
            "sliceUrl": "/api/media/furusato/slice?start=29.2&end=30.4&format=wav",
            "due": "2026-11-08T09:00:00+08:00", "interval": 1, "ease": 2.5,
            "reps": 0, "lapses": 0, "createdAt": "2026-11-07T20:00:00+08:00",
        },
    ]

    song = {
        "id": "furusato",
        "title": "ふるさと",
        "artist": "童謡",
        "duration": DURATION,
        "audioUrl": "/api/media/furusato/audio",
        "coverUrl": None,
        "sourceUrl": "https://www.youtube.com/watch?v=demo",
        "offset": 0.0,
        "synced": True,
        "createdAt": "2026-11-07T20:00:00+08:00",
        "cards": cards,
        "lines": lines,
    }

    songs = [{
        "id": "furusato", "title": "ふるさと", "artist": "童謡",
        "duration": DURATION, "audioUrl": "/api/media/furusato/audio",
        "coverUrl": None, "linesTotal": len(lines), "cards": len(cards),
        "synced": True, "thumbHue": 338,
    }]

    out = ROOT / "contract" / "fixtures"
    out.mkdir(parents=True, exist_ok=True)
    (out / "song.json").write_text(json.dumps(song, ensure_ascii=False, indent=2), "utf-8")
    (out / "songs.json").write_text(json.dumps(songs, ensure_ascii=False, indent=2), "utf-8")

    total_morae = sum(len(t["morae"]) for ln in lines for t in ln["tokens"])
    print(f"wrote {out}/song.json  lines={len(lines)} tokens={sum(len(l['tokens']) for l in lines)} morae={total_morae}")
    for ln in lines:
        n = sum(len(t["morae"]) for t in ln["tokens"])
        print(f"  {ln['text']}  morae={n}  {ln['naturalness']}")


if __name__ == "__main__":
    main()
