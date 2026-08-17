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
