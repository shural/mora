# Mora モーラ

**A local lab for learning to sing Japanese songs — without learning broken Japanese.**

You bring a song you already love. Mora turns it into a sound-first study sheet: every mora
gets a beat, every kanji gets a reading, every phrase gets an honest label telling you whether
it's Japanese you can actually use or Japanese that only exists inside a song. Then it makes
you sing it back and tells you which kana you dropped.

Everything runs on your Mac. Nothing is uploaded. Your audio and your notes stay in `data/`.

```
song you love
  → mora-synced lyrics (furigana · romaji · 中译 · 自然度)
  → loop it, slow it, sing it
  → the words you fumbled become audio-cloze cards cut from that exact second of the vocal
  → sing it back → kana-level diff of what you actually sang
```

---

## Why not just a lyrics app

There are already lyric viewers with furigana and translation. They solve the wrong problem
for a Chinese speaker. **Kanji gives you meaning for free — it doesn't give you sound.** Your
bottlenecks are 読み, モーラ数 and アクセント, and "spelling a Japanese word wrong" usually
means *"I dropped a っ / ー / ん"*, not "I picked the wrong kana".

So Mora is built around four things a lyrics reader can't do:

| | |
|---|---|
| **モーラ・ルーラー** | Lyrics are split into morae and laid on a beat ruler synced to the audio. `きょう` is 2 beats, `がっこう` is 4. You stop singing syllables and start singing morae. |
| **自然度 (naturalness)** | Every line is tagged 🟢 日常可用 / 🟡 诗意但成立 / 🔴 只存在于歌词, with the natural way to say it. Songs are full of 文語 (`〜しか`, `〜がたき`, `如何にいます`) that you must **not** copy into conversation. Most apps quietly teach you this broken Japanese. |
| **当て字 reading resolution** | `故郷` is こきょう in a dictionary and ふるさと in the song. `運命`→さだめ, `地球`→ほし. Lyrics routinely break the dictionary, so the app flags it and lets you override the reading per word. |
| **唱回来 diff** | Record one line → whisper transcribes you → the app diffs at **mora level**: *"丢掉了促音「っ」——要停一拍再发下一个音"*. This is the only feature that fixes "I don't spell it correctly". |

Plus a **kanji-trap** check for Chinese speakers (`大丈夫` `勉強` `手紙` `汽車` `娘` `愛人` `我慢`…),
because you will read those right and understand them wrong.

---

## Quick start

```bash
cd mora
./run.sh
# → http://127.0.0.1:8787
```

First run builds the frontend and the Python venv (~2 min). Requirements, all already on this
machine: `yt-dlp`, `ffmpeg`, Python 3.10 with `torch` + `faster-whisper` (`small` model cached),
Node + `pnpm`, and Ollama for annotations (default model `gemma4:31b-cloud`).

Frontend dev with mock data (no backend needed):

```bash
cd web && pnpm install && pnpm dev     # http://127.0.0.1:5173
```

## How to use it

1. **Add a song** — paste a YouTube / Bilibili URL, or type a song name (it searches both).
   Audio is downloaded locally; if the video has subtitles they're used for a first-pass sync.
2. **Paste the lyrics** — in `読む` → 编辑歌词. (Automatic captions are a rough machine transcript,
   real lyrics always beat them; pasting also fixes 当て字 readings for the whole song.)
3. **Sync** — try 自动同步 (subtitles → or whisper on the audio), then fix by hand with
   `⌨ tap-sync`: press Space as each line starts. Takes ~20s for a whole song and never drifts.
4. **Sing** — `歌う`: tempo 0.5×, A–B loop one phrase, and follow the ruler. Pitch never shifts
   when you slow it down.
5. **Study** — `読む`: click any word for its reading, gloss, grammar note, naturalness. Save it.
6. **Review** — `覚える`: the prompt is 1.5s of the actual vocal. You'll remember the word *and*
   the song.
7. **Check yourself** — 🎤 on a line, sing it, read the mora diff.

## Under the hood

```
server/jp.py          fugashi + unidic-lite → tokens, furigana alignment, morae, romaji,
                      ｜当て字 flags, kanji traps
server/annotate.py     Ollama → 中译 · 自然度 · 语法注 · 词义   (batched, ~4s for a whole song)
server/audio/         yt-dlp (YouTube android-client fallback) · ffmpeg · faster-whisper · captions
server/kana_diff.py   mora-level SequenceMatcher + plain-language hints
server/store.py       one JSON doc per song under data/songs/<id>/
server/main.py        FastAPI: ingest/annotate/autosync as pollable jobs
web/                  Vite + React + TS, dark karaoke UI
```

Two deliberate choices worth knowing:

- **Timing is not in the data model.** Each line carries `start`/`end`; the ruler distributes
  morae evenly across that line. This is why tap-sync is enough to make a song fully usable,
  and why the app never "drifts" the way forced-alignment pipelines do.
- **Nothing is a hard dependency.** No Ollama → no glosses, everything else works. No whisper →
  no sing-back, no ASR sync, everything else works. The app degrades, it doesn't break.

## What is experimental

- Sing-back is judged by speech recognition on *singing*, which is genuinely hard. Treat it as a
  hint about dropped morae, not a verdict on your voice.
- `自然度` and `中译` are model output. They're good, they're not a textbook. The goal is to make
  you notice *"huh, nobody says that"* — not to be your authority.
- ASR auto-sync is a rough pass (proportional mora allocation over detected sung spans). Tap-sync
  is the ground truth.

## Legal

Mora downloads audio you have a right to listen to and annotates lyrics **you** supply, for
private study. It never redistributes lyrics or audio. Don't ship a database of other people's
lyrics with it.

## Roadmap

- Real note detection (CREPE) → true per-mora timing + pitch display
- Demucs vocal split → free instrumental track + pitch scoring
- SRS scheduling upgrade (FSRS), cross-song "known words" so later songs unlock faster
- 字余り/字足らず warnings: morae vs. notes, and where the singer breathes
- Extension: send the YouTube tab you're already watching straight into Mora
