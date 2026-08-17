"""Tests for SpotifyPlayer device selection, transfer, and volume carry-over."""

import pytest

from spotify_kvm_switcher import spotify_player
from spotify_kvm_switcher.spotify_player import SpotifyPlayer


def device(name, *, active=False, volume=50, supports_volume=True):
    """Build a Spotify Connect device dict shaped like the Web API's."""
    return {
        "id": f"id-{name}",
        "name": name,
        "is_active": active,
        "volume_percent": volume,
        "supports_volume": supports_volume,
    }


class FakeSpotify:
    """Replays a canned devices() response and records every call made."""

    def __init__(self, devices, volume_errors=0):
        self._devices = devices
        self._volume_errors = volume_errors
        self.calls = []
        self.volume_calls = []
        self.transfer_calls = []

    def devices(self):
        return {"devices": self._devices}

    def volume(self, volume_percent, device_id=None):
        self.calls.append(("volume", volume_percent, device_id))
        self.volume_calls.append((volume_percent, device_id))
        if self._volume_errors:
            self._volume_errors -= 1
            raise RuntimeError("Device not found")

    def transfer_playback(self, device_id, force_play=True):
        self.calls.append(("transfer", device_id, force_play))
        self.transfer_calls.append((device_id, force_play))


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Keep the retry loop instant so tests stay fast."""
    monkeypatch.setattr(spotify_player, "VOLUME_RETRY_DELAY", 0, raising=False)


# --- existing behaviour, pinned before it is changed ---

def test_transfers_to_named_device():
    sp = FakeSpotify([device("other", active=True, volume=40), device("mine", volume=40)])
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.transfer_calls == [("id-mine", True)]


def test_no_devices_does_nothing():
    sp = FakeSpotify([])
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.transfer_calls == []
    assert sp.volume_calls == []


def test_unknown_device_name_does_nothing():
    sp = FakeSpotify([device("other", active=True)])
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.transfer_calls == []
    assert sp.volume_calls == []


def test_already_active_target_does_nothing():
    sp = FakeSpotify([device("mine", active=True, volume=70)])
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.transfer_calls == []
    assert sp.volume_calls == []
