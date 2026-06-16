#!/usr/bin/env bash
# Start the FastAPI backend on port 8100.
set -e
cd "$(dirname "$0")"
exec ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload
