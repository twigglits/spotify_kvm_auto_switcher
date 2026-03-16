"""CLI entry point for spotify-kvm-switcher."""

import argparse
import logging
import sys
from pathlib import Path

from .config import load_config
from .daemon import run_daemon


def main():
    parser = argparse.ArgumentParser(
        prog="spotify-kvm-switcher",
        description="Automatically transfer Spotify playback when a KVM switch changes the active machine.",
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to config file (default: config.toml)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose/debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    run_daemon(config)


if __name__ == "__main__":
    main()
