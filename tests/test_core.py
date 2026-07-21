import threading

import pyzipper
import pytest

from locking_zip import core, fsutil


def _make_source(tmp_path, name="myfolder"):
    root = tmp_path / name
    root.mkdir()
    (root / "a.txt").write_text("hello world")
    sub = root / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("nested contents")
    return root


def test_round_trip_correct_password(tmp_path):
    source = _make_source(tmp_path)
    entries, _skipped = fsutil.collect_entries(source)
    dest = tmp_path / "out.zip"

    core.encrypt_to_zip(entries, dest, "correct-horse")

    with pyzipper.ZipFile(dest) as zf:
        names = sorted(zf.namelist())
        assert names == ["myfolder/a.txt", "myfolder/sub/b.txt"]
        assert zf.read("myfolder/a.txt", pwd=b"correct-horse") == b"hello world"
        assert zf.read("myfolder/sub/b.txt", pwd=b"correct-horse") == b"nested contents"


def test_wrong_password_raises(tmp_path):
    source = _make_source(tmp_path)
    entries, _skipped = fsutil.collect_entries(source)
    dest = tmp_path / "out.zip"

    core.encrypt_to_zip(entries, dest, "correct-horse")

    with pyzipper.ZipFile(dest) as zf:
        with pytest.raises(RuntimeError):
            zf.read("myfolder/a.txt", pwd=b"wrong-password")


def test_data_descriptor_flag_set(tmp_path):
    source = _make_source(tmp_path)
    entries, _skipped = fsutil.collect_entries(source)
    dest = tmp_path / "out.zip"

    core.encrypt_to_zip(entries, dest, "correct-horse")

    with pyzipper.ZipFile(dest) as zf:
        for info in zf.infolist():
            assert info.flag_bits & 0x08, "expected data-descriptor bit set"
            assert info.flag_bits & 0x01, "expected encrypted bit set"


def test_overwrite_false_raises_when_exists(tmp_path):
    source = _make_source(tmp_path)
    entries, _skipped = fsutil.collect_entries(source)
    dest = tmp_path / "out.zip"
    dest.write_bytes(b"not a zip")

    with pytest.raises(core.OutputExistsError):
        core.encrypt_to_zip(entries, dest, "pw", overwrite=False)


def test_overwrite_true_replaces_existing(tmp_path):
    source = _make_source(tmp_path)
    entries, _skipped = fsutil.collect_entries(source)
    dest = tmp_path / "out.zip"
    dest.write_bytes(b"not a zip")

    core.encrypt_to_zip(entries, dest, "pw", overwrite=True)

    with pyzipper.ZipFile(dest) as zf:
        assert zf.read("myfolder/a.txt", pwd=b"pw") == b"hello world"


def test_empty_entries_produces_valid_empty_zip(tmp_path):
    dest = tmp_path / "out.zip"

    core.encrypt_to_zip([], dest, "pw")

    with pyzipper.ZipFile(dest) as zf:
        assert zf.namelist() == []


def test_progress_callback_monotonic_and_complete(tmp_path):
    source = _make_source(tmp_path)
    entries, _skipped = fsutil.collect_entries(source)
    dest = tmp_path / "out.zip"
    total = fsutil.compute_total_size(entries)

    seen = []
    core.encrypt_to_zip(
        entries, dest, "pw", total_size=total,
        progress_cb=lambda done, tot, name: seen.append((done, tot)),
    )

    assert seen, "expected at least one progress callback"
    done_values = [d for d, _t in seen]
    assert done_values == sorted(done_values)
    assert seen[-1][0] == total


def test_cancel_mid_run_raises_and_cleans_up(tmp_path):
    source = _make_source(tmp_path)
    entries, _skipped = fsutil.collect_entries(source)
    dest = tmp_path / "out.zip"

    cancel_event = threading.Event()

    def progress_cb(done, total, name):
        cancel_event.set()

    with pytest.raises(core.CancelledError):
        core.encrypt_to_zip(
            entries, dest, "pw",
            progress_cb=progress_cb, cancel_event=cancel_event,
        )

    assert not dest.exists()
    assert not dest.with_name(dest.name + ".part").exists()


def test_password_never_appears_in_exception_message(tmp_path):
    source = _make_source(tmp_path)
    entries, _skipped = fsutil.collect_entries(source)
    dest = tmp_path / "out.zip"
    dest.write_bytes(b"already here")

    secret = "s3cr3t-password-xyz"
    try:
        core.encrypt_to_zip(entries, dest, secret, overwrite=False)
    except core.OutputExistsError as e:
        assert secret not in str(e)
