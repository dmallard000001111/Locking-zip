# Locking Zip

A tiny drag-and-drop app: drop a file or folder onto it, set a password, and it
saves a password-protected `.zip` you can open anywhere with a double-click and
the password -- no extra software needed on either Mac or Windows.

## 0. Download the app (no coding needed)

Ready-made downloads live on this repo's **Releases** page (right sidebar on
GitHub, or `/releases`): one "Latest builds" entry with a macOS Apple Silicon
zip and a Windows zip, rebuilt on demand from the newest code.

- **macOS (Apple Silicon: M1/M2/M3/M4)** -- unzip, put `LockingZip.app`
  anywhere, then **right-click it and choose Open** the first time (the app is
  unsigned, so a plain double-click shows a warning with no Open button).
- **macOS (Intel)** -- there's no packaged download for Intel Macs (GitHub
  retired its hosted Intel macOS build machines, so we can't produce one
  automatically). Run it from source instead -- see **section 3**, it's a
  one-time setup and after that it's just double-clicking a file, same as any
  other app.
- **Windows** -- unzip the whole folder and run `LockingZip.exe` inside it.
  If SmartScreen says "Windows protected your PC", click **More info -> Run
  anyway** (same unsigned-app reason).

To refresh the downloads after code changes: GitHub -> **Actions** tab ->
**Build releases** -> **Run workflow**.

## 1. Using the app

1. Drag a file or folder onto the window (or use **Choose File…** / **Choose
   Folder…**).
2. Click **Encrypt…**, set a password (typed twice to confirm), and pick where
   to save the resulting `.zip`.
3. That's it -- the zip is created with a progress bar, and a **Cancel**
   button if you change your mind partway through a large folder.

Symbolic links inside a dropped folder are skipped (never followed) and you'll
be told how many were skipped before the zip is created.

## 2. Opening the resulting zip

Just double-click it and enter the password when prompted -- this uses the
standard/legacy zip password format that Windows Explorer and macOS Archive
Utility both support natively, so nothing extra needs installing on either
platform.

**Security note:** this is the classic zip password scheme, not modern AES
encryption. It's fine for casually keeping a file away from prying eyes, but
it's crackable by someone with the right tools and enough motivation --
**don't rely on it for highly sensitive data.** A long, unique password still
helps a lot. The app never stores or logs your password anywhere; if you
forget it, there is no recovery.

## 3. Running on Intel Mac (or any machine, from source)

Needs Python 3 -- macOS usually has it already; check with `python3 --version`
in Terminal, or install from https://python.org if that command isn't found.

**One-time setup:**
```
git clone <this repo's URL>
cd Locking-zip
```

That's it -- from here on, everything is double-clicking files in Finder, no
Terminal needed:

- **`Run Locking Zip.command`** -- launches the app. The very first
  double-click sets up a Python virtual environment and installs dependencies
  (takes about a minute); every launch after that is a couple of seconds.
- **`Update Locking Zip.command`** -- pulls the newest code from GitHub and
  updates dependencies. Run this whenever you want to make sure you're on the
  current version, then launch as usual.

(First time only: macOS may warn that these are unidentified scripts --
right-click each one and choose **Open** once to approve it, same as with any
downloaded script.)

Prefer the terminal instead? The two `.command` files above are just thin
wrappers around this:
```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main_gui.py       # launches the app
git pull                 # to update later, then re-run the two lines above
```

```
python -m pytest tests/ -q
```

### Rebuilding the packaged app

```
pyinstaller packaging/LockingZip.spec --noconfirm
```

This produces a onedir, windowed build at `dist/LockingZip` (and, on macOS,
`dist/LockingZip.app`). The GitHub Actions workflow does the same thing plus a
`--selftest` check that the frozen build's drag-and-drop extension actually
loads, then packages and publishes both platforms to the rolling `latest`
release.
