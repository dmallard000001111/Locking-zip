#!/usr/bin/env python3
"""Entry point for the double-clickable GUI app."""
import sys


def _selftest():
    """Invoked as `LockZip --selftest` by the CI build job. Instantiates a real
    TkinterDnD.Tk() rather than just importing tkinterdnd2 -- its tkdnd Tcl
    extension is loaded at runtime, not at import time, so a frozen build can
    have a working import but a broken drag-and-drop extension (see gui.py)."""
    try:
        from tkinter import ttk  # noqa: F401
        import pyzipper  # noqa: F401
        from locking_zip import core, fsutil, gui_logic, updater  # noqa: F401
        from tkinterdnd2 import TkinterDnD

        root = TkinterDnD.Tk()
        root.withdraw()
        root.destroy()
        print("SELFTEST_OK")
        return 0
    except Exception as e:
        print(f"SELFTEST_FAIL: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())

    # Best-effort: pull the newest build from the cloud before launching. This
    # is a no-op when running from source or offline; it never blocks launch
    # (see updater.maybe_update). If it applies an update it relaunches and
    # exits, so anything past this line runs the current, up-to-date build.
    from locking_zip import updater
    updater.maybe_update()

    from locking_zip.gui import main
    main()
