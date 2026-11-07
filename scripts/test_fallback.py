#!/usr/bin/env python
"""Prove the demo-fallback banner appears when the backend is down, and that the
app recovers by itself (no manual reload) once the backend returns.

    python3 scripts/test_fallback.py

Needs: Vite dev server on :5173 (VITE_MOCK=0) and the real backend on :8787.
Leaves the backend running afterwards.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://localhost:5173/"
BANNER = ".mode-banner"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")


def backend_up() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8787/api/ping", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def stop_backend() -> None:
    subprocess.run(["pkill", "-f", "uvicorn server.main:app"], capture_output=True)
    for _ in range(20):
        if not backend_up():
            return
        time.sleep(0.25)


def start_backend() -> None:
    subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), "-m", "uvicorn", "server.main:app",
         "--host", "127.0.0.1", "--port", "8787"],
        cwd=str(ROOT), stdout=open("/tmp/mora-server.log", "ab"), stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    for _ in range(60):
        if backend_up():
            return
        time.sleep(0.5)
    raise RuntimeError("backend did not come back up")


def main() -> int:
    from playwright.sync_api import sync_playwright

    print("stopping backend")
    stop_backend()
    check("backend stopped", not backend_up())

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 820})
        page.goto(BASE, wait_until="domcontentloaded")

        appeared = True
        try:
            page.wait_for_selector(BANNER, timeout=20000)
        except Exception:
            appeared = False
        check("fallback banner shown while backend down", appeared,
              "" if appeared else "banner never appeared")
        page.screenshot(path="/tmp/fallback_banner.png")

        print("starting backend")
        start_backend()

        gone = True
        t0 = time.time()
        try:
            page.wait_for_selector(BANNER, state="detached", timeout=25000)
        except Exception:
            gone = False
        elapsed = time.time() - t0
        check("banner clears on its own (no manual reload)", gone, f"{elapsed:.1f}s")

        # after recovery it should have reloaded into the live dataset
        try:
            page.wait_for_selector("text=SAY YES", timeout=15000)
            live = True
        except Exception:
            live = False
        check("page now shows real library data", live,
              "" if live else "never saw a real song title")
        page.screenshot(path="/tmp/fallback_recovered.png")
        browser.close()

    ok = sum(1 for _, p, _ in results if p)
    print(f"\n{ok}/{len(results)} passed")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
