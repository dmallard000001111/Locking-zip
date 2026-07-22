import sys

from locking_zip import updater


def test_platform_asset_name(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert updater.platform_asset_name() == "LockZip-macOS-AppleSilicon.zip"

    monkeypatch.setattr(sys, "platform", "win32")
    assert updater.platform_asset_name() == "LockZip-Windows.zip"

    monkeypatch.setattr(sys, "platform", "linux")
    assert updater.platform_asset_name() is None


def test_should_update_same_sha_is_false():
    assert updater.should_update("abc123", "abc123") is False


def test_should_update_different_sha_is_true():
    assert updater.should_update("abc123", "def456") is True


def test_should_update_dev_build_never_updates():
    # A source build (BUILD_SHA == "dev") must never try to self-update.
    assert updater.should_update("dev", "anything") is False


def test_should_update_unknown_latest_is_false():
    # Network hiccup / couldn't read the latest SHA -> do nothing.
    assert updater.should_update("abc123", None) is False


def test_is_frozen_false_when_running_from_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert updater.is_frozen() is False


def test_maybe_update_noop_from_source(monkeypatch):
    # From source it must return without touching the network or exiting.
    called = {"fetch": False}

    def _boom():
        called["fetch"] = True
        raise AssertionError("fetch_latest_sha must not be called from source")

    monkeypatch.setattr(updater, "fetch_latest_sha", _boom)
    monkeypatch.setattr(updater, "is_frozen", lambda: False)

    updater.maybe_update()  # should not raise, not exit, not fetch
    assert called["fetch"] is False


def test_maybe_update_noop_when_dev_build(monkeypatch):
    # Even if somehow "frozen", a dev BUILD_SHA short-circuits before any fetch.
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(updater, "BUILD_SHA", "dev")

    def _boom():
        raise AssertionError("must not fetch when BUILD_SHA is dev")

    monkeypatch.setattr(updater, "fetch_latest_sha", _boom)
    updater.maybe_update()  # returns quietly
