# Project Context

## What This Is

Spotify KVM Auto-Switcher: a Python daemon that monitors USB device connections (via KVM switch) and auto-transfers Spotify playback to the newly active machine.

3 machines share a KVM switch (Linux Workstation, macOS MAC-JEAN, Linux Huawei MateBook X Pro). All run Spotify on the same account (Twigglits).

## Architecture

- `src/spotify_kvm_switcher/` — installable Python package with `spotify-kvm-switcher` CLI entry point
- USB events detected via `usbmonitor` library (PyPI package name: `usb-monitor`, NOT `usbmonitor`)
- Debounce (2s default) collapses rapid KVM USB events into one Spotify transfer call
- `force_play=True` forces playback to start on the target device on transfer
- Device matching by Spotify Connect name (configured per-machine in config.toml)
- Only the machine gaining USB devices fires transfer — no race condition
- USB VID/PID format differs by platform: Linux `usbmonitor` reports hex strings (`"046d"`), macOS reports decimal strings (`"1133"`). `usb_monitor.py` normalizes both to int for comparison.
- Spotify device names may contain Unicode (e.g. curly apostrophe U+2019). Config uses TOML `\u` escapes to match exactly.
- On transfer, the outgoing (active) device's `volume_percent` is carried onto the incoming device: pre-armed before `transfer_playback`, then re-applied afterwards until it sticks. Controlled by `spotify.sync_volume`, default true. This is Spotify's own slider, not the OS mixer.
- **Spotify silently drops volume writes aimed at a device that has not finished going active** — it returns HTTP 204 with no error and ignores them. Measured on the Linux client: the pre-arm write and a write at t+1.6s after `transfer_playback` were both discarded; t+2.7s landed. `_apply_volume` therefore confirms success by reading the level back via `devices()` (6 attempts, 1s apart), never by trusting the response. Do not "simplify" this back into a fire-and-forget write — it will look like it works and silently do nothing.

## Deployment Status

### Linux Workstation (jeannaude-workstation) — COMPLETE
- Spotify Connect device name: `jeannaude-workstation`
- Config: `~/.config/spotify-kvm-switcher/config.toml`
- Auth token cached at: `~/.config/spotify-kvm-switcher/.spotify_cache`
- Watched USB devices: Logitech G502 mouse (046d:c08d), Corsair K70 keyboard (1b1c:1b33)
- Running as systemd user service: `spotify-kvm-switcher.service` (enabled on boot)
- Logs: `journalctl --user -u spotify-kvm-switcher -f`

### macOS (MAC-JEAN) — COMPLETE
- Apple Silicon (arm64), macOS 26.5.1, user `jean` (home `/Users/jean`). Replaced the retired MacBook Pro 15", which is no longer in the picture.
- Spotify Connect device name: `MAC-JEAN` (plain ASCII; matches the computer's Sharing/ComputerName)
- Config: `~/.config/spotify-kvm-switcher/config.toml`
- Auth token cached at: `~/.config/spotify-kvm-switcher/.spotify_cache`
- Venv: `~/.local/share/spotify-kvm-switcher/.venv` (Homebrew Python 3.14; outside ~/Documents to avoid macOS TCC/sandbox restrictions on launchd). Installed non-editable (`pip install .`) so the daemon doesn't read code from ~/Personal at runtime.
- Watched USB devices: Logitech G502 mouse (046d:c08d), Corsair K70 keyboard (1b1c:1b33)
- Running as launchd user agent: `com.jeannaude.spotify-kvm-switcher` (RunAtLoad + KeepAlive). Label kept from the prior macOS setup; plist paths now point at /Users/jean.
- Plist installed at: `~/Library/LaunchAgents/com.jeannaude.spotify-kvm-switcher.plist`
- Logs: `~/Library/Logs/spotify-kvm-switcher.err` (startup/INFO logs go to stderr; the `.log`/stdout file stays empty)
- Service management: `launchctl load/unload ~/Library/LaunchAgents/com.jeannaude.spotify-kvm-switcher.plist`

### Linux Huawei MateBook X Pro (jeansmatexpro) — COMPLETE
- Spotify Connect device name: `jeansmatexpro`
- Config: `~/.config/spotify-kvm-switcher/config.toml`
- Auth token cached at: `~/.config/spotify-kvm-switcher/.spotify_cache`
- Watched USB devices: Logitech G502 mouse (046d:c08d), Corsair K70 keyboard (1b1c:1b33)
- Running as systemd user service: `spotify-kvm-switcher.service` (enabled on boot)
- Logs: `journalctl --user -u spotify-kvm-switcher -f`

## Key Files

- `config.py` — TOML config loading/validation
- `usb_monitor.py` — `KVMUSBMonitor` with debounced USB connect detection
- `spotify_auth.py` — spotipy OAuth2 wrapper, token cached at `~/.config/spotify-kvm-switcher/.spotify_cache`
- `spotify_player.py` — `SpotifyPlayer` device discovery + playback transfer
- `daemon.py` — wires USB → Spotify, signal handling, platform-aware blocking
- `scripts/identify_usb.py` — helper to list USB VID:PIDs
- `scripts/setup_auth.py` — one-time OAuth flow
- `service/spotify-kvm-switcher.service` — systemd user service (Linux)
- `service/com.jeannaude.spotify-kvm-switcher.plist` — launchd plist (macOS)

## Dependencies

- `spotipy` — Spotify Web API
- `usb-monitor` (imports as `usbmonitor`) — cross-platform USB monitoring
- `tomli` (Python < 3.11 only) — TOML parsing
