# Spotify Volume Carry-Over Across KVM Switches

**Date:** 2026-08-17
**Status:** Approved

## Problem

Three machines (`jeannaude-workstation`, `MAC-JEAN`, `jeansmatexpro`) share a KVM switch and
run Spotify on the same account. The daemon already transfers playback to whichever machine
gains USB devices, but every Spotify Connect device keeps its own independent volume slider.
Playback therefore arrives on the new machine at whatever level that machine's Spotify was
last left at — frequently much louder or quieter than the machine just left.

Volume should follow the switch: the machine gaining playback adopts the volume of the
machine losing it.

## Scope

In scope:

- Read the outgoing (currently active) device's Spotify volume at transfer time.
- Apply that volume to the incoming device as part of the same transfer.
- A per-machine config toggle to disable the behaviour.

Out of scope:

- **System/OS output volume.** The Spotify Web API reads and writes only the Spotify
  application's own volume slider on each Connect device. It has no visibility into
  PulseAudio/PipeWire or CoreAudio levels. If volume is changed through the OS mixer, or
  through media keys bound to the OS mixer, Spotify's slider does not move and there is
  nothing to carry. Volume must be set inside Spotify for this feature to do anything.
- Per-machine offset or clamping to compensate for different speaker sensitivities.
  Considered and deferred; revisit only if verbatim carry-over proves impractical in use.
- Persisting volume across daemon restarts or idle periods. Spotify's own device list is the
  cross-machine source of truth; a local state file cannot observe what the other two
  machines did.

## Approach

`SpotifyPlayer.transfer_playback()` already calls `sp.devices()`, and that single response
carries `is_active`, `volume_percent`, and `supports_volume` for every device. The source
volume is therefore already in hand — discovering it costs no additional API call.

Two alternatives were rejected:

- **Set volume only after the transfer.** One fewer API call, but `force_play=True` starts
  audio immediately, so switching from a quiet machine to one whose slider sits at 100%
  produces a loud burst before the correction lands.
- **Background polling with a persisted volume cache.** The cache would be per-machine and so
  could never learn what the other machines did. Complexity with no cross-machine payoff.

## Sequence

Within `SpotifyPlayer.transfer_playback()`, after the existing device lookup and the existing
"already active" early return:

1. **Resolve the source volume `V`** from the device in the snapshot with `is_active: true`.
2. **Pre-arm** — `sp.volume(V, device_id=target)` *before* transferring. Single attempt,
   best-effort, all exceptions swallowed to a debug log. This closes the loud-burst window.
3. **Transfer** — `sp.transfer_playback(target, force_play=True)`, unchanged.
4. **Re-apply** — `sp.volume(V, device_id=target)`, up to 3 attempts spaced 0.4 s apart. This
   is the authoritative write; Spotify intermittently rejects volume commands aimed at a
   device that has not finished becoming active. Exhausting all attempts logs a warning.

Sleeping between retries is safe: the callback runs on the debounce `threading.Timer` thread,
not the main thread or the USB monitor thread.

## Skip conditions

Volume work is skipped, with a log line and no effect on the transfer, when any of these hold:

| Condition | Rationale |
|---|---|
| `sync_volume` is `false` | Explicitly disabled for this machine. |
| No device in the snapshot has `is_active: true` | Nothing is playing anywhere, so there is no "previous machine" volume to carry. Leave the target's slider untouched. |
| The active device's `volume_percent` is `null` | Device does not report a level. |
| Target's `supports_volume` is `false` | Device cannot accept volume commands. A missing `supports_volume` key is treated as `true`. |
| Target's `volume_percent` already equals `V` | Already correct; saves both API calls and avoids a pointless write. |

The pre-existing early returns are unchanged and take precedence: an empty device list, a
target that is not found by name, and a target that is already active all return before any
volume work is considered.

## Error handling

Playback transfer is the daemon's primary function; volume carry-over is a convenience. No
volume failure may prevent, abort, or precede-and-block a transfer.

The shared helper catches broad `Exception`, not just `spotipy.SpotifyException`. This is
deliberate: connection-level failures surface as `requests` exceptions rather than spotipy
ones, and an unhandled exception in the pre-arm step (which runs *before* the transfer) would
stop the transfer from happening at all. Genuine faults are not hidden by this — an expired
token swallowed during pre-arm will still raise from `transfer_playback()` on the very next
line, and every swallowed exception is logged.

Worst case is a logged warning and playback continuing at the target's own volume.

## Components

| File | Change |
|---|---|
| `src/spotify_kvm_switcher/spotify_player.py` | `SpotifyPlayer.__init__` gains `sync_volume: bool = True`. New private helper `_apply_volume(device_id, volume, attempts, delay) -> bool`. New private helper to resolve the source volume from the snapshot. `transfer_playback()` gains the pre-arm/re-apply steps. Module constants `VOLUME_RETRY_ATTEMPTS = 3` and `VOLUME_RETRY_DELAY = 0.4` so tests can neutralise the delay. |
| `src/spotify_kvm_switcher/config.py` | Default `spotify.sync_volume` to `true`; raise `ValueError` if it is present but not a boolean, matching the existing validation style. |
| `src/spotify_kvm_switcher/daemon.py` | Pass `sync_volume` through to `SpotifyPlayer`. |
| `config.example.toml` | Document `sync_volume`, including the OS-volume caveat. |
| `README.md` | Document the behaviour in "How It Works" and add `sync_volume` to the configuration reference. |
| `CLAUDE.md` | One line in Architecture recording the volume carry-over behaviour. |
| `pyproject.toml` | Add `[project.optional-dependencies] dev = ["pytest>=7.0"]` and a `testpaths` setting. |
| `tests/test_spotify_player.py` | New. See below. |

Existing config files on all three machines remain valid without edits, since `sync_volume`
defaults to `true`.

## Testing

The repository has no tests today and pytest is not installed. `SpotifyPlayer` takes an
injected client, so a `FakeSpotify` stub recording `volume()` and `transfer_playback()` calls
covers the logic without network access. This is worth doing: the alternative is validating
roughly ten branches by physically walking between three machines.

Cases:

1. Volume carries from the active device to the target — `volume()` called with the source
   level both before and after the transfer, and the pre-arm call precedes the transfer.
2. No active device — no volume calls, transfer still happens.
3. Source and target volumes already match — no volume calls, transfer still happens.
4. Target reports `supports_volume: false` — no volume calls, transfer still happens.
5. Source `volume_percent` is `null` — no volume calls, transfer still happens.
6. `sync_volume=False` — no volume calls, transfer still happens.
7. Every `volume()` call raises — `transfer_playback()` still called exactly once.
8. Post-transfer retry succeeds on a later attempt — retry loop exercised with the delay
   monkeypatched to zero.
9. Target already active — neither transfer nor volume calls.
10. Target not found by name — neither transfer nor volume calls.

## Incidental fix

`spotify_player.py:21` and `README.md` both state `force_play=False`, while the code passes
`force_play=True`. The docstring being corrected is the one this change rewrites, so the
claim is fixed rather than left in place. No behaviour change.

## Rollout

Only `jeansmatexpro` is reachable from the implementing session. After merge, the other two
machines each need a manual update:

- **jeannaude-workstation** — `git pull`, reinstall, `systemctl --user restart spotify-kvm-switcher`.
- **MAC-JEAN** — `git pull`, then `pip install .` into
  `~/.local/share/spotify-kvm-switcher/.venv` (the install is non-editable, so a pull alone
  changes nothing at runtime), then `launchctl unload`/`load` the agent.

No re-authentication is needed anywhere: the existing OAuth scopes
(`user-read-playback-state user-modify-playback-state`) already cover volume reads and writes.
