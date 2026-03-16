"""USB event detection with debouncing for KVM switch detection."""

import logging
import threading

from usbmonitor import USBMonitor
from usbmonitor.attributes import ID_MODEL_ID, ID_VENDOR_ID

log = logging.getLogger(__name__)


class KVMUSBMonitor:
    """Watches for specific USB device connections and fires a debounced callback.

    When a KVM switch occurs, multiple USB devices reconnect in rapid succession.
    This class collapses those events into a single callback after a debounce period.
    """

    def __init__(self, watched_devices: list[dict], debounce_seconds: float, on_switch: callable):
        """
        Args:
            watched_devices: List of dicts with ID_VENDOR_ID and ID_MODEL_ID keys.
            debounce_seconds: Seconds to wait after last USB event before firing callback.
            on_switch: Callable invoked (no args) when a KVM switch is detected.
        """
        self._watched = {
            (d["ID_VENDOR_ID"].lower(), d["ID_MODEL_ID"].lower())
            for d in watched_devices
        }
        self._debounce_seconds = debounce_seconds
        self._on_switch = on_switch
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._monitor = USBMonitor()

    def _is_watched(self, device_info: dict) -> bool:
        vid = device_info.get(ID_VENDOR_ID, "").lower()
        mid = device_info.get(ID_MODEL_ID, "").lower()
        return (vid, mid) in self._watched

    def _on_connect(self, device_id: str, device_info: dict):
        if not self._is_watched(device_info):
            return

        vid = device_info.get(ID_VENDOR_ID, "")
        mid = device_info.get(ID_MODEL_ID, "")
        log.debug("Watched USB device connected: %s (VID:%s MID:%s)", device_id, vid, mid)

        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_seconds, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self):
        log.info("KVM switch detected (USB devices settled)")
        try:
            self._on_switch()
        except Exception:
            log.exception("Error in KVM switch callback")

    def start(self):
        log.info(
            "Monitoring USB for %d watched device(s), debounce=%.1fs",
            len(self._watched), self._debounce_seconds,
        )
        self._monitor.start_monitoring(on_connect=self._on_connect)

    def stop(self):
        log.info("Stopping USB monitor")
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._monitor.stop_monitoring()
