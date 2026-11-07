# Mora (モーラ) — v1 contract

Local web app for learning to **sing** Japanese songs while actually learning Japanese.
Everything runs on this Mac. Nothing is uploaded anywhere.

## Files & ownership (do not write outside your scope)

| Path | Owner | Contents |
|---|---|---|
| `web/` | **frontend** | Vite + React + TS SPA. All styling lives here. |
| `server/audio/` | **audio** | Pure-python: yt-dlp ingest, ffmpeg, whisper, caption alignment. |
| `server/*.py` (except `server/audio/`) | **lead** | FastAPI app, tokenizer, annotator, store. |
| `contract/` | **lead** | This file + fixtures. Read only. |
| `data/` | runtime | Never hand-edit; created by the server. |

## Run commands

```bash
cd /Users/media/Documents/dsh_playground/mora
./run.sh            # builds web/ if needed, starts uvicorn on 127.0.0.1:8787
.venv/bin/python -m uvicorn server.main:app --port 8787 --reload   # backend dev
cd web && pnpm install && pnpm dev                                 # frontend dev on :5173, proxies /api -> :8787
```

Python is `.venv/bin/python` (3.10, has torch + faster_whisper via system site packages).
Use `pnpm`, never npm.

## What v1 is

1. **Add a song** from a YouTube/Bilibili URL (yt-dlp) or by search.
2. **Lyrics** pasted by the user, or pulled from YouTube captions if available.
3. **Tokenize** → furigana, kana, romaji, morae, POS per token.
4. **Sync** line start/end times: tap-to-sync, or auto from YouTube captions, or even distribution.
5. **Karaoke view**: the current mora lights up. Tempo 0.5–1.0× *without pitch change*. A–B loop. Toggles for furigana / romaji / translation.
6. **Study view**: per-token gloss (Chinese), naturalness badge 🟢🟡🔴, note, save-as-card.
7. **Review view**: saved cards, prompt = audio slice from the real vocal.
8. **Sing-back** (experimental): record one line → whisper transcribes → kana-level diff vs the target → tells you which mora you dropped.

## Non-goals for v1

Stems/Demucs, pitch scoring, real note detection, LLM chat tutor, mobile, multi-user, auth, offline packaging.

---

# API

Base `http://127.0.0.1:8787`. All JSON. Errors: `{"error": "human readable", "detail": "..."}` with 4xx/5xx.

### Health & jobs

```
GET  /api/health
     -> {ok, ytdlp, ffmpeg, whisper:{ok,model}, ollama:{ok,model}, tokenizer}

POST /api/ingest   {query:"https://... | search text"} -> {jobId}
POST /api/songs/{id}/autosync  -> {jobId}
POST /api/songs/{id}/annotate  -> {jobId}
GET  /api/jobs/{jobId} -> {id, kind, status:"running|done|error", progress:0..100, message, songId?, result?}
```

Long operations (download, whisper, LLM) are always jobs. Frontend polls every 700 ms.

### Songs

```
GET   /api/songs                 -> SongSummary[]
GET   /api/songs/{id}            -> Song
DELETE /api/songs/{id}           -> {ok}
PATCH /api/songs/{id}            {title?, artist?, offset?} -> Song
POST  /api/songs/{id}/lyrics     {text}  -> Song   # paste lyrics; re-tokenizes, keeps timings if line count matches
PATCH /api/songs/{id}/lines/{lineId}  {start?, end?, naturalness?, note?, glossZh?} -> Song
PATCH /api/songs/{id}/tokens/{tokenId} {kana?, glossZh?, note?} -> Song   # manual reading override
PUT   /api/songs/{id}/sync       {lines:[{lineId,start,end}]} -> Song     # bulk from tap-sync
```

### Cards

```
GET  /api/cards                  -> Card[]
POST /api/cards                  {songId, lineId, tokenId} -> Card   # idempotent per token
DELETE /api/cards/{id}           -> {ok}
POST /api/cards/{id}/review      {grade:0|1|2|3} -> Card              # 0 again 1 hard 2 good 3 easy
```

### Sing-back

```
POST /api/songs/{id}/lines/{lineId}/sing   multipart: file=<webm/opus>
     -> {targetKana, heardKana, diff:[{op:"eq"|"del"|"ins"|"sub", a?, b?}], score:0..100, moraeOk, moraeTotal, hint}
```

### Media

```
GET /api/media/{id}/audio            # supports Range requests (needed for seeking)
GET /api/media/{id}/slice?start=12.4&end=15.1&format=wav   # for cards; wav, 22.05kHz mono
```

---

# Types (authoritative)

```ts
type Naturalness = "green" | "yellow" | "red";

interface SongSummary {
  id: string; title: string; artist: string; duration: number;
  audioUrl: string; coverUrl: string | null;
  linesTotal: number; cards: number; synced: boolean;
  thumbHue: number;           // 0-360, for a generated gradient placeholder
}

interface Song {
  id: string; title: string; artist: string; duration: number;
  audioUrl: string; coverUrl: string | null;
  sourceUrl: string | null; offset: number;   // seconds, added to every line time
  synced: boolean; createdAt: string;
  cards: Card[];
  lines: Line[];
}

interface Line {
  id: string; text: string;
  start: number; end: number;          // seconds; -1 when unsynced
  glossZh: string | null;
  naturalness: Naturalness | null;
  note: string | null;                 // grammar / "why it's said this way"
  tokens: Token[];
}

interface Token {
  id: string; surface: string;
  ruby: { text: string; rt?: string }[];   // rt absent => no furigana needed
  kana: string;        // hiragana reading, "" for punctuation/space
  romaji: string;      // "" for punctuation/space
  morae: string[];     // ["きょ","う"] — see mora rules
  pos: string;         // 名詞 / 動詞 / 助詞 / 記号 ...
  dictForm: string | null;
  glossZh: string | null;
  naturalness: Naturalness | null;
  note: string | null;
  flags: ("ateji" | "jodai" | "rare-reading" | "kanji-trap")[];
  saved: boolean;
}

interface Card {
  id: string; songId: string; lineId: string; tokenId: string;
  surface: string; kana: string; romaji: string; glossZh: string | null;
  lineText: string;
  start: number; end: number;      // slice into the song
  sliceUrl: string;
  due: string; interval: number; ease: number; reps: number; lapses: number;
  createdAt: string;
}
```

### Mora rules (exact, get these right)

Split the hiragana `kana` into morae:

- small kana `ゃ ゅ ょ ぁ ぃ ぅ ぇ ぉ ゎ` attach to the **previous** mora: `きょ` = 1 mora.
- `っ` is its own mora. `ー` (long vowel mark) is its own mora. `ん` is its own mora.
- `ゔ`/voiced variants normal. `・`/space/punctuation → `morae: []`.
- Count must satisfy: `がっこう`=4, `きょう`=2, `おんな`=3, `しんぶん`=4, `コーヒー`→`こーひー`=4.

Romaji: Hepburn-ish, `し→shi, ち→chi, つ→tsu, ふ→fu, じ→ji, を→o, ん→n`, long `ー` repeats the previous vowel, `っ` doubles the next consonant. `kana` is hiragana even when the surface is katakana.

**Timing is not on the wire.** The frontend flattens `line.tokens[].morae` into one ruler and distributes it evenly over `[start, end]`:
`tOfMorae(i) = start + (end - start) * i / N`, current index = `floor((t - start) / (end - start) * N)`.
So the ruler is the single source of truth for "what to highlight".

---

# Frontend spec

Routing: `/` library, `/song/:id` (tabs: 歌う / 読む / 覚える).

## Design language (dark, quiet, type-first)

```
--bg:#0B0D12  --surface:#12151D  --surface-2:#181D28  --line:#252B38
--text:#E8EAF0 --muted:#8A90A2 --dim:#4A5163
--accent:#FF5C8A (sakura)  --green:#4ADE80  --yellow:#FBBF24  --red:#F87171
--teal:#5EEAD4 (current mora)
font: "Hiragino Sans","Noto Sans JP",system-ui
lyrics size: clamp(26px, 3.6vw, 52px); weight 500; letter-spacing .02em
```

- Lyrics are the hero. No chrome competing with them. Big vertical breathing room.
- Furigana: `<ruby>` with `rt` at `0.42em`, `--muted`, positioned tight.
- The **morae ruler** under each active line: one small pill per mora, equal width (~14–18px), current one `--teal` filled + 2px glow, sung ones `--dim`, unsung `--line`.
- Karaoke line states: current line full opacity; previous line `0.35`; next line `0.55`. Translucent, never hidden — you need to see where you're going.
- Everything keyboard-drivable: `Space` play/pause, `←/→` seek 3s, `L` loop, `F` furigana, `R` romaji, `T` translation.
- No modals for the main flow. Popovers for token detail.

## 1. Library `/`

Header `モーラ` + one-line pitch. A single wide input: *"Paste a YouTube / Bilibili link, or type a song name"* + Add button. Below: song cards (cover gradient from `thumbHue`, title, artist, `8 lines · 5 cards · synced`). Empty state explains the loop in 3 steps.

## 2. Karaoke `歌う` — the product lives here

```
ふるさと                                    ← back   0:12 / 2:58
────────────────────────────────────────────────────────────
              う さ ぎ お い し か の や ま       ← furigana row (if on)
              兎 追 い し か の 山                ← lyric, current mora tinted
              u sa gi o i shi ka no ya ma         ← romaji row
              ●─●─●─●─●─●─●─●─●─●                ← morae ruler
────────────────────────────────────────────────────────────
▶  0.75×  [A—B]  ふりがな ローマ字 訳    ⌨tap-sync
```

- Auto-scroll the lyric list so the current line is centered; the current line is huge, neighbors visible above/below at reduced opacity.
- Tempo buttons `.5 .65 .75 .9 1.0` — implement with **preservesPitch** time-stretch. `audio.playbackRate` + `audio.preservesPitch = true` is acceptable for v1; if it sounds bad, use a 2-line granular stretcher. Do not resample (pitch must not shift).
- A–B loop: click `A` then `B` to set from the current position (or drag on a mini timeline). Loop must not drift.
- `tap-sync` mode: overlay that dims everything, shows the next line, and on `Space` records `currentTime` as that line's start (and previous line's end). Saves via `PUT /sync` when done. Esc cancels.
- Unsynced song (`start < 0`): play still works, ruler just doesn't advance; show a hint chip "未同期 → tap to sync".

## 3. Study `読む`

Left: the lyrics with furigana, each line with a naturalness dot. Right: sticky panel for the selected token — surface, ruby, kana, romaji, POS, dict form, `glossZh`, `note`, and `＋ カードに保存` / `読み方を直す`.

Naturalness legend with plain Chinese: 🟢 日常可用 · 🟡 诗意但成立 · 🔴 只存在于歌词. Red tokens get a one-line "换成自然说法" note when available.

## 4. Review `覚える`

Card stack. Front: the audio slice auto-plays once (`sliceUrl`), plus the lyric line with the target word blanked (`＿＿＿`). User thinks, then Space reveals: surface / kana / romaji / gloss. Then `Again 1 · Hard 2 · Good 3 · Easy 4` → `POST /review`. Show due count, and `next due in X` after grading. Empty state: "先存几张卡".

## 5. Sing-back (in the karaoke view, per line)

A small `🎤` button on the current line → hold-to-record (MediaRecorder, `audio/webm;codecs=opus`) → `POST /sing` → shows:
`你唱: うさぎおいしかのやま  / 目标: ...` with a character diff (green equal, red missing, amber extra) and `score`. Copy: "实验性：靠语音识别判断，仅供参考".

## Mock mode (required)

`web/src/api.ts` must export a `USE_MOCK` switch driven by `import.meta.env.VITE_MOCK`. When on, every call resolves from `web/src/mock/` (copy of `contract/fixtures/*`), with fake latency and a fake job that completes in 2s. The app must be fully clickable and demoable with the backend off. This is how you develop.

---

# `server/audio/` interface (audio owns this, lead consumes it)

```python
# server/audio/__init__.py
def probe(url: str) -> dict:
    """{'ok':bool,'title','uploader','duration','webpage_url','thumbnail'} — no download."""

def download(url: str, dest: Path, progress: Callable[[float, str], None]) -> dict:
    """Download best audio to dest/audio.m4a. Returns {'path','title','artist','duration','thumbnail','webpage_url'}."""

def fetch_captions(url: str, workdir: Path) -> list[dict] | None:
    """YouTube/Bilibili subtitles if any. [{'start':float,'end':float,'text':str}] sorted. None if none."""

def slice_audio(src: Path, start: float, end: float, dest: Path) -> None:
    """ffmpeg -> 22.05kHz mono wav, exact [start,end], 30ms fade in/out."""

def transcribe(audio: Path, language: str = "ja") -> dict:
    """faster-whisper 'small' (already cached: Systran/faster-whisper-small).
    Returns {'text':str,'segments':[{'start','end','text'}],'lang':str}."""

def health() -> dict: ...
```

Everything must be import-safe without the optional deps present (return `{ok: False, reason}`).

---

# Acceptance for v1

1. `./run.sh` starts; `GET /api/health` all green.
2. Paste a Bilibili or YouTube URL → job downloads → song appears in library → lyrics can be pasted → tokens show furigana/kana/romaji/morae.
3. `annotate` job fills `glossZh` + `naturalness` on lines and tokens via ollama.
4. Karaoke view plays the real audio, highlights morae in time, tempo + A–B loop work.
5. Tap-sync sets timings and persists.
6. Saving a token creates a card with a working `sliceUrl` that plays in review.
7. Sing-back returns a diff for a line.
8. `cd web && pnpm build` is clean (no TS errors).
