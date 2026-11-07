#!/usr/bin/env python
"""End-to-end smoke test against a running Mora server.

    ./run.sh &                     # or: .venv/bin/python -m uvicorn server.main:app --port 8787
    .venv/bin/python scripts/smoke.py [--query "ふるさと 童謡"] [--port 8787]

Exercises: health -> ingest -> lyrics -> autosync -> annotate -> card -> slice -> sing.
Prints a PASS/FAIL table and exits non-zero on failure.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

LYRICS = """兎追いしかの山
小鮒釣りしかの川
夢は今もめぐりて
忘れがたき故郷
如何にいます父母
恙なしや友がき
雨に風につけても
思ひ出づる故郷"""

results: list[tuple[str, bool, str]] = []


def check(name: str, fn):
    try:
        detail = fn()
        results.append((name, True, str(detail)[:150]))
        print(f"  PASS  {name}  {str(detail)[:110]}")
        return True
    except Exception as e:  # noqa: BLE001
        results.append((name, False, str(e)[:300]))
        print(f"  FAIL  {name}  {e}")
        return False


class Api:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"

    def req(self, method: str, path: str, body=None, timeout=120):
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                raw = resp.read()
                ctype = resp.headers.get("content-type", "")
                return json.loads(raw) if "json" in ctype else raw
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> {e.code} {e.read()[:300]!r}") from e

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.req("POST", path, body if body is not None else {}, **kw)

    def wait(self, job_id: str, timeout: float = 600) -> dict:
        t0 = time.time()
        last = ""
        while time.time() - t0 < timeout:
            job = self.get(f"/api/jobs/{job_id}")
            msg = f"{job['progress']:>3}% {job['message']}"
            if msg != last:
                print(f"        · {msg}")
                last = msg
            if job["status"] == "done":
                return job
            if job["status"] == "error":
                raise RuntimeError(f"job failed: {job['error']}")
            time.sleep(0.7)
        raise TimeoutError(f"job {job_id} timed out")

    def upload(self, path: str, file_path: Path) -> bytes:
        out = subprocess.run(
            ["curl", "-sS", "-X", "POST", "-F", f"file=@{file_path};type=audio/wav",
             self.base + path],
            capture_output=True, timeout=180,
        )
        if out.returncode != 0:
            raise RuntimeError(out.stderr.decode()[:300])
        return out.stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="Say Yes")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--lyrics", default=None, help="path to a lyrics text file")
    ap.add_argument("--skip-ingest", default=None, help="existing song id")
    args = ap.parse_args()

    api = Api(args.port)
    print(f"Mora smoke test @ {api.base}")

    health = api.get("/api/health")
    check("health", lambda: f"media={health['media'].get('ok')} ollama={health['ollama'].get('ok')} "
                            f"tok={health['tokenizer'].get('ok')}")
    if not health["media"].get("ok"):
        print("  note: media not ok ->", health["media"])

    song_id = args.skip_ingest
    if not song_id:
        job = api.post("/api/ingest", {"query": args.query})
        done = api.wait(job["jobId"])
        song_id = done["result"]["songId"]
        res = done["result"]
        check("name -> lyrics+audio", lambda: f"{res['title']} — {res['artist']} | "
                                              f"lyrics={res.get('lyricsSource')} timing={res.get('timingSource')}")
    check("ingest", lambda: song_id)

    song = api.get(f"/api/songs/{song_id}")
    check("downloaded audio", lambda: f"{song['duration']:.0f}s, lines={len(song['lines'])}, synced={song['synced']}")
    check("auto-synced from one input", lambda: f"synced={song['synced']} timing={song.get('timingSource')}")
    if not song["synced"] or not song["lines"]:
        raise SystemExit("name-only ingest did not produce a synced song")

    song = api.get(f"/api/songs/{song_id}")
    if song["lines"] and not args.lyrics:
        # name-only ingest already fetched real lyrics — never clobber them
        check("lyrics fetched by name", lambda: f"{len(song['lines'])} lines, "
                                                f"source={song.get('lyricsSource')}, timing={song.get('timingSource')}")
    else:
        lyrics = Path(args.lyrics).read_text("utf-8") if args.lyrics else LYRICS
        song = api.post(f"/api/songs/{song_id}/lyrics", {"text": lyrics, "source": "smoke"})
        check("paste lyrics", lambda: f"{len(song['lines'])} lines, "
                                      f"{sum(len(t['morae']) for l in song['lines'] for t in l['tokens'])} morae")

    if not song["synced"]:
        job = api.post(f"/api/songs/{song_id}/autosync")
        done = api.wait(job["jobId"], timeout=900)
        song = api.get(f"/api/songs/{song_id}")
        check("autosync", lambda: f"source={song.get('syncedFrom')} "
                                  f"first={song['lines'][0]['start']:.1f}s last_end={song['lines'][-1]['end']:.1f}s")
    else:
        check("autosync", lambda: "already synced by captions")

    job = api.post(f"/api/songs/{song_id}/annotate")
    api.wait(job["jobId"], timeout=300)
    song = api.get(f"/api/songs/{song_id}")
    filled = sum(1 for l in song["lines"] if l.get("glossZh"))
    nat = {l.get("naturalness") for l in song["lines"]}
    check("annotate", lambda: f"{filled}/{len(song['lines'])} lines glossed, naturalness={sorted(x for x in nat if x)}")

    line = song["lines"][3]
    tok = next(t for t in line["tokens"] if t["kana"] and not t["surface"].isdigit())
    card = api.post("/api/cards", {"songId": song_id, "lineId": line["id"], "tokenId": tok["id"]})
    check("save card", lambda: f"{card['surface']} → {card['sliceUrl']}")

    card = api.post(f"/api/cards/{card['id']}/review", {"grade": 2})
    check("review card", lambda: f"due={card['due']} interval={card['interval']}")

    audio = api.get(f"/api/media/{song_id}/audio", timeout=180)
    check("audio bytes", lambda: f"{len(audio)} bytes")

    wav = api.get(f"/api/media/{song_id}/slice?start={max(0, line['start'])}&end={max(1, line['end'])}&format=wav")
    check("slice wav", lambda: f"{len(wav)} bytes, riff={wav[:4]!r}")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav)
        tmp = Path(f.name)
    try:
        res = api.upload(f"/api/songs/{song_id}/lines/{line['id']}/sing", tmp)
        data = json.loads(res)
        check("sing-back", lambda: f"score={data['score']} "
                                   f"target={data['targetKana'][:12]} heard={data['heardKana'][:12]} "
                                   f"hint={data['hint'][:40]}")
    finally:
        tmp.unlink(missing_ok=True)

    ok = sum(1 for _, p, _ in results if p)
    print(f"\n{ok}/{len(results)} passed")
    for name, passed, detail in results:
        if not passed:
            print(f"  - {name}: {detail}")
    print(f"\nsong id: {song_id}  ->  {api.base}/song/{song_id}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
