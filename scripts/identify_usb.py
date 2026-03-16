#!/usr/bin/env python3
"""List connected USB devices with VID:PID for KVM switcher configuration.

Run this script to find the vendor and model IDs of your keyboard/mouse
that connect through the KVM switch. Use these values in config.toml.
"""

from usbmonitor import USBMonitor
from usbmonitor.attributes import ID_MODEL, ID_MODEL_ID, ID_VENDOR, ID_VENDOR_ID


def main():
    monitor = USBMonitor()
    devices = monitor.get_available_devices()

    if not devices:
        print("No USB devices found.")
        return

    print(f"{'VID:MID':<12} {'Vendor':<30} {'Model'}")
    print("-" * 72)

    for device_id, info in sorted(devices.items()):
        vid = info.get(ID_VENDOR_ID, "????")
        mid = info.get(ID_MODEL_ID, "????")
        vendor = info.get(ID_VENDOR, "Unknown")
        model = info.get(ID_MODEL, "Unknown")
        print(f"{vid}:{mid:<5} {vendor:<30} {model}")

    print()
    print("Add watched devices to config.toml like this:")
    print()
    print('[[usb.watched_devices]]')
    print('ID_VENDOR_ID = "046d"')
    print('ID_MODEL_ID = "c52b"')


if __name__ == "__main__":
    main()
