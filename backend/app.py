import os
import json
import asyncio
import secrets
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from bandcamp_search.search import search, SearchType
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sse_starlette.sse import EventSourceResponse

load_dotenv()

app = FastAPI()

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", secrets.token_hex(32)),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
SCOPE = "playlist-read-private"


def create_spotify_oauth():
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
    )


@app.get("/api/auth/login")
async def login():
    oauth = create_spotify_oauth()
    auth_url = oauth.get_authorize_url()
    return RedirectResponse(auth_url)


@app.get("/api/auth/callback")
async def callback(request: Request, code: str = None, error: str = None):
    if error or not code:
        return RedirectResponse(FRONTEND_URL)
    oauth = create_spotify_oauth()
    token_info = oauth.get_access_token(code)
    request.session["token_info"] = token_info
    return RedirectResponse(FRONTEND_URL)


@app.get("/api/auth/status")
async def auth_status(request: Request):
    token_info = request.session.get("token_info")
    if token_info:
        oauth = create_spotify_oauth()
        if oauth.is_token_expired(token_info):
            try:
                token_info = oauth.refresh_access_token(token_info["refresh_token"])
                request.session["token_info"] = token_info
            except Exception:
                request.session.pop("token_info", None)
                return JSONResponse({"logged_in": False})
        return JSONResponse({"logged_in": True})
    return JSONResponse({"logged_in": False})


@app.get("/api/auth/logout")
async def logout(request: Request):
    request.session.pop("token_info", None)
    return RedirectResponse(FRONTEND_URL)


def get_spotify_client(token_info):
    return spotipy.Spotify(auth=token_info["access_token"])


def get_spotify_tracks(sp, playlist_id):
    results = sp.playlist_tracks(playlist_id)
    tracks = results["items"]
    while results["next"]:
        results = sp.next(results)
        tracks.extend(results["items"])
    return [(t["track"]["name"], t["track"]["artists"][0]["name"]) for t in tracks if t["track"]]


def search_bandcamp(track_name, artist_name):
    query = f"{artist_name} {track_name}"
    try:
        results = search(query, SearchType.TRACKS)
        for r in results["auto"]["results"]:
            if r["type"] == SearchType.TRACKS:
                return r["item_url_path"]
    except Exception:
        return None
    return None


def parse_playlist_id(url):
    return url.split("/")[-1].split("?")[0]


@app.get("/api/search")
async def search_playlist(request: Request, playlist_url: str):
    token_info = request.session.get("token_info")
    if not token_info:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    oauth = create_spotify_oauth()
    if oauth.is_token_expired(token_info):
        token_info = oauth.refresh_access_token(token_info["refresh_token"])
        request.session["token_info"] = token_info

    sp = get_spotify_client(token_info)
    playlist_id = parse_playlist_id(playlist_url)

    async def event_generator():
        tracks = get_spotify_tracks(sp, playlist_id)
        yield {"event": "total", "data": json.dumps({"total": len(tracks)})}

        for i, (track, artist) in enumerate(tracks):
            link = search_bandcamp(track, artist)
            yield {
                "event": "track",
                "data": json.dumps({
                    "index": i + 1,
                    "artist": artist,
                    "track": track,
                    "link": link,
                }),
            }
            await asyncio.sleep(0.3)

        yield {"event": "done", "data": json.dumps({"message": "Search complete"})}

    return EventSourceResponse(event_generator())


# Serve static files in production (built Vite output)
static_dir = os.path.join(os.path.dirname(__file__), "..", "ui", "dist")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
