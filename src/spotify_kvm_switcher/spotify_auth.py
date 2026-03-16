"""Spotify OAuth2 authentication with token persistence."""

import logging
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth

log = logging.getLogger(__name__)

SCOPES = "user-read-playback-state user-modify-playback-state"
REDIRECT_URI = "http://127.0.0.1:8888/callback"


def get_cache_path() -> Path:
    cache_dir = Path.home() / ".config" / "spotify-kvm-switcher"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / ".spotify_cache"


def get_spotify_client(client_id: str, client_secret: str) -> spotipy.Spotify:
    """Create an authenticated Spotify client with token caching."""
    cache_path = get_cache_path()
    log.debug("Token cache: %s", cache_path)

    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
        cache_path=str(cache_path),
        open_browser=False,
    )

    return spotipy.Spotify(auth_manager=auth_manager)
