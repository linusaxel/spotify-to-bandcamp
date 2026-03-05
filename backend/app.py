import os
import re
import json
import asyncio
import secrets
import logging
import spotipy
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from spotipy.oauth2 import SpotifyOAuth
from soundcloud import SoundCloud
from bandcamp_search.search import search, SearchType
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sse_starlette.sse import EventSourceResponse

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI()

# In production (ui/dist exists), redirect to "/". In dev, redirect to Vite dev server.
_static_dir = os.path.join(os.path.dirname(__file__), "..", "ui", "dist")
FRONTEND_URL = os.getenv("FRONTEND_URL", "/" if os.path.isdir(_static_dir) else "http://127.0.0.1:5173")

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
        logger.exception("Bandcamp search failed for: %s", query)
        return None
    return None


def _slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def _normalize(text):
    """Lowercase, strip non-alphanumeric, collapse whitespace."""
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def _compact(text):
    """Lowercase, strip everything non-alphanumeric (no spaces)."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _names_match(query_name, result_name):
    """Check if names match: substring match or compact match (ignoring spaces/punctuation)."""
    a, b = _normalize(query_name), _normalize(result_name)
    if a in b or b in a:
        return True
    # Also try without spaces (e.g. "Aphex Twin" vs "aphextwin")
    ac, bc = _compact(query_name), _compact(result_name)
    return ac in bc or bc in ac


def search_beatport(track_name, artist_name):
    query = f"{artist_name} {track_name}"
    try:
        resp = requests.get(
            f"https://www.beatport.com/search?q={quote_plus(query)}",
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            timeout=10,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script:
            return None
        data = json.loads(script.string)
        queries = data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
        for q in queries:
            state = q.get("state", {})
            results = state.get("data", {})
            tracks = results.get("tracks") if isinstance(results, dict) else None
            if tracks:
                items = tracks.get("data", []) if isinstance(tracks, dict) else tracks
                for t in items:
                    track_id = t.get("track_id") or t.get("id")
                    name = t.get("track_name") or t.get("name", "")
                    bp_artists = [a.get("artist_name", "") for a in t.get("artists", [])]
                    if not track_id or not name:
                        continue
                    artist_ok = any(_names_match(artist_name, a) for a in bp_artists)
                    track_ok = _names_match(track_name, name)
                    if artist_ok and track_ok:
                        return f"https://www.beatport.com/track/{_slugify(name)}/{track_id}"
    except Exception:
        logger.exception("Beatport search failed for: %s", query)
        return None
    return None


_sc_client = SoundCloud()


def search_soundcloud(track_name, artist_name):
    query = f"{artist_name} {track_name}"
    try:
        results = _sc_client.search_tracks(query)
        fallback = None
        for t in results:
            title = t.title or ""
            user = t.user.username or "" if t.user else ""
            if not t.permalink_url:
                continue
            track_ok = _names_match(track_name, title)
            if not track_ok:
                continue
            artist_in_user = _names_match(artist_name, user)
            artist_in_title = _names_match(artist_name, title)
            if not artist_in_user and not artist_in_title:
                continue
            # Skip remixes/edits/reworks unless the original is that
            title_lower = title.lower()
            is_remix = any(tag in title_lower for tag in ("remix", "edit", "rework", "bootleg", "retake", "cut"))
            if is_remix and not any(tag in track_name.lower() for tag in ("remix", "edit", "rework")):
                if not fallback:
                    fallback = t.permalink_url
                continue
            # Prefer official uploads (username matches artist)
            if artist_in_user:
                return t.permalink_url
            if not fallback:
                fallback = t.permalink_url
        return fallback
    except Exception:
        logger.exception("SoundCloud search failed for: %s", query)
        return None


SPOTIFY_PLAYLIST_RE = re.compile(
    r"(?:https?://)?(?:open\.)?spotify\.com/playlist/([a-zA-Z0-9]+)"
)


def parse_playlist_id(url):
    match = SPOTIFY_PLAYLIST_RE.search(url)
    if not match:
        return None
    return match.group(1)


@app.get("/api/search")
async def search_playlist(request: Request, playlist_url: str):
    token_info = request.session.get("token_info")
    if not token_info:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    playlist_id = parse_playlist_id(playlist_url)
    if not playlist_id:
        return JSONResponse({"error": "Invalid Spotify playlist URL"}, status_code=400)

    oauth = create_spotify_oauth()
    if oauth.is_token_expired(token_info):
        token_info = oauth.refresh_access_token(token_info["refresh_token"])
        request.session["token_info"] = token_info

    sp = get_spotify_client(token_info)

    async def event_generator():
        try:
            tracks = get_spotify_tracks(sp, playlist_id)
            yield {"event": "total", "data": json.dumps({"total": len(tracks)})}

            for i, (track, artist) in enumerate(tracks):
                bandcamp_link = search_bandcamp(track, artist)
                beatport_link = search_beatport(track, artist)
                soundcloud_link = search_soundcloud(track, artist)
                yield {
                    "event": "track",
                    "data": json.dumps({
                        "index": i + 1,
                        "artist": artist,
                        "track": track,
                        "bandcamp_link": bandcamp_link,
                        "beatport_link": beatport_link,
                        "soundcloud_link": soundcloud_link,
                    }),
                }
                await asyncio.sleep(0.3)

            yield {"event": "done", "data": json.dumps({"message": "Search complete"})}
        except spotipy.SpotifyException as e:
            logger.exception("Spotify API error")
            yield {"event": "search_error", "data": json.dumps({"message": f"Spotify error: {e.msg}"})}
        except Exception as e:
            logger.exception("Unexpected error during search")
            yield {"event": "search_error", "data": json.dumps({"message": str(e)})}

    return EventSourceResponse(event_generator())


@app.get("/api/health")
async def health():
    return JSONResponse({"status": "ok"})


# Serve static files in production (built Vite output)
static_dir = os.path.join(os.path.dirname(__file__), "..", "ui", "dist")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
