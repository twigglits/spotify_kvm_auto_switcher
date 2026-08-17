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
    """Replays a live devices() response and records every call made.

    Volume writes mutate the device they target, so the player can read the
    level back the way it does against the real API. Two failure modes are
    modelled: volume_errors raises, and volume_drops mimics Spotify's real
    behaviour on a device that has not finished going active — the write is
    accepted with a 204 and then silently ignored.
    """

    def __init__(self, devices, volume_errors=0, volume_drops=0):
        self._devices = devices
        self._volume_errors = volume_errors
        self._volume_drops = volume_drops
        self.calls = []
        self.volume_calls = []
        self.transfer_calls = []

    def devices(self):
        return {"devices": self._devices}

    def volume_of(self, name):
        return next(d["volume_percent"] for d in self._devices if d["name"] == name)

    def volume(self, volume_percent, device_id=None):
        self.calls.append(("volume", volume_percent, device_id))
        self.volume_calls.append((volume_percent, device_id))
        if self._volume_errors:
            self._volume_errors -= 1
            raise RuntimeError("Device not found")
        if self._volume_drops:
            self._volume_drops -= 1
            return
        for dev in self._devices:
            if dev["id"] == device_id:
                dev["volume_percent"] = volume_percent

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


# --- volume carry-over ---

def test_volume_carries_from_active_device():
    sp = FakeSpotify([device("other", active=True, volume=35), device("mine", volume=90)])
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.volume_calls == [(35, "id-mine"), (35, "id-mine")]
    assert sp.transfer_calls == [("id-mine", True)]


def test_volume_is_pre_armed_before_the_transfer():
    sp = FakeSpotify([device("other", active=True, volume=35), device("mine", volume=90)])
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert [call[0] for call in sp.calls] == ["volume", "transfer", "volume"]


def test_no_active_device_leaves_volume_alone():
    sp = FakeSpotify([device("other", volume=35), device("mine", volume=90)])
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.volume_calls == []
    assert sp.transfer_calls == [("id-mine", True)]


def test_matching_volume_skips_volume_calls():
    sp = FakeSpotify([device("other", active=True, volume=40), device("mine", volume=40)])
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.volume_calls == []
    assert sp.transfer_calls == [("id-mine", True)]


def test_target_without_volume_support_is_skipped():
    sp = FakeSpotify([
        device("other", active=True, volume=35),
        device("mine", volume=90, supports_volume=False),
    ])
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.volume_calls == []
    assert sp.transfer_calls == [("id-mine", True)]


def test_missing_supports_volume_key_is_treated_as_supported():
    target = device("mine", volume=90)
    del target["supports_volume"]
    sp = FakeSpotify([device("other", active=True, volume=35), target])
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.volume_calls == [(35, "id-mine"), (35, "id-mine")]


def test_null_source_volume_is_skipped():
    sp = FakeSpotify([device("other", active=True, volume=None), device("mine", volume=90)])
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.volume_calls == []
    assert sp.transfer_calls == [("id-mine", True)]


def test_sync_volume_disabled_skips_volume_calls():
    sp = FakeSpotify([device("other", active=True, volume=35), device("mine", volume=90)])
    SpotifyPlayer(sp, "mine", sync_volume=False).transfer_playback()
    assert sp.volume_calls == []
    assert sp.transfer_calls == [("id-mine", True)]


def test_transfer_still_happens_when_every_volume_call_fails():
    sp = FakeSpotify(
        [device("other", active=True, volume=35), device("mine", volume=90)],
        volume_errors=99,
    )
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.transfer_calls == [("id-mine", True)]
    assert len(sp.volume_calls) == 1 + spotify_player.VOLUME_RETRY_ATTEMPTS


def test_post_transfer_volume_retries_until_it_succeeds():
    sp = FakeSpotify(
        [device("other", active=True, volume=35), device("mine", volume=90)],
        volume_errors=2,  # pre-arm fails, then the first post-transfer attempt fails
    )
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.transfer_calls == [("id-mine", True)]
    assert len(sp.volume_calls) == 3
    assert sp.volume_of("mine") == 35


# --- silently dropped writes: the bug that made carry-over look like it worked ---

def test_silently_dropped_volume_write_is_retried_until_it_reads_back():
    sp = FakeSpotify(
        [device("other", active=True, volume=35), device("mine", volume=90)],
        volume_drops=2,  # accepted with a 204, then ignored — no exception raised
    )
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert len(sp.volume_calls) == 3  # pre-arm + 1 dropped + 1 that lands
    assert sp.volume_of("mine") == 35


def test_gives_up_when_the_volume_never_sticks():
    sp = FakeSpotify(
        [device("other", active=True, volume=35), device("mine", volume=90)],
        volume_drops=99,
    )
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.transfer_calls == [("id-mine", True)]
    assert len(sp.volume_calls) == 1 + spotify_player.VOLUME_RETRY_ATTEMPTS
    assert sp.volume_of("mine") == 90  # left at its own level, transfer still happened
