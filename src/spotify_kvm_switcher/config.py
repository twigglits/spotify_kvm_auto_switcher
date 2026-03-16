"""TOML config loading and validation."""

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def load_config(path: Path) -> dict:
    """Load and validate configuration from a TOML file.

    Required keys:
        spotify.client_id
        spotify.client_secret
        spotify.device_name
        usb.watched_devices (non-empty list with ID_VENDOR_ID and ID_MODEL_ID)
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Copy config.example.toml to config.toml and fill in your values."
        )

    with open(path, "rb") as f:
        config = tomllib.load(f)

    # Validate spotify section
    spotify = config.get("spotify", {})
    for key in ("client_id", "client_secret", "device_name"):
        val = spotify.get(key)
        if not val or val.startswith("YOUR_"):
            raise ValueError(f"spotify.{key} must be set in {path}")

    # Validate usb section
    usb = config.get("usb", {})
    watched = usb.get("watched_devices", [])
    if not watched:
        raise ValueError(
            f"usb.watched_devices must contain at least one device in {path}\n"
            "Run `python scripts/identify_usb.py` to find your device VID:PID."
        )
    for i, dev in enumerate(watched):
        for key in ("ID_VENDOR_ID", "ID_MODEL_ID"):
            if key not in dev:
                raise ValueError(
                    f"usb.watched_devices[{i}] missing {key} in {path}"
                )

    # Defaults
    config.setdefault("debounce_seconds", 2.0)

    return config
