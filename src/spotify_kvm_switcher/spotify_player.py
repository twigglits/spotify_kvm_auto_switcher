"""Spotify device discovery and playback transfer."""

import logging

import spotipy

log = logging.getLogger(__name__)


class SpotifyPlayer:
    """Manages Spotify playback transfers for a specific device."""

    def __init__(self, sp: spotipy.Spotify, device_name: str):
        self._sp = sp
        self._device_name = device_name

    def transfer_playback(self):
        """Transfer playback to this machine's Spotify device.

        - Skips if this device is already active.
        - Uses force_play=False so paused playback stays paused.
        """
        devices = self._sp.devices()
        if not devices or not devices.get("devices"):
            log.warning("No Spotify devices found. Is Spotify running on this machine?")
            return

        target = None
        for dev in devices["devices"]:
            log.debug("Found device: %s (id=%s, active=%s)", dev["name"], dev["id"], dev["is_active"])
            if dev["name"] == self._device_name:
                target = dev
                break

        if target is None:
            log.warning(
                "Device '%s' not found. Available: %s",
                self._device_name,
                ", ".join(d["name"] for d in devices["devices"]),
            )
            return

        if target["is_active"]:
            log.info("Device '%s' is already active, skipping transfer", self._device_name)
            return

        log.info("Transferring playback to '%s'", self._device_name)
        self._sp.transfer_playback(device_id=target["id"], force_play=False)
        log.info("Playback transferred successfully")
