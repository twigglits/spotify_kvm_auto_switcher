"""Spotify device discovery and playback transfer."""

from __future__ import annotations

import logging
import time

import spotipy

log = logging.getLogger(__name__)

# Spotify accepts (HTTP 204, no error) volume commands aimed at a device that has
# not finished becoming active, then silently drops them. Measured on the Linux
# client: the write only takes ~2.5s after transfer_playback returns. So the
# post-transfer write is retried until the level actually reads back.
VOLUME_RETRY_ATTEMPTS = 6
VOLUME_RETRY_DELAY = 1.0


class SpotifyPlayer:
    """Manages Spotify playback transfers for a specific device."""

    def __init__(self, sp: spotipy.Spotify, device_name: str, sync_volume: bool = True):
        self._sp = sp
        self._device_name = device_name
        self._sync_volume = sync_volume

    def transfer_playback(self):
        """Transfer playback to this machine's Spotify device.

        - Skips if this device is already active.
        - Uses force_play=True so playback starts on the target device.
        - Carries the outgoing device's volume across, unless sync_volume is off.
        """
        devices = self._sp.devices()
        if not devices or not devices.get("devices"):
            log.warning("No Spotify devices found. Is Spotify running on this machine?")
            return

        target = None
        active = None
        for dev in devices["devices"]:
            log.debug("Found device: %s (id=%s, active=%s)", dev["name"], dev["id"], dev["is_active"])
            if dev["name"] == self._device_name and target is None:
                target = dev
            if dev.get("is_active") and active is None:
                active = dev

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

        volume = self._resolve_carry_volume(active, target)
        if volume is not None:
            # Pre-arm before transferring: force_play=True starts audio straight
            # away, and without this the target would briefly blare at its own
            # level before the post-transfer write corrects it.
            log.info("Carrying volume %d%% from '%s'", volume, active["name"])
            self._apply_volume(target["id"], volume, attempts=1, verify=False)

        log.info("Transferring playback to '%s'", self._device_name)
        self._sp.transfer_playback(device_id=target["id"], force_play=True)
        log.info("Playback transferred successfully")

        if volume is not None:
            if self._apply_volume(target["id"], volume, attempts=VOLUME_RETRY_ATTEMPTS):
                log.info("Volume set to %d%%", volume)
            else:
                log.warning(
                    "Could not set volume to %d%% on '%s'; it keeps its own level",
                    volume,
                    self._device_name,
                )

    def _resolve_carry_volume(self, active: dict | None, target: dict) -> int | None:
        """Decide what volume to carry onto the target, or None to leave it be."""
        if not self._sync_volume:
            log.debug("Volume sync disabled, leaving '%s' alone", self._device_name)
            return None

        if active is None:
            log.info("No active Spotify device; leaving '%s' at its own volume", self._device_name)
            return None

        volume = active.get("volume_percent")
        if volume is None:
            log.info("Device '%s' reports no volume level, nothing to carry", active["name"])
            return None

        if not target.get("supports_volume", True):
            log.info("Device '%s' does not support volume control", self._device_name)
            return None

        volume = max(0, min(100, int(volume)))
        if target.get("volume_percent") == volume:
            log.debug("Device '%s' is already at %d%%", self._device_name, volume)
            return None

        return volume

    def _apply_volume(self, device_id: str, volume: int, attempts: int, verify: bool = True) -> bool:
        """Set volume on a device, retrying until it sticks. True if it landed.

        A successful call proves nothing: Spotify returns 204 for writes aimed
        at a device still going active and drops them on the floor. So success
        means the level reads back, not that the request didn't raise. The
        pre-arm call passes verify=False — it is a best-effort shot before the
        transfer and has nothing to read back against yet.

        Catches broad Exception on purpose. Transferring playback is this
        daemon's primary job and must never be blocked by a best-effort volume
        write: connection failures surface as requests exceptions rather than
        SpotifyException, and the pre-arm call runs *before* the transfer. Real
        faults still surface — an expired token swallowed here raises again from
        transfer_playback on the next line — and every failure is logged.
        """
        for attempt in range(1, attempts + 1):
            try:
                self._sp.volume(volume, device_id=device_id)
                if not verify:
                    return True
            except Exception as exc:
                log.debug("Volume attempt %d/%d failed: %s", attempt, attempts, exc)
            else:
                if self._reads_back(device_id, volume):
                    return True
                log.debug("Volume attempt %d/%d was accepted but did not stick", attempt, attempts)
            if attempt < attempts:
                time.sleep(VOLUME_RETRY_DELAY)
        return False

    def _reads_back(self, device_id: str, volume: int) -> bool:
        """True if the device actually reports the volume we just wrote."""
        try:
            devices = self._sp.devices() or {}
        except Exception as exc:
            log.debug("Could not read volume back: %s", exc)
            return False
        for dev in devices.get("devices", []):
            if dev["id"] == device_id:
                return dev.get("volume_percent") == volume
        return False
