"""Filesystem helpers for building the list of zip entries from a file or folder."""
import os
from pathlib import Path
from typing import List, Tuple


def collect_entries(source: Path) -> Tuple[List[Tuple[Path, str]], List[Path]]:
    """Return (entries, skipped_symlinks) for `source`.

    entries is a list of (absolute_path, posix_arcname) pairs. A single file
    becomes one entry named after itself; a folder is walked recursively with
    arcnames rooted under the folder's own name, so extracting the zip
    recreates the top-level folder rather than dumping its contents loose.
    Symlinks are never followed -- they're collected separately so the caller
    can warn about them instead of silently skipping or dereferencing them.
    """
    source = Path(source)
    entries: List[Tuple[Path, str]] = []
    skipped: List[Path] = []

    if source.is_symlink():
        skipped.append(source)
        return entries, skipped

    if source.is_file():
        entries.append((source, source.name))
        return entries, skipped

    root_name = source.name
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
        for filename in filenames:
            abs_path = Path(dirpath) / filename
            if abs_path.is_symlink():
                skipped.append(abs_path)
                continue
            rel = abs_path.relative_to(source)
            arcname = "/".join((root_name, *rel.parts))
            entries.append((abs_path, arcname))

    return entries, skipped


def compute_total_size(entries: List[Tuple[Path, str]]) -> int:
    """Sum on-disk byte sizes of all entries, used as the progress denominator."""
    total = 0
    for abs_path, _arcname in entries:
        total += abs_path.stat().st_size
    return total
