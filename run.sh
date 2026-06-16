#!/usr/bin/env bash
# Start backend (8100) + frontend (5200) together. Ctrl-C stops both.
set -e
cd "$(dirname "$0")"

cleanup() { kill 0 2>/dev/null; }
trap cleanup EXIT INT TERM

echo "→ backend  http://localhost:8100"
( cd backend && ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload ) &

echo "→ frontend http://localhost:5200"
( cd frontend && npm run dev ) &

wait
