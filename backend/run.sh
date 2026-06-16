#!/usr/bin/env bash
# Start the FastAPI backend on port 8100.
set -e
cd "$(dirname "$0")"
# Authoring a filter writes a new filter.py under data/filters/. On macOS the
# watchfiles backend over-watches the parent dir, so --reload-dir app is NOT enough
# (uvicorn still sees those writes and restarts — wiping the in-memory generation
# queue and killing in-flight render threads). The reliable guard is an ABSOLUTE
# --reload-exclude on the data dir, which uvicorn's FileFilter honours.
exec ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100 \
  --reload --reload-dir app --reload-exclude "$(pwd)/data"
