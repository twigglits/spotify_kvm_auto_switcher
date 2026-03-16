# Spotify KVM Auto-Switcher

Automatically transfers Spotify playback to the active machine when a KVM switch changes input. Runs as a lightweight daemon on each machine, monitoring USB device connections (keyboard/mouse reconnect) and calling the Spotify Web API to transfer playback.

## Supported Platforms

- Linux (pyudev)
- macOS (IOKit)

## Setup

### 1. Create a Spotify Developer App

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Set the redirect URI to `http://127.0.0.1:8888/callback`
4. Note the Client ID and Client Secret

### 2. Install

```bash
pip install -e .
```

### 3. Identify Your USB Devices

Find the VID:PID of your keyboard/mouse that connect through the KVM:

```bash
python scripts/identify_usb.py
```

### 4. Configure

```bash
cp config.example.toml config.toml
```

Edit `config.toml`:
- Set `spotify.client_id` and `spotify.client_secret` from step 1
- Set `spotify.device_name` to this machine's Spotify device name
- Add your KVM keyboard/mouse VID:PID to `usb.watched_devices`

### 5. Authenticate with Spotify

Run once per machine to complete the OAuth flow:

```bash
python scripts/setup_auth.py
```

This opens a browser for Spotify login and prints available device names.

### 6. Run

```bash
# Foreground with verbose logging
spotify-kvm-switcher --config config.toml --verbose

# Or just
spotify-kvm-switcher -v
```

### 7. Install as a Service (Optional)

**Linux (systemd user service):**

```bash
cp config.toml ~/.config/spotify-kvm-switcher/config.toml
cp service/spotify-kvm-switcher.service ~/.config/systemd/user/
systemctl --user enable --now spotify-kvm-switcher
```

**macOS (launchd):**

```bash
# Edit the plist to match your paths first
cp service/com.jeannaude.spotify-kvm-switcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jeannaude.spotify-kvm-switcher.plist
```

## How It Works

1. The daemon monitors USB device connections using `usbmonitor`
2. When a KVM switch occurs, your keyboard/mouse disconnect from one machine and reconnect to another
3. The machine gaining USB devices detects the connection events
4. After a debounce period (default 2s), it calls the Spotify API to transfer playback
5. `force_play=False` preserves the play/pause state - if music was paused, it stays paused

## Configuration Reference

```toml
debounce_seconds = 2.0          # Collapse rapid USB events into one transfer

[spotify]
client_id = "..."               # From Spotify Developer Dashboard
client_secret = "..."           # From Spotify Developer Dashboard
device_name = "My Machine"      # This machine's Spotify Connect name

[usb]
[[usb.watched_devices]]
ID_VENDOR_ID = "046d"           # USB Vendor ID (hex)
ID_MODEL_ID = "c52b"            # USB Model ID (hex)
```
