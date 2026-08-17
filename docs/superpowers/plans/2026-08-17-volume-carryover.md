# Spotify Volume Carry-Over Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a KVM switch moves Spotify playback to a new machine, that machine adopts the Spotify volume of the machine playback just left.

**Architecture:** `SpotifyPlayer.transfer_playback()` already fetches `sp.devices()`, and that one response carries `is_active`, `volume_percent`, and `supports_volume` for every device — so the outgoing machine's volume costs no extra API call to discover. The volume is written to the target twice: once *before* `transfer_playback` (to close the loud-burst window that `force_play=True` opens) and once *after*, with retries (the authoritative write, because Spotify intermittently rejects volume commands aimed at a device that has not finished becoming active).

**Tech Stack:** Python 3.9+, spotipy 2.26, pytest (new dev dependency), TOML config.

**Spec:** `docs/superpowers/specs/2026-08-17-spotify-volume-carryover-design.md`

## Global Constraints

- `requires-python = ">=3.9"`. PEP 604 unions (`int | None`) in *function signatures* are evaluated at def time and raise `TypeError` on 3.9, so `spotify_player.py` must gain `from __future__ import annotations`. (The existing `threading.Timer | None` in `usb_monitor.py:50` is a local variable annotation, which is never evaluated — it is not a precedent for signatures.)
- Playback transfer is the daemon's primary function; volume carry-over is a convenience. **No volume failure may prevent, abort, or block a transfer.** Every task's tests must keep asserting that `transfer_playback` is still called.
- The Spotify Web API reads and writes only Spotify's own per-device volume slider — never the OS mixer. Documentation must say so plainly rather than implying system volume follows.
- Existing `config.toml` files on all three machines must stay valid unedited: `sync_volume` defaults to `true`.
- No new runtime dependencies. pytest is dev-only, under `[project.optional-dependencies]`.
- The dev environment is pyenv 3.11.9 (`~/.pyenv/versions/3.11.9`), where the package is already installed editable. It is not the PEP-668-managed system Python, so `pip install` needs no `--break-system-packages` or venv gymnastics.
- Retry tuning lives in module constants `VOLUME_RETRY_ATTEMPTS = 3` and `VOLUME_RETRY_DELAY = 0.4`, read at call time so tests can monkeypatch the delay to zero.

## File Structure

| File | Responsibility |
|---|---|
| `src/spotify_kvm_switcher/spotify_player.py` | *Modified.* All volume carry-over logic. Two new private helpers keep `transfer_playback()` readable: one decides *what* volume to carry, one performs the write with retries. |
| `src/spotify_kvm_switcher/config.py` | *Modified.* Defaults and type-validates `spotify.sync_volume`. |
| `src/spotify_kvm_switcher/daemon.py` | *Modified.* Passes `sync_volume` through; logs it at startup so it is visible in `journalctl`. |
| `tests/test_spotify_player.py` | *New.* `FakeSpotify` stub plus device-selection, transfer, and volume tests. |
| `tests/test_config.py` | *New.* `sync_volume` defaulting and validation. |
| `pyproject.toml` | *Modified.* pytest dev extra and `testpaths`. |
| `config.example.toml`, `README.md`, `CLAUDE.md` | *Modified.* Docs, including the OS-volume caveat and the `force_play` correction. |

---

### Task 1: Test harness and characterization tests

Pins the *current* behaviour of `transfer_playback()` before anything changes it. These tests must pass on first run — they describe code that already exists. If one fails, stop and investigate: the safety net is wrong, and every later task depends on it.

**Files:**
- Create: `tests/test_spotify_player.py`
- Modify: `pyproject.toml:16-19`

**Interfaces:**
- Consumes: `SpotifyPlayer(sp, device_name)` as it exists today.
- Produces: `device(...)` factory and `FakeSpotify` class, reused verbatim by Task 2. `FakeSpotify.calls` is an ordered list of tuples whose first element is `"volume"` or `"transfer"`; `FakeSpotify.volume_calls` is `[(volume_percent, device_id), ...]`; `FakeSpotify.transfer_calls` is `[(device_id, force_play), ...]`.

- [ ] **Step 1: Add the pytest dev extra**

In `pyproject.toml`, insert after the `[project.scripts]` block:

```toml
[project.optional-dependencies]
dev = ["pytest>=7.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Install pytest**

Run: `pip install -e ".[dev]"`
Expected: pytest installs; `spotify_kvm_switcher` remains importable from `src/`.

- [ ] **Step 3: Write the harness and characterization tests**

Create `tests/test_spotify_player.py`:

```python
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
```

`raising=False` on the monkeypatch is deliberate: `VOLUME_RETRY_DELAY` does not exist until Task 2, and this fixture must not break Task 1's run.

Note `test_transfers_to_named_device` gives both devices volume 40. That is not incidental — it means this test keeps asserting *only* transfer behaviour once Task 2 lands, because matching volumes skip the volume calls.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_spotify_player.py -v`
Expected: 4 passed. These describe existing code, so a failure means the safety net is wrong — stop and investigate rather than editing source.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_spotify_player.py
git commit -m "test: pin existing SpotifyPlayer transfer behaviour

Adds a pytest dev extra and a FakeSpotify stub, then characterizes the
current device-selection and transfer logic before volume carry-over
changes it."
```

---

### Task 2: Volume carry-over in SpotifyPlayer

**Files:**
- Modify: `src/spotify_kvm_switcher/spotify_player.py` (whole file)
- Test: `tests/test_spotify_player.py`

**Interfaces:**
- Consumes: `device(...)`, `FakeSpotify`, and the `no_retry_delay` fixture from Task 1.
- Produces:
  - `SpotifyPlayer.__init__(self, sp, device_name: str, sync_volume: bool = True)` — Task 3's daemon wiring passes `sync_volume` by keyword.
  - Module constants `VOLUME_RETRY_ATTEMPTS: int = 3`, `VOLUME_RETRY_DELAY: float = 0.4`.
  - Private `_resolve_carry_volume(active: dict | None, target: dict) -> int | None` and `_apply_volume(device_id: str, volume: int, attempts: int) -> bool`.

- [ ] **Step 1: Write the failing volume tests**

Append to `tests/test_spotify_player.py`:

```python
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
    assert len(sp.volume_calls) == 4  # 1 pre-arm + 3 post-transfer attempts


def test_post_transfer_volume_retries_until_it_succeeds():
    sp = FakeSpotify(
        [device("other", active=True, volume=35), device("mine", volume=90)],
        volume_errors=2,  # pre-arm fails, then the first post-transfer attempt fails
    )
    SpotifyPlayer(sp, "mine").transfer_playback()
    assert sp.transfer_calls == [("id-mine", True)]
    assert len(sp.volume_calls) == 3
```

- [ ] **Step 2: Run them and watch them fail**

Run: `pytest tests/test_spotify_player.py -v`
Expected: the 4 Task 1 tests pass; the new ones fail — most with `AssertionError: assert [] == [(35, 'id-mine'), ...]`, and `test_sync_volume_disabled_skips_volume_calls` with `TypeError: __init__() got an unexpected keyword argument 'sync_volume'`.

- [ ] **Step 3: Add imports and retry constants**

Replace lines 1-7 of `src/spotify_kvm_switcher/spotify_player.py`:

```python
"""Spotify device discovery and playback transfer."""

from __future__ import annotations

import logging
import time

import spotipy

log = logging.getLogger(__name__)

# Spotify intermittently rejects volume commands aimed at a device that has not
# finished becoming active, so the post-transfer write gets a few short retries.
VOLUME_RETRY_ATTEMPTS = 3
VOLUME_RETRY_DELAY = 0.4
```

`spotipy` stays imported for the type annotation on `__init__`.

- [ ] **Step 4: Add the `_apply_volume` helper**

Append this method to `SpotifyPlayer`:

```python
    def _apply_volume(self, device_id: str, volume: int, attempts: int) -> bool:
        """Set volume on a device, retrying briefly. True if it landed.

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
                return True
            except Exception as exc:
                log.debug("Volume attempt %d/%d failed: %s", attempt, attempts, exc)
                if attempt < attempts:
                    time.sleep(VOLUME_RETRY_DELAY)
        return False
```

- [ ] **Step 5: Add the `_resolve_carry_volume` helper**

Append this method to `SpotifyPlayer`:

```python
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
```

- [ ] **Step 6: Rewire the constructor and `transfer_playback`**

Replace the constructor and `transfer_playback` with:

```python
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
            self._apply_volume(target["id"], volume, attempts=1)

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
```

Three deliberate changes beyond adding volume: the loop no longer `break`s (it must keep scanning to find the active device), `and target is None` preserves the old first-match-wins semantics, and the docstring's `force_play=False` claim is corrected to match line `force_play=True` which the code has always passed.

- [ ] **Step 7: Run the full suite**

Run: `pytest tests/ -v`
Expected: 14 passed.

- [ ] **Step 8: Commit**

```bash
git add src/spotify_kvm_switcher/spotify_player.py tests/test_spotify_player.py
git commit -m "feat: carry Spotify volume across KVM switches

The outgoing device's volume_percent comes free with the devices()
snapshot transfer_playback already fetches. It is written to the target
before the transfer (force_play=True would otherwise blare at the
target's own level) and again after, with retries, since Spotify rejects
volume commands to a device that is not active yet.

Also corrects the docstring's force_play=False claim; the code has always
passed force_play=True."
```

---

### Task 3: `sync_volume` config key and daemon wiring

**Files:**
- Modify: `src/spotify_kvm_switcher/config.py:31-56`
- Modify: `src/spotify_kvm_switcher/daemon.py:18-20`, `daemon.py:42-45`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: `SpotifyPlayer(sp, device_name, sync_volume=...)` from Task 2.
- Produces: `load_config()` guarantees `config["spotify"]["sync_volume"]` is a `bool`.

- [ ] **Step 1: Write the failing config tests**

Create `tests/test_config.py`:

```python
"""Tests for config loading and validation."""

import pytest

from spotify_kvm_switcher.config import load_config


def config_body(extra_spotify=""):
    """A minimal valid config, optionally with extra keys in [spotify].

    [spotify] comes last so extra keys land in it rather than in the
    [[usb.watched_devices]] table.
    """
    return f"""
[usb]
[[usb.watched_devices]]
ID_VENDOR_ID = "046d"
ID_MODEL_ID = "c08d"

[spotify]
client_id = "cid"
client_secret = "csec"
device_name = "mine"
{extra_spotify}
"""


def write_config(tmp_path, body):
    path = tmp_path / "config.toml"
    path.write_text(body)
    return path


def test_sync_volume_defaults_to_true(tmp_path):
    config = load_config(write_config(tmp_path, config_body()))
    assert config["spotify"]["sync_volume"] is True


def test_sync_volume_can_be_disabled(tmp_path):
    config = load_config(write_config(tmp_path, config_body("sync_volume = false")))
    assert config["spotify"]["sync_volume"] is False


def test_non_boolean_sync_volume_is_rejected(tmp_path):
    path = write_config(tmp_path, config_body('sync_volume = "yes"'))
    with pytest.raises(ValueError, match="sync_volume"):
        load_config(path)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `pytest tests/test_config.py -v`
Expected: 3 failed — two with `KeyError: 'sync_volume'`, one with `Failed: DID NOT RAISE <class 'ValueError'>`.

- [ ] **Step 3: Default and validate the key**

In `src/spotify_kvm_switcher/config.py`, insert immediately after the `for key in ("client_id", "client_secret", "device_name"):` validation loop and before the `# Validate usb section` comment:

```python
    # Optional: carry the outgoing machine's Spotify volume across on transfer.
    sync_volume = spotify.get("sync_volume", True)
    if not isinstance(sync_volume, bool):
        raise ValueError(f"spotify.sync_volume must be true or false in {path}")
    config["spotify"]["sync_volume"] = sync_volume
```

Then extend the docstring's key list, changing the `usb.watched_devices` line to read:

```
        usb.watched_devices (non-empty list with ID_VENDOR_ID and ID_MODEL_ID)

    Optional keys:
        spotify.sync_volume (bool, default true)
```

`config["spotify"]` is guaranteed to exist here: the loop above raises if any required key is missing, which includes the case of the section being absent entirely.

- [ ] **Step 4: Run the config tests**

Run: `pytest tests/test_config.py -v`
Expected: 3 passed.

- [ ] **Step 5: Wire it into the daemon**

In `src/spotify_kvm_switcher/daemon.py`, replace the `player = ...` line with:

```python
    player = SpotifyPlayer(
        sp,
        spotify_cfg["device_name"],
        sync_volume=spotify_cfg["sync_volume"],
    )
```

and replace the startup log call with:

```python
    log.info(
        "Starting spotify-kvm-switcher (device='%s', sync_volume=%s)",
        spotify_cfg["device_name"],
        spotify_cfg["sync_volume"],
    )
```

- [ ] **Step 6: Verify the daemon wiring end to end**

Run: `pytest tests/ -v && spotify-kvm-switcher --config config.toml --verbose`
Expected: 17 passed. The daemon starts and logs `Starting spotify-kvm-switcher (device='jeansmatexpro', sync_volume=True)`. Stop it with Ctrl-C.

- [ ] **Step 7: Commit**

```bash
git add src/spotify_kvm_switcher/config.py src/spotify_kvm_switcher/daemon.py tests/test_config.py
git commit -m "feat: add spotify.sync_volume config key

Defaults to true, so existing config files on all three machines stay
valid unedited. Logged at startup to make the setting visible in
journalctl."
```

---

### Task 4: Documentation

**Files:**
- Modify: `config.example.toml:11-18`
- Modify: `README.md:82-104`
- Modify: `CLAUDE.md` (Architecture section)

**Interfaces:**
- Consumes: the `spotify.sync_volume` key from Task 3. Produces nothing consumed by other tasks.

- [ ] **Step 1: Document the key in `config.example.toml`**

Append to the `[spotify]` section, after the `device_name` line:

```toml
# Carry the volume of the machine you switched away from onto this one.
# NOTE: this reads and writes Spotify's OWN volume slider, not your OS mixer.
# If you change volume with system media keys rather than inside Spotify,
# Spotify's slider never moves and there is nothing to carry.
# Set to false to leave this machine's Spotify volume alone.
sync_volume = true
```

- [ ] **Step 2: Update the README**

In "How It Works", replace item 5 (`force_play=False` preserves the play/pause state...) with:

```markdown
5. `force_play=True` starts playback on the machine you switched to
6. The Spotify volume of the machine you switched *away from* is carried over, so playback continues at the level you had it
```

In the configuration reference block, add after the `device_name` line:

```toml
sync_volume = true              # Carry the previous machine's Spotify volume across
```

Then add this subsection immediately after the configuration reference block:

```markdown
## Volume Carry-Over

When playback transfers, the new machine adopts the Spotify volume of the machine
it transferred from, so switching seats does not change how loud your music is.

This works on **Spotify's own volume slider only**. The Spotify Web API cannot see
or change your operating system's mixer, so if you set volume with system media
keys instead of inside Spotify, Spotify's slider stays at 100% on every machine and
there is nothing to carry across. Set `sync_volume = false` to turn the behaviour
off on a given machine.
```

- [ ] **Step 3: Record it in `CLAUDE.md`**

Append to the Architecture bullet list:

```markdown
- On transfer, the outgoing (active) device's `volume_percent` is carried onto the incoming device: pre-armed before `transfer_playback` to avoid a loud burst from `force_play=True`, then re-applied afterwards with retries (Spotify rejects volume writes to a device that is not active yet). Controlled by `spotify.sync_volume`, default true. This is Spotify's own slider, not the OS mixer.
```

- [ ] **Step 4: Check the docs against the code**

Run: `grep -rn "force_play" README.md src/ && grep -rn "sync_volume" README.md config.example.toml CLAUDE.md src/`
Expected: no remaining `force_play=False` claim anywhere; `sync_volume` present in all of README, config.example.toml, CLAUDE.md, config.py, daemon.py, spotify_player.py.

- [ ] **Step 5: Commit**

```bash
git add config.example.toml README.md CLAUDE.md
git commit -m "docs: document volume carry-over and sync_volume

Also corrects the README's force_play=False claim, which never matched
the code."
```

---

## Manual verification

Automated tests cannot prove this works against real Spotify. After Task 4, verify on hardware:

1. On this machine (`jeansmatexpro`), set Spotify's volume slider to something distinctive — 25%.
2. `systemctl --user restart spotify-kvm-switcher` and confirm it comes up clean.
3. Switch the KVM away and back.
4. `journalctl --user -u spotify-kvm-switcher -f` should show `Carrying volume NN% from '<other machine>'` followed by `Volume set to NN%`.
5. Confirm Spotify's slider on this machine now reads the other machine's level, and that no loud burst occurred at the moment of transfer.

If step 5 shows the slider unmoved, check first whether volume on the *other* machine was set through Spotify or through the OS mixer — the latter is the documented limitation, not a bug.

## Rollout to the other two machines

Not doable from this session; only `jeansmatexpro` is reachable.

- **jeannaude-workstation:** `git pull`, `pip install -e .`, `systemctl --user restart spotify-kvm-switcher`
- **MAC-JEAN:** `git pull`, then `~/.local/share/spotify-kvm-switcher/.venv/bin/pip install .` — the install is non-editable, so a pull alone changes nothing at runtime — then `launchctl unload ~/Library/LaunchAgents/com.jeannaude.spotify-kvm-switcher.plist && launchctl load ~/Library/LaunchAgents/com.jeannaude.spotify-kvm-switcher.plist`

No re-authentication anywhere: the existing scopes (`user-read-playback-state user-modify-playback-state`) already cover volume reads and writes.
