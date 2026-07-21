import os
from pathlib import Path

from locking_zip import fsutil


def test_collect_entries_single_file(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("hello")

    entries, skipped = fsutil.collect_entries(f)

    assert entries == [(f, "note.txt")]
    assert skipped == []


def test_collect_entries_nested_folder(tmp_path):
    root = tmp_path / "myfolder"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("a")
    (root / "sub" / "b.txt").write_text("b")

    entries, skipped = fsutil.collect_entries(root)
    arcnames = sorted(arcname for _abs, arcname in entries)

    assert arcnames == ["myfolder/a.txt", "myfolder/sub/b.txt"]
    assert skipped == []


def test_collect_entries_skips_symlinks(tmp_path):
    root = tmp_path / "myfolder"
    root.mkdir()
    real = tmp_path / "real.txt"
    real.write_text("real")
    (root / "a.txt").write_text("a")

    link = root / "link.txt"
    os.symlink(real, link)

    entries, skipped = fsutil.collect_entries(root)
    arcnames = sorted(arcname for _abs, arcname in entries)

    assert arcnames == ["myfolder/a.txt"]
    assert skipped == [link]


def test_collect_entries_skips_symlinked_source(tmp_path):
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    link = tmp_path / "link_dir"
    os.symlink(real_dir, link)

    entries, skipped = fsutil.collect_entries(link)

    assert entries == []
    assert skipped == [link]


def test_compute_total_size(tmp_path):
    f1 = tmp_path / "a.txt"
    f1.write_bytes(b"x" * 100)
    f2 = tmp_path / "b.txt"
    f2.write_bytes(b"y" * 250)

    entries = [(f1, "a.txt"), (f2, "b.txt")]

    assert fsutil.compute_total_size(entries) == 350
