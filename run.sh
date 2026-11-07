#!/usr/bin/env bash
# Mora — local Japanese-song lab. Starts the API + serves the built web app.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8787}"

if [ ! -x .venv/bin/python ]; then
  echo "==> creating venv"
  python3 -m venv --system-site-packages .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q fastapi "uvicorn[standard]" python-multipart fugashi unidic-lite
fi

if [ ! -f web/dist/index.html ]; then
  echo "==> building frontend"
  ( cd web && pnpm install && pnpm build )
fi

echo "==> Mora  http://127.0.0.1:${PORT}"
exec .venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port "${PORT}"
