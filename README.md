# AI Music Video Studio

[![Support me on Patreon](https://img.shields.io/badge/Patreon-Support%20my%20work-FF424D?style=flat&logo=patreon&logoColor=white)](https://www.patreon.com/AndersBjarby)

A tool for building music videos: create a project, upload a song, and the app
converts it to WAV, runs spectral beat analysis (bass / mid / high onsets),
extracts time-stamped lyrics with whisper.cpp, and analyses mood & style via
OpenRouter (`google/gemini-3.5-flash`). You then cut, trim and arrange media on a
horizontal NLE timeline with a synced vertical lyric column and a live preview.

> Step 1 scope: projects, song upload + analysis, media library, timeline with
> cut/trim, synced lyrics, live preview. Effects come next.

## Architecture
- **backend/** — FastAPI (port 8100). SQLite + filesystem under `backend/data/`.
  Shells out to `ffmpeg`/`ffprobe` and `whisper-cli`; spectral analysis on
  numpy/scipy; mood via OpenRouter.
- **frontend/** — React + Vite + TypeScript + Tailwind + Zustand (port 5200).

See `docs/CONTRACT.md` for the full interface contract.

## Prerequisites
- `ffmpeg` / `ffprobe` on PATH
- whisper.cpp built at `/Users/andersbj/Projekt/whisper.cpp` with the
  `ggml-large-v3-turbo.bin` model (paths configurable in `backend/.env`)
- Python 3.12+ and Node 18+

## Setup
```bash
# backend (venv reuses system numpy/scipy)
cd backend
python3 -m venv --system-site-packages venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in OPENROUTER_API_KEY + whisper paths

# frontend
cd ../frontend
npm install
```

## Run
```bash
./run.sh            # starts backend (8100) + frontend (5200)
# or separately:
cd backend && ./run.sh
cd frontend && npm run dev
```
Open http://localhost:5200
