"""Mora (モーラ) backend — FastAPI app."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import annotate, jp, kana_diff, store

try:  # the audio module is developed in parallel; never break import on it
    from . import audio as audio_mod
except Exception as _audio_err:  # noqa: BLE001
    audio_mod = None
    _AUDIO_IMPORT_ERROR = repr(_audio_err)

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / "web" / "dist"

app = FastAPI(title="Mora", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------ jobs

_executor = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()

JobFn = Callable[[dict[str, Any]], Any]


def _new_job(kind: str) -> dict[str, Any]:
    job = {
        "id": uuid.uuid4().hex[:12],
        "kind": kind,
        "status": "running",
        "progress": 0,
        "message": "开始…",
        "songId": None,
        "result": None,
        "error": None,
    }
    with _jobs_lock:
        _jobs[job["id"]] = job
    return job


def _run_job(job: dict[str, Any], fn: JobFn) -> None:
    def progress(pct: float, msg: str) -> None:
        job["progress"] = max(0, min(100, round(float(pct))))
        job["message"] = msg

    try:
        job["result"] = fn(progress)
        job["status"] = "done"
        job["progress"] = 100
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(e) or e.__class__.__name__
        job["message"] = job["error"]
        traceback.print_exc()


def _start_job(kind: str, fn: JobFn) -> dict[str, Any]:
    job = _new_job(kind)
    _executor.submit(_run_job, job, fn)
    return job


def _require_audio() -> Any:
    if audio_mod is None:
        raise HTTPException(503, f"音频模块不可用：{globals().get('_AUDIO_IMPORT_ERROR', 'import failed')}")
    return audio_mod


# ------------------------------------------------------------------ health

@app.get("/api/health")
def health() -> dict[str, Any]:
    au = {}
    if audio_mod is not None:
        try:
            au = audio_mod.health()
        except Exception as e:  # noqa: BLE001
            au = {"ok": False, "reason": str(e)}
    else:
        au = {"ok": False, "reason": _AUDIO_IMPORT_ERROR}
    tok = {}
    try:
        jp.tagger()("テスト")
        tok = {"ok": True, "engine": "fugashi+unidic-lite"}
    except Exception as e:  # noqa: BLE001
        tok = {"ok": False, "reason": str(e)}
    return {
        "ok": bool(au.get("ok")) and tok.get("ok", False),
        "media": au,
        "tokenizer": tok,
        "ollama": annotate.health(),
        "version": "0.1.0",
    }


# ------------------------------------------------------------------ ingest

def _looks_like_url(q: str) -> bool:
    return bool(re.match(r"^https?://", q.strip(), re.I))


def _resolve_url(query: str, progress: Callable[[float, str], None]) -> dict[str, Any]:
    au = _require_audio()
    q = query.strip()
    if _looks_like_url(q):
        progress(3, "读取视频信息…")
        return au.probe(q)
    last: Exception | None = None
    for prefix, label in (("ytsearch1:", "YouTube"), ("bilisearch1:", "bilibili")):
        try:
            progress(3, f"在 {label} 搜索「{q}」…")
            info = au.probe(prefix + q)
            if info and info.get("ok"):
                return info
        except Exception as e:  # noqa: BLE001
            last = e
    raise HTTPException(404, f"搜不到这个视频：{q}" + (f"（{last}）" if last else ""))


def _captions_to_lines(cues: list[dict[str, Any]]) -> tuple[list[str], list[tuple[float, float]]]:
    """YouTube auto-captions are short rolling phrases. Glue them into lines."""
    cleaned: list[dict[str, Any]] = []
    for c in cues:
        text = re.sub(r"\s+", "", str(c.get("text", "")))
        text = re.sub(r"[♪♫▶■□]", "", text).strip()
        if len(text) < 2:
            continue
        if not re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text):
            continue
        cleaned.append({"start": float(c["start"]), "end": float(c["end"]), "text": text})

    lines: list[str] = []
    times: list[tuple[float, float]] = []
    buf = ""
    t0 = 0.0
    t1 = 0.0
    prev_end = -99.0
    for c in cleaned:
        gap = c["start"] - prev_end
        if buf and (gap > 0.45 or len(buf) >= 28):
            lines.append(buf)
            times.append((round(t0, 2), round(t1, 2)))
            buf = ""
        if not buf:
            t0 = c["start"]
        else:
            buf += "　"
        buf += c["text"]
        t1 = c["end"]
        prev_end = c["end"]
    if buf:
        lines.append(buf)
        times.append((round(t0, 2), round(t1, 2)))
    # join wrapped phrases without the spacer we used internally
    lines = [ln.replace("　", "") for ln in lines]
    return lines, times



def _source_song_id(info: dict[str, Any], title: str) -> str:
    """Stable ASCII id from the video, not from the (often Japanese) title."""
    url = str(info.get("webpage_url") or info.get("url") or "")
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
    if m:
        return f"yt-{m.group(1).lower()}"
    m = re.search(r"/video/(BV[0-9A-Za-z]+)", url, re.I)
    if m:
        return f"bv-{m.group(1).lower()[:12]}"
    m = re.search(r"/video/(av\d+)", url, re.I)
    if m:
        return f"av-{m.group(1)[2:]}"
    return store.new_id(title)

@app.post("/api/ingest")
def ingest(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "请输入链接或歌名")

    def work(progress: Callable[[float, str], None]) -> dict[str, Any]:
        au = _require_audio()
        info = _resolve_url(query, progress)
        import unicodedata
        title = unicodedata.normalize("NFC", info.get("title") or "未命名")
        artist = unicodedata.normalize("NFC", info.get("uploader") or "")
        song_id = _source_song_id(info, title)
        dest = store.song_dir(song_id)
        dest.mkdir(parents=True, exist_ok=True)
        progress(8, f"下载音频：{title}")
        dl_url = info.get("webpage_url") or query

        def _dl(u: str, lo: float) -> dict[str, Any]:
            return au.download(u, dest, lambda p, m: progress(lo + p * 0.55, m))

        try:
            meta = _dl(dl_url, 8)
        except Exception as first_err:  # noqa: BLE001
            # YouTube media URLs are often bot-blocked on this network; Bilibili is not.
            if _looks_like_url(query):
                raise
            progress(50, "这个源下载失败，改用 bilibili 找同一个歌名…")
            alt = au.probe("bilisearch1:" + query)
            if not alt.get("ok"):
                raise first_err
            info = alt
            title = info.get("title") or title
            meta = _dl(info.get("webpage_url") or query, 52)
        duration = float(meta.get("duration") or info.get("duration") or 0)
        progress(72, "读取字幕…")
        cues = None
        try:
            cues = au.fetch_captions(meta.get("webpage_url") or info.get("webpage_url") or query, dest)
        except Exception as e:  # noqa: BLE001
            print("captions failed:", e)
        lines_text: list[str] = []
        timings: list[tuple[float, float]] | None = None
        if cues:
            lines_text, timings = _captions_to_lines(cues)
        song = store.empty_song(
            song_id,
            title=meta.get("title") or title,
            artist=meta.get("artist") or artist,
            duration=duration,
            source_url=meta.get("webpage_url") or query,
            cover_url=meta.get("thumbnail"),
        )
        song["lines"] = store.build_lines(lines_text, timings) if lines_text else []
        song["lyricsSource"] = "captions" if lines_text else "none"
        store.mark_synced(song)
        progress(92, "生成标注…")
        if lines_text:
            try:
                annotate.annotate_song(song)
            except Exception as e:  # noqa: BLE001
                print("auto-annotate skipped:", e)
        store.save_song(song)
        progress(100, "完成")
        return {"songId": song_id, "title": song["title"],
                "lines": len(song["lines"]), "fromCaptions": bool(lines_text)}

    job = _start_job("ingest", work)
    return {"jobId": job["id"]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job



# ------------------------------------------------------------------ sung-time mapping


def _heard_morae(result: dict[str, Any]) -> tuple[list[str], list[float]]:
    """Flatten ASR output into (mora, start_time) pairs, in order."""
    morae: list[str] = []
    times: list[float] = []
    for seg in result.get("segments") or []:
        words = seg.get("words") or []
        if words:
            units = [(w.get("start"), w.get("end"), w.get("word")) for w in words]
        else:
            units = [(seg.get("start"), seg.get("end"), seg.get("text"))]
        for a, b, text in units:
            try:
                a, b = float(a), float(b)
            except (TypeError, ValueError):
                continue
            ks = kana_diff.morae_of_text(str(text or ""))
            if not ks:
                continue
            span = max(1e-3, b - a)
            step = span / len(ks)
            for i, k in enumerate(ks):
                morae.append(k)
                times.append(a + step * i)
    return morae, times


def _nw_pairs(a: list[str], b: list[str]) -> list[tuple[int, int]]:
    """Monotonic alignment (Needleman-Wunsch). Returns matched index pairs."""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return []
    prev = list(range(m + 1))
    back = [bytearray(m + 1) for _ in range(n + 1)]  # 0 diag 1 up 2 left
    for j in range(m + 1):
        back[0][j] = 2
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        back[i][0] = 1
        ai = a[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ai == b[j - 1] else 1
            diag, up, left = prev[j - 1] + cost, prev[j] + 1, cur[j - 1] + 1
            best = min(diag, up, left)
            cur[j] = best
            back[i][j] = 0 if best == diag else (1 if best == up else 2)
        prev = cur
    pairs: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0 and j > 0:
        d = back[i][j]
        if d == 0:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif d == 1:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def _asr_line_timings(lines: list[dict[str, Any]], result: dict[str, Any]) -> list[tuple[float, float]] | None:
    """Line times derived from where the lyrics actually got sung.

    Aligns the known lyric morae against the morae of the ASR transcript of the
    vocal, then reads each line's time span off the matched ASR words. Beats
    proportional spreading because it survives instrumental intros, repeated
    choruses and different line lengths.
    """
    heard, htimes = _heard_morae(result)
    target: list[str] = []
    line_of: list[int] = []
    for li, line in enumerate(lines):
        for tok in line["tokens"]:
            for mo in tok.get("morae") or []:
                target.append(mo)
                line_of.append(li)
    if not heard or not target:
        return None

    pairs = _nw_pairs(target, heard)
    matched = {ti: hj for ti, hj in pairs}
    if len(matched) / len(target) < 0.55:
        return None

    starts: list[float | None] = [None] * len(lines)
    ends: list[float | None] = [None] * len(lines)
    for ti, hj in matched.items():
        li = line_of[ti]
        t = htimes[hj]
        if starts[li] is None or t < starts[li]:  # type: ignore[operator]
            starts[li] = t
        if ends[li] is None or t > ends[li]:  # type: ignore[operator]
            ends[li] = t

    # a line whose morae were all dropped by the ASR: interpolate
    known = [i for i, v in enumerate(starts) if v is not None]
    if len(known) < max(2, len(lines) // 3):
        return None
    for i in range(len(lines)):
        if starts[i] is None:
            lo = next((k for k in reversed(known) if k < i), None)
            hi = next((k for k in known if k > i), None)
            if lo is not None and hi is not None:
                frac = (i - lo) / (hi - lo)
                starts[i] = starts[lo] + (starts[hi] - starts[lo]) * frac  # type: ignore[operator]
                ends[i] = starts[i]
            elif lo is not None:
                starts[i] = starts[lo]
                ends[i] = starts[lo]
            else:
                starts[i] = ends[i] = 0.0

    # give every line a minimum plausible duration and close gaps
    avg = sum(
        (ends[i] - starts[i]) / max(1, sum(len(t.get("morae") or []) for t in lines[i]["tokens"]))
        for i in range(len(lines))
    ) / max(1, len(lines))
    out: list[tuple[float, float]] = []
    for i in range(len(lines)):
        a, b = float(starts[i]), float(ends[i])  # type: ignore[arg-type]
        n_morae = max(1, sum(len(t.get("morae") or []) for t in lines[i]["tokens"]))
        b = max(b, a + avg * n_morae)
        out.append((a, b))
    for i in range(len(out) - 1):
        a, b = out[i]
        out[i] = (round(a, 2), round(min(b, out[i + 1][0] + 2.0), 2))
    a, b = out[-1]
    out[-1] = (round(a, 2), round(max(b, a + 0.5), 2))
    if sum(max(0.0, b - a) for a, b in out) < 1.0:
        return None
    return out


def _sung_spans(result: dict[str, Any]) -> list[tuple[float, float]]:
    """Where singing actually happens, in order. Falls back to segments."""
    spans: list[tuple[float, float]] = []
    for seg in result.get("segments") or []:
        words = seg.get("words") or []
        if words:
            for w in words:
                try:
                    spans.append((float(w["start"]), float(w["end"])))
                except (KeyError, TypeError, ValueError):
                    continue
        else:
            try:
                spans.append((float(seg["start"]), float(seg["end"])))
            except (KeyError, TypeError, ValueError):
                continue
    spans = sorted((a, b) for a, b in spans if b > a)
    # merge overlapping/adjacent spans (whisper word timings often overlap)
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + 0.02:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def _wall_time_at(spans: list[tuple[float, float]], offset: float) -> float:
    """Map a position inside the *sung* timeline back to wall-clock seconds."""
    if not spans:
        return max(0.0, offset)
    acc = 0.0
    for a, b in spans:
        dur = b - a
        if offset <= acc + dur:
            return a + (offset - acc)
        acc += dur
    return spans[-1][1]



def _sanitize_timings(timings: list[tuple[float, float]], max_line: float = 15.0) -> list[tuple[float, float]]:
    """Force a usable timeline: monotonic, non-overlapping, sane per-line length.

    ASR matches are sparse and sometimes land on an instrumental outro, which can
    hand one line a 60s span. A rough timeline the user can fix beats a precise
    one that is obviously wrong.
    """
    if not timings:
        return timings
    clean: list[tuple[float, float]] = []
    prev_end = 0.0
    for a, b in timings:
        a = max(0.0, float(a), prev_end)
        b = max(a + 0.4, min(float(b), a + max_line))
        clean.append((round(a, 2), round(b, 2)))
        prev_end = b + 0.01
    return clean


def _allocate_timings(spans: list[tuple[float, float]], weights: list[int]) -> list[tuple[float, float]]:
    """Share the sung timeline between lines in proportion to their mora counts.

    Using sung spans (not the whole file) means intros, instrumental breaks and
    the outro don't swallow the lyrics.
    """
    if not spans:
        return [(-1.0, -1.0)] * len(weights)
    total_dur = sum(b - a for a, b in spans)
    total_w = max(1, sum(weights))
    out: list[tuple[float, float]] = []
    acc = 0.0
    for w in weights:
        dur = total_dur * w / total_w
        start = _wall_time_at(spans, acc)
        end = _wall_time_at(spans, acc + dur)
        if end - start < 0.25:
            end = start + 0.25
        out.append((round(start, 2), round(end, 2)))
        acc += dur
    return out

# ------------------------------------------------------------------ songs

@app.get("/api/songs")
def list_songs() -> list[dict[str, Any]]:
    return store.list_songs()


@app.get("/api/songs/{song_id}")
def get_song(song_id: str) -> dict[str, Any]:
    try:
        return store.get_song(song_id)
    except KeyError:
        raise HTTPException(404, "歌曲不存在")


@app.patch("/api/songs/{song_id}")
def patch_song(song_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    song = _song(song_id)
    for key in ("title", "artist", "offset"):
        if key in payload and payload[key] is not None:
            song[key] = payload[key]
    return store.save_song(song)


@app.delete("/api/songs/{song_id}")
def remove_song(song_id: str) -> dict[str, Any]:
    try:
        store.delete_song(song_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))
    return {"ok": True}


def _song(song_id: str) -> dict[str, Any]:
    try:
        return store.get_song(song_id)
    except KeyError:
        raise HTTPException(404, "歌曲不存在")


@app.post("/api/songs/{song_id}/lyrics")
def set_lyrics(song_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    song = _song(song_id)
    text = str(payload.get("text") or "")
    texts = jp.split_lyrics(text)
    if not texts:
        raise HTTPException(400, "歌词是空的")
    timings = None
    if payload.get("timings"):
        raw = payload["timings"]
        if len(raw) == len(texts):
            timings = [(float(t["start"]), float(t["end"])) for t in raw]
    old_had_timing = any(l["start"] >= 0 for l in song.get("lines", []))
    song["lines"] = store.build_lines(texts, timings)
    if old_had_timing and not timings:
        store.remap_timings(song)
    song["lyricsSource"] = str(payload.get("source") or "pasted")
    store.mark_synced(song)
    return store.save_song(song)


@app.patch("/api/songs/{song_id}/lines/{line_id}")
def patch_line(song_id: str, line_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    song = _song(song_id)
    line = next((l for l in song["lines"] if l["id"] == line_id), None)
    if line is None:
        raise HTTPException(404, "行不存在")
    for key in ("start", "end"):
        if key in payload and payload[key] is not None:
            line[key] = round(float(payload[key]), 2)
    for key in ("naturalness", "note", "glossZh"):
        if key in payload:
            line[key] = payload[key]
    store.mark_synced(song)
    return store.save_song(song)


@app.patch("/api/songs/{song_id}/tokens/{token_id}")
def patch_token(song_id: str, token_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    song = _song(song_id)
    found = None
    for line in song["lines"]:
        for i, tok in enumerate(line["tokens"]):
            if tok["id"] == token_id:
                found = (line, i, tok)
                break
        if found:
            break
    if not found:
        raise HTTPException(404, "词不存在")
    line, idx, tok = found
    if payload.get("kana"):
        kana = jp.to_hiragana(str(payload["kana"]).strip())
        tok["kana"] = kana
        tok["morae"] = jp.split_morae(kana)
        tok["romaji"] = jp.to_romaji(kana, tok["pos"].split("-")[0])
        tok["ruby"] = jp.align_ruby(tok["surface"], kana)
        tok["manualReading"] = True
    if "glossZh" in payload:
        tok["glossZh"] = payload["glossZh"]
    if "note" in payload:
        tok["note"] = payload["note"]
    if "saved" in payload:
        tok["saved"] = bool(payload["saved"])
    return store.save_song(song)


@app.put("/api/songs/{song_id}/sync")
def bulk_sync(song_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    song = _song(song_id)
    rows = payload.get("lines") or []
    by_id = {l["id"]: l for l in song["lines"]}
    for row in rows:
        line = by_id.get(row.get("lineId"))
        if not line:
            continue
        if row.get("start") is not None:
            line["start"] = round(float(row["start"]), 2)
        if row.get("end") is not None:
            line["end"] = round(float(row["end"]), 2)
    # close gaps: each line ends where the next starts
    for i in range(len(song["lines"]) - 1):
        cur, nxt = song["lines"][i], song["lines"][i + 1]
        if cur["start"] >= 0 and nxt["start"] > cur["start"]:
            cur["end"] = round(nxt["start"], 2)
    store.mark_synced(song)
    return store.save_song(song)


@app.post("/api/songs/{song_id}/autosync")
def autosync(song_id: str) -> dict[str, Any]:
    song = _song(song_id)
    url = song.get("sourceUrl")

    def work(progress: Callable[[float, str], None]) -> dict[str, Any]:
        au = _require_audio()
        fresh = store.get_song(song_id)
        if not fresh.get("lines"):
            raise RuntimeError("还没有歌词，先粘贴歌词再自动同步")

        spans: list[tuple[float, float]] = []
        asr_result: dict[str, Any] | None = None
        source = "captions"
        if url:
            progress(8, "抓取视频字幕…")
            try:
                cues = au.fetch_captions(url, store.song_dir(song_id))
            except Exception:  # noqa: BLE001
                cues = None
            if cues:
                _texts, timings = _captions_to_lines(cues)
                if timings:
                    spans = [(a, b) for a, b in timings if b > a]
        if not spans:
            source = "asr"
            audio_path = store.audio_path(song_id)
            if not audio_path:
                raise RuntimeError("没有字幕，也找不到音频文件，无法自动同步")
            progress(15, "没有字幕，用语音识别找演唱段落（约需 1 分钟）…")
            result = au.transcribe(audio_path, language="ja")
            asr_result = result
            spans = _sung_spans(result)
            if not spans:
                raise RuntimeError("语音识别没找到清晰的演唱段落，请用 tap 手动同步")

        progress(70, f"按 {source} 时间轴对齐歌词…")
        weights = [max(1, sum(len(t.get("morae") or []) for t in l["tokens"])) for l in fresh["lines"]]
        timings = None
        if source == "asr" and asr_result:
            timings = _asr_line_timings(fresh["lines"], asr_result)
            if timings:
                source = "asr-mora"
        if not timings:
            timings = _allocate_timings(spans, weights)
        timings = _sanitize_timings(timings)
        for line, (a, b) in zip(fresh["lines"], timings):
            line["start"], line["end"] = a, b
        store.mark_synced(fresh)
        fresh["syncedFrom"] = source
        store.save_song(fresh)
        progress(100, "已自动同步" + ("（字幕）" if source == "captions" else "（按演唱位置对齐，建议核对）"))
        return {"songId": song_id, "source": source, "spans": len(spans)}

    job = _start_job("autosync", work)
    return {"jobId": job["id"]}


@app.post("/api/songs/{song_id}/annotate")
def annotate_song_endpoint(song_id: str) -> dict[str, Any]:
    _song(song_id)

    def work(progress: Callable[[float, str], None]) -> dict[str, Any]:
        song = store.get_song(song_id)
        annotate.annotate_song(song, progress)
        store.save_song(song)
        return {"songId": song_id, "lines": len(song["lines"])}

    job = _start_job("annotate", work)
    return {"jobId": job["id"]}


@app.post("/api/songs/{song_id}/lines/{line_id}/tokens/{token_id}/gloss")
def token_gloss(song_id: str, line_id: str, token_id: str) -> dict[str, Any]:
    song = _song(song_id)
    try:
        tok = annotate.annotate_one_token(song, line_id, token_id)
    except annotate.OllamaError as e:
        raise HTTPException(503, str(e))
    store.save_song(song)
    return tok


# ------------------------------------------------------------------ cards

@app.get("/api/cards")
def list_cards() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in store.list_songs():
        try:
            song = store.get_song(s["id"])
        except KeyError:
            continue
        for c in song.get("cards", []):
            out.append({**c, "songTitle": song.get("title")})
    out.sort(key=lambda c: c.get("due") or "")
    return out


@app.post("/api/cards")
def create_card(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    song = _song(str(payload.get("songId")))
    try:
        card = store.ensure_card(song, str(payload.get("lineId")), str(payload.get("tokenId")))
    except KeyError:
        raise HTTPException(404, "找不到这一行或这个词")
    store.save_song(song)
    return card


@app.delete("/api/cards/{card_id}")
def delete_card(card_id: str) -> dict[str, Any]:
    for s in store.list_songs():
        song = store.get_song(s["id"])
        if any(c["id"] == card_id for c in song.get("cards", [])):
            store.drop_card(song, card_id)
            store.save_song(song)
            return {"ok": True}
    raise HTTPException(404, "卡片不存在")


@app.post("/api/cards/{card_id}/review")
def review(card_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    grade = int(payload.get("grade", 2))
    for s in store.list_songs():
        song = store.get_song(s["id"])
        for c in song.get("cards", []):
            if c["id"] == card_id:
                store.review_card(c, grade)
                store.save_song(song)
                return c
    raise HTTPException(404, "卡片不存在")


# ------------------------------------------------------------------ sing-back

@app.post("/api/songs/{song_id}/lines/{line_id}/sing")
async def sing(song_id: str, line_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    au = _require_audio()
    song = _song(song_id)
    line = next((l for l in song["lines"] if l["id"] == line_id), None)
    if line is None:
        raise HTTPException(404, "行不存在")

    tmpdir = Path(tempfile.mkdtemp(prefix="mora-sing-"))
    suffix = Path(file.filename or "x.webm").suffix or ".webm"
    raw = tmpdir / f"upload{suffix}"
    try:
        raw.write_bytes(await file.read())
        wav = tmpdir / "rec16k.wav"
        try:
            au.extract_audio_to_wav(raw, wav)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"录音转码失败：{e}")
        try:
            result = au.transcribe(wav, language="ja")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, f"语音识别不可用：{e}")
        target = kana_diff.target_morae(line["tokens"])
        heard_text = str(result.get("text") or "")
        heard = kana_diff.morae_of_text(heard_text)
        diff = kana_diff.diff_morae(target, heard)
        return {
            "targetKana": "".join(target),
            "heardKana": "".join(heard),
            "heardText": heard_text,
            "targetText": line["text"],
            **diff,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ------------------------------------------------------------------ media

_MEDIA_TYPES = {".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".webm": "audio/webm"}


def _media_type(path: Path) -> str:
    return _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _send_file(path: Path, request: Request, cache: str = "public, max-age=3600") -> Response:
    size = path.stat().st_size
    rng = request.headers.get("range") or request.headers.get("Range")
    if rng:
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        if m:
            start = int(m.group(1) or 0)
            end = int(m.group(2)) if m.group(2) else size - 1
            end = min(end, size - 1)
            if start > end:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
            length = end - start + 1
            with path.open("rb") as f:
                f.seek(start)
                data = f.read(length)
            return Response(
                content=data,
                status_code=206,
                media_type=_media_type(path),
                headers={
                    "Content-Range": f"bytes {start}-{end}/{size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(length),
                    "Cache-Control": cache,
                },
            )
    return FileResponse(path, media_type=_media_type(path),
                        headers={"Accept-Ranges": "bytes", "Cache-Control": cache})


@app.get("/api/media/{song_id}/audio")
def media_audio(song_id: str, request: Request) -> Response:
    try:
        p = store.audio_path(song_id)
    except ValueError:
        raise HTTPException(400, "bad id")
    if not p:
        raise HTTPException(404, "音频还没下载好")
    return _send_file(p, request)


@app.get("/api/media/{song_id}/slice")
def media_slice(song_id: str, request: Request, start: float = 0.0, end: float = 1.0) -> Response:
    au = _require_audio()
    src = store.audio_path(song_id)
    if not src:
        raise HTTPException(404, "音频还没下载好")
    end = max(start + 0.2, min(end, start + 20.0))
    key = f"{song_id}_{start:.2f}_{end:.2f}.wav"
    dest = store.CACHE / "slices" / key
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            au.slice_audio(src, start, end, dest)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"切片失败：{e}")
    return _send_file(dest, request, cache="public, max-age=86400")


# ------------------------------------------------------------------ static SPA

if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):  # noqa: ANN201
        if full_path.startswith("api/"):
            raise HTTPException(404, "not found")
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        index = WEB_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(404, "前端还没构建，先运行 ./run.sh")
else:
    @app.get("/")
    def no_web() -> JSONResponse:
        return JSONResponse({
            "app": "Mora",
            "hint": "前端还没构建：cd web && pnpm install && pnpm build",
            "docs": "/docs",
        })
