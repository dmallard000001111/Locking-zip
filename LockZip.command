#!/bin/bash
# Double-click this file in Finder to update to the newest version and launch
# LockZip -- one file, no need to run a separate update step first.
cd "$(dirname "$0")"

echo "Checking for updates..."
git pull || echo "Couldn't check for updates (offline?) -- launching the version already here."

if [ ! -d venv ]; then
  echo "First-time setup: creating virtual environment..."
  python3 -m venv venv || { read -p "Setup failed. Press Enter to close..."; exit 1; }
fi

source venv/bin/activate
pip install -q -r requirements.txt || { read -p "Dependency install failed. Press Enter to close..."; exit 1; }
python3 main_gui.py || read -p "LockZip closed with an error above. Press Enter to close..."
