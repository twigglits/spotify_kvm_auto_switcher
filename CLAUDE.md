# Project Context

## What This Is

Spotify KVM Auto-Switcher: a Python daemon that monitors USB device connections (via KVM switch) and auto-transfers Spotify playback to the newly active machine.

3 machines share a KVM switch (Linux Workstation, macOS MacBook Pro 15", Linux Huawei MateBook X Pro). All run Spotify on the same account (Twigglits).

## Architecture

- `src/spotify_kvm_switcher/` — installable Python package with `spotify-kvm-switcher` CLI entry point
- USB events detected via `usbmonitor` library (PyPI package name: `usb-monitor`, NOT `usbmonitor`)
- Debounce (2s default) collapses rapid KVM USB events into one Spotify transfer call
- `force_play=True` forces playback to start on the target device on transfer
- Device matching by Spotify Connect name (configured per-machine in config.toml)
- Only the machine gaining USB devices fires transfer — no race condition
- USB VID/PID format differs by platform: Linux `usbmonitor` reports hex strings (`"046d"`), macOS reports decimal strings (`"1133"`). `usb_monitor.py` normalizes both to int for comparison.
- Spotify device names may contain Unicode (e.g. curly apostrophe U+2019). Config uses TOML `\u` escapes to match exactly.

## Deployment Status

### Linux Workstation (jeannaude-workstation) — COMPLETE
- Spotify Connect device name: `jeannaude-workstation`
- Config: `~/.config/spotify-kvm-switcher/config.toml`
- Auth token cached at: `~/.config/spotify-kvm-switcher/.spotify_cache`
- Watched USB devices: Logitech G502 mouse (046d:c08d), Corsair K70 keyboard (1b1c:1b33)
- Running as systemd user service: `spotify-kvm-switcher.service` (enabled on boot)
- Logs: `journalctl --user -u spotify-kvm-switcher -f`

### macOS MacBook Pro 15" (Jean's MacBook Pro) — COMPLETE
- Spotify Connect device name: `Jean\u2019s MacBook Pro` (note: curly apostrophe U+2019, not ASCII)
- Config: `~/.config/spotify-kvm-switcher/config.toml`
- Auth token cached at: `~/.config/spotify-kvm-switcher/.spotify_cache`
- Venv: `~/.local/share/spotify-kvm-switcher/.venv` (outside ~/Documents to avoid macOS TCC/sandbox restrictions on launchd)
- Watched USB devices: Logitech G502 mouse (046d:c08d), Corsair K70 keyboard (1b1c:1b33)
- Running as launchd user agent: `com.jeannaude.spotify-kvm-switcher` (RunAtLoad + KeepAlive)
- Plist installed at: `~/Library/LaunchAgents/com.jeannaude.spotify-kvm-switcher.plist`
- Logs: `~/Library/Logs/spotify-kvm-switcher.log` and `~/Library/Logs/spotify-kvm-switcher.err`
- Service management: `launchctl load/unload ~/Library/LaunchAgents/com.jeannaude.spotify-kvm-switcher.plist`

### Linux Huawei MateBook X Pro — NOT SET UP

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
