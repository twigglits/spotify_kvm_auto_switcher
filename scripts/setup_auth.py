#!/usr/bin/env python3
"""One-time Spotify OAuth setup.

Completes the browser-based OAuth flow and prints available Spotify devices.
Run this once per machine before starting the daemon.
"""

import sys
from pathlib import Path

# Allow running from scripts/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from spotify_kvm_switcher.config import load_config
from spotify_kvm_switcher.spotify_auth import get_spotify_client


def main():
    config_path = Path("config.toml")
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])

    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    spotify_cfg = config["spotify"]
    print("Authenticating with Spotify...")
    print("If a browser doesn't open, copy the URL from the terminal and paste it in your browser.")
    print()

    sp = get_spotify_client(spotify_cfg["client_id"], spotify_cfg["client_secret"])

    # Verify auth works
    user = sp.current_user()
    print(f"Authenticated as: {user['display_name']} ({user['id']})")
    print()

    # List devices
    devices = sp.devices()
    if not devices or not devices.get("devices"):
        print("No Spotify devices found. Make sure Spotify is open on at least one machine.")
        return

    print("Available Spotify devices:")
    print()
    for dev in devices["devices"]:
        active = " (ACTIVE)" if dev["is_active"] else ""
        print(f"  - {dev['name']} [{dev['type']}]{active}")

    print()
    print("Set spotify.device_name in config.toml to the name of THIS machine's device.")


if __name__ == "__main__":
    main()
