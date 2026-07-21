#!/bin/bash
# Double-click this file in Finder to pull the newest code and update
# dependencies. Run this any time before "Run Locking Zip.command" if you
# want to make sure you're on the latest version.
cd "$(dirname "$0")"

echo "Checking for updates..."
git pull || { read -p "Update failed (see error above). Press Enter to close..."; exit 1; }

if [ ! -d venv ]; then
  python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt

echo ""
echo "Up to date. Double-click 'Run Locking Zip.command' to launch."
read -p "Press Enter to close..."
