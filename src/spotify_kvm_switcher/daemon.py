"""Main daemon: wires USB monitor events to Spotify playback transfer."""

import logging
import platform
import signal
import sys
import threading

from .spotify_auth import get_spotify_client
from .spotify_player import SpotifyPlayer
from .usb_monitor import KVMUSBMonitor

log = logging.getLogger(__name__)


def run_daemon(config: dict):
    """Start the KVM switch daemon. Blocks until SIGTERM/SIGINT."""
    spotify_cfg = config["spotify"]
    sp = get_spotify_client(spotify_cfg["client_id"], spotify_cfg["client_secret"])
    player = SpotifyPlayer(sp, spotify_cfg["device_name"])

    def on_kvm_switch():
        player.transfer_playback()

    monitor = KVMUSBMonitor(
        watched_devices=config["usb"]["watched_devices"],
        debounce_seconds=config["debounce_seconds"],
        on_switch=on_kvm_switch,
    )

    shutdown_event = threading.Event()

    def handle_signal(signum, frame):
        sig_name = signal.Signals(signum).name
        log.info("Received %s, shutting down...", sig_name)
        monitor.stop()
        shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log.info(
        "Starting spotify-kvm-switcher (device='%s')",
        spotify_cfg["device_name"],
    )
    monitor.start()

    # Block until shutdown signal
    if platform.system() != "Darwin":
        # Linux: signal.pause() is efficient and wakes on any signal
        while not shutdown_event.is_set():
            signal.pause()
    else:
        # macOS: signal.pause() doesn't exist in all contexts; use Event.wait()
        shutdown_event.wait()

    log.info("Stopped.")
