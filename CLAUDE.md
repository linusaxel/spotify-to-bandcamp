## Project

Web app that fetches Spotify playlist tracks and searches Bandcamp for matching links.
- Backend: FastAPI (Python) in `backend/`
- Frontend: Vite + vanilla JS in `ui/`
- Deployment: Railway via Dockerfile (single service serves both)

## Running locally

Backend:
```
source .venv/bin/activate && uvicorn backend.app:app --reload
```

Frontend:
```
cd ui && npx vite
```

Open http://127.0.0.1:5173 (must use 127.0.0.1, NOT localhost)

## Key architecture notes

- Per-user Spotify OAuth: each visitor logs in with their Spotify account
- Session stored in signed cookies via SessionMiddleware
- In dev: frontend on :5173 talks to backend on :8000 directly (cross-origin with credentials)
- In production: FastAPI serves built Vite static files from `ui/dist/` — single origin, no CORS needed
- `API_BASE` in main.js auto-detects dev vs prod by checking the port

## Spotify API gotchas

- Redirect URIs must use `127.0.0.1` (not `localhost`) — Spotify rejects `localhost`
- Redirect URI in .env must EXACTLY match what's registered in Spotify Developer Dashboard
- The `.cache` file stores Spotify tokens locally — delete it when switching auth approaches
- bandcamp-search `item_url_path` already contains full URLs — don't prepend `https://bandcamp.com`

## Preferences

- Always run the app for the user — don't ask, just do it.
