#!/usr/bin/env bash
# Start the FastAPI backend on port 8100.
set -e
cd "$(dirname "$0")"
# --reload-dir app: only watch source. The live filter library lives under
# data/filters/ and authoring a filter writes a new filter.py there; without this
# scope uvicorn would treat that as a code change, restart, wipe the in-memory
# generation queue and kill in-flight render/generation threads.
exec ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100 \
  --reload --reload-dir app
