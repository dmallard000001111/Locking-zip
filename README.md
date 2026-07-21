# Zip Lock

A tiny drag-and-drop app: drop a file or folder onto it, set a password, and it
saves a password-protected `.zip`. Choose **Standard** protection (opens
anywhere with a double-click, no extra software) or **AES-256** (much
stronger, but needs a tool like 7-Zip or Keka to open). Zip Lock can also
**unlock** protected zips right in the app -- either kind it made, or most
password-protected zips from other tools.

## 0. Download the app (no coding needed)

Ready-made downloads live on this repo's **Releases** page (right sidebar on
GitHub, or `/releases`): one "Latest builds" entry with a macOS Apple Silicon
zip and a Windows zip, rebuilt on demand from the newest code.

- **macOS (Apple Silicon: M1/M2/M3/M4)** -- unzip, put `Zip Lock.app`
  anywhere, then **right-click it and choose Open** the first time (the app is
  unsigned, so a plain double-click shows a warning with no Open button).
- **macOS (Intel)** -- there's no packaged download for Intel Macs (GitHub
  retired its hosted Intel macOS build machines, so we can't produce one
  automatically). Run it from source instead -- see **section 4**, it's a
  one-time setup and after that it's just double-clicking a file, same as any
  other app.
- **Windows** -- unzip the whole folder and run `Zip Lock.exe` inside it.
  If SmartScreen says "Windows protected your PC", click **More info -> Run
  anyway** (same unsigned-app reason).

To refresh the downloads after code changes: GitHub -> **Actions** tab ->
**Build releases** -> **Run workflow**.

## 1. Locking a file or folder

1. Make sure the **Lock** tab is selected (it's the default).
2. Drag a file or folder onto the window (or use the **choose a file** /
   **choose a folder** links).
3. Click **Encrypt…**, set a password (typed twice to confirm), pick a
   **protection level**, and choose where to save the resulting `.zip`.
4. That's it -- the zip is created with a progress bar, and a **Cancel**
   button if you change your mind partway through a large folder.

Symbolic links inside a dropped folder are skipped (never followed) and you'll
be told how many were skipped before the zip is created.

### Choosing a protection level

- **Standard** -- opens with a plain double-click and password prompt on
  stock Windows (Explorer) and macOS (Archive Utility), no extra software
  needed anywhere. This is the classic zip password scheme, not modern
  encryption -- fine for casually keeping a file away from prying eyes, but
  crackable by someone with the right tools and enough motivation. **Don't
  rely on it for highly sensitive data.**
- **AES-256** -- real, strong encryption. Neither Windows nor macOS can open
  it with their built-in tools, though -- the recipient needs **7-Zip**
  (Windows) or **Keka** / **The Unarchiver** (Mac), or they can use Zip Lock's
  own **Unlock** tab.

Either way: Zip Lock never stores or logs your password anywhere; if you
forget it, there is no recovery.

## 2. Unlocking a zip

1. Switch to the **Unlock** tab.
2. Drag a password-protected `.zip` onto the window (or use **choose a zip
   file**).
3. Pick where to extract it, then enter the password.
4. If the password's wrong, you'll be asked to try again without having to
   re-pick the file or the destination.

This works on zips Zip Lock made in either protection level, and on most
password-protected zips from other tools too.

## 3. Development

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main_gui.py       # run the app from source
python -m pytest tests/ -q
```

### Rebuilding the packaged app

```
pyinstaller packaging/ZipLock.spec --noconfirm
```

This produces a onedir, windowed build at `dist/Zip Lock` (and, on macOS,
`dist/Zip Lock.app`). The GitHub Actions workflow does the same thing plus a
`--selftest` check that the frozen build's drag-and-drop extension actually
loads, then packages and publishes both platforms to the rolling `latest`
release.

## 4. Running on Intel Mac (or any machine, from source)

Needs Python 3 -- macOS usually has it already; check with `python3 --version`
in Terminal, or install from https://python.org if that command isn't found.

**One-time setup:**
```
git clone <this repo's URL>
cd Locking-zip
```

That's it -- from here on, everything is double-clicking files in Finder, no
Terminal needed:

- **`Run Zip Lock.command`** -- launches the app. The very first
  double-click sets up a Python virtual environment and installs dependencies
  (takes about a minute); every launch after that is a couple of seconds.
- **`Update Zip Lock.command`** -- pulls the newest code from GitHub and
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
