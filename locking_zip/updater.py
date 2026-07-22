"""Self-update: on launch, a frozen build checks GitHub for a newer packaged
build and, if there is one, downloads it, swaps itself in place, and relaunches.

Design rules:
- **Best-effort, never blocks launch.** Every failure path (offline, timeout,
  bad download, swap error) is caught and falls through to running the version
  already installed. The app must always open.
- **Frozen-only.** Running from source (`not sys.frozen`) or an un-stamped build
  (`BUILD_SHA == "dev"`) skips updating entirely -- source users update via git.
- **No auth, no dependencies.** The repo is public, so the GitHub API and asset
  downloads need no token; only stdlib (`urllib`, `json`, `zipfile`) is used.

The in-place swap can't overwrite the running bundle directly, so it stages the
new build to a temp dir and hands off to a small detached helper script that
waits for this process to exit, replaces the bundle, and relaunches it.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from locking_zip._build_info import BUILD_SHA

OWNER = "dmallard000001111"
REPO = "Locking-zip"
_TAG_REF_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/git/refs/tags/latest"
_RELEASE_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/tags/latest"
_TIMEOUT = 8  # seconds; keep launch snappy when up-to-date or on a slow network


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def current_build_label() -> str:
    """Human-readable build identity for display in the UI. Changes when the
    app self-updates, so it doubles as visible proof an update landed."""
    if BUILD_SHA == "dev":
        return "LockZip · source build"
    return f"LockZip · build {BUILD_SHA[:7]}"


def platform_asset_name() -> Optional[str]:
    if sys.platform == "darwin":
        return "LockZip-macOS-AppleSilicon.zip"
    if sys.platform.startswith("win"):
        return "LockZip-Windows.zip"
    return None


def should_update(installed_sha: str, latest_sha: Optional[str]) -> bool:
    """True only when we know both SHAs and they differ. 'dev' (source build)
    or an unknown latest SHA both mean 'do nothing'."""
    if not latest_sha:
        return False
    if not installed_sha or installed_sha == "dev":
        return False
    return installed_sha != latest_sha


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_latest_sha() -> Optional[str]:
    try:
        data = _get_json(_TAG_REF_URL)
        return data.get("object", {}).get("sha")
    except Exception:
        return None


def _find_asset_url(asset_name: str) -> Optional[str]:
    try:
        data = _get_json(_RELEASE_URL)
    except Exception:
        return None
    for asset in data.get("assets", []):
        if asset.get("name") == asset_name:
            return asset.get("browser_download_url")
    return None


def _current_bundle_root() -> Path:
    """The directory to replace on update.

    macOS: the `.app` bundle root (…/LockZip.app). Windows/onedir: the folder
    containing the executable (…/LockZip/)."""
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent
        return exe.parent
    return exe.parent


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT * 4) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def _spawn_swap_helper(new_bundle: Path, target: Path) -> None:
    """Write and detach a helper that waits for us to exit, swaps the bundle,
    and relaunches. Detaching is what lets the swap happen after we quit."""
    pid = os.getpid()
    if sys.platform == "darwin":
        script = target.parent / ".lockzip_update.sh"
        staged = f"{target}.update-tmp"
        # Copy the new bundle in next to the old one FIRST (same volume), and
        # only remove the old one once the copy succeeded -- so a failure never
        # leaves the user with no app. If anything goes wrong we still relaunch
        # whatever is at `target`.
        script.write_text(
            "#!/bin/bash\n"
            f'while kill -0 {pid} 2>/dev/null; do sleep 0.3; done\n'
            f'rm -rf "{staged}"\n'
            f'if cp -R "{new_bundle}" "{staged}"; then\n'
            f'  rm -rf "{target}"\n'
            f'  mv "{staged}" "{target}"\n'
            f'  xattr -cr "{target}" 2>/dev/null || true\n'
            f'fi\n'
            f'open "{target}"\n'
            f'rm -f "{script}"\n'
        )
        script.chmod(0o755)
        subprocess.Popen(
            ["/bin/bash", str(script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    elif sys.platform.startswith("win"):
        script = target.parent / "_lockzip_update.cmd"
        exe = target / "LockZip.exe"
        staged = f"{target}.update-tmp"
        # Same safety shape as macOS: copy the new folder in beside the old one
        # first, and only remove the old one once the copy is verified present.
        script.write_text(
            "@echo off\r\n"
            ":wait\r\n"
            f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL\r\n'
            "if not errorlevel 1 (\r\n"
            "  timeout /t 1 /nobreak >NUL\r\n"
            "  goto wait\r\n"
            ")\r\n"
            f'if exist "{staged}" rmdir /S /Q "{staged}"\r\n'
            f'xcopy /E /I /Y /Q "{new_bundle}" "{staged}" >NUL\r\n'
            f'if exist "{staged}\\LockZip.exe" (\r\n'
            f'  rmdir /S /Q "{target}"\r\n'
            f'  move "{staged}" "{target}" >NUL\r\n'
            f')\r\n'
            f'start "" "{exe}"\r\n'
            f'del "%~f0"\r\n'
        )
        subprocess.Popen(
            ["cmd", "/c", str(script)],
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            close_fds=True,
        )
    else:
        raise RuntimeError("Unsupported platform for self-update")


def _show_updating_window():
    """Tiny 'Updating…' splash so a slow download isn't a frozen dock icon.
    Returned object has .close(); failures here are non-fatal."""
    try:
        import tkinter as tk

        win = tk.Tk()
        win.title("LockZip")
        win.geometry("260x90")
        win.configure(bg="#0f1117")
        tk.Label(
            win, text="Updating LockZip…", bg="#0f1117", fg="#eef0f6", font=("", 13, "bold")
        ).pack(expand=True)
        win.update()
        return win
    except Exception:
        return None


def maybe_update() -> None:
    """Entry point called from main_gui before the GUI starts. Silent no-op
    unless a frozen build finds a newer published build; then it stages the
    update, hands off to the swap helper, and exits this process so the helper
    can relaunch the new version."""
    try:
        if not is_frozen() or BUILD_SHA == "dev":
            return
        asset_name = platform_asset_name()
        if not asset_name:
            return

        latest_sha = fetch_latest_sha()
        if not should_update(BUILD_SHA, latest_sha):
            return

        asset_url = _find_asset_url(asset_name)
        if not asset_url:
            return

        splash = _show_updating_window()
        try:
            staging = Path(tempfile.mkdtemp(prefix="lockzip_update_"))
            zip_path = staging / asset_name
            _download(asset_url, zip_path)

            extract_dir = staging / "extracted"
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(extract_dir)

            target = _current_bundle_root()
            new_bundle = _locate_new_bundle(extract_dir, target)
            if new_bundle is None:
                return

            _spawn_swap_helper(new_bundle, target)
        finally:
            if splash is not None:
                try:
                    splash.destroy()
                except Exception:
                    pass

        # Hand-off done; quit so the detached helper can replace and relaunch us.
        os._exit(0)
    except Exception:
        # Any failure: fall through and let the caller launch the installed build.
        return


def _locate_new_bundle(extract_dir: Path, target: Path) -> Optional[Path]:
    """Find the freshly-extracted bundle whose name matches what we're replacing
    (LockZip.app on macOS, LockZip/ folder on Windows)."""
    wanted = target.name
    direct = extract_dir / wanted
    if direct.exists():
        return direct
    for child in extract_dir.iterdir():
        if child.name == wanted:
            return child
    # ditto/Compress-Archive sometimes nest one level deeper.
    for child in extract_dir.iterdir():
        if child.is_dir():
            nested = child / wanted
            if nested.exists():
                return nested
    return None
