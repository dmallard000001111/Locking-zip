"""Pure helper functions used by gui.py, kept Tk-free so they're unit-testable
without a display (the CI `test` job runs headless on Ubuntu)."""
from pathlib import Path
from typing import Callable, List, Optional


def parse_dropped_paths(raw: str, splitlist_fn: Callable[[str], List[str]]) -> List[str]:
    """Parse a tkinterdnd2 DND_FILES payload into a list of paths.

    tkinterdnd2 hands back a Tcl list where paths containing spaces are wrapped
    in {braces} -- a naive `raw.split(' ')` would split those apart. `splitlist_fn`
    should be the owning widget's `tk.splitlist`, which parses Tcl list syntax
    correctly.
    """
    return list(splitlist_fn(raw))


def passwords_match(password: str, confirm: str) -> bool:
    return bool(password) and password == confirm


def suggest_dest_name(source: Path) -> str:
    return f"{Path(source).stem}.zip"


def validate_source(path: Optional[Path]) -> Optional[str]:
    """Return an error string if `path` isn't a usable source, else None."""
    if path is None:
        return "No file or folder selected."
    path = Path(path)
    if not path.exists():
        return f"'{path}' no longer exists."
    if path.is_symlink():
        return "Can't encrypt a symlink directly -- drop the real file or folder."
    return None


def estimate_strength(password: str) -> str:
    """Rough, cosmetic-only password strength label -- not a security gate."""
    length = len(password)
    variety = sum([
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ])
    if length == 0:
        return ""
    if length < 8 or variety <= 1:
        return "Weak"
    if length < 12 or variety <= 2:
        return "Medium"
    return "Strong"
