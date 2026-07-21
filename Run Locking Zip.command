#!/bin/bash
# Double-click this file in Finder to launch Locking Zip from source.
# First run creates a virtual environment and installs dependencies (takes a
# minute); every run after that starts in a couple of seconds.
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  echo "First-time setup: creating virtual environment..."
  python3 -m venv venv || { read -p "Setup failed. Press Enter to close..."; exit 1; }
fi

source venv/bin/activate
pip install -q -r requirements.txt || { read -p "Dependency install failed. Press Enter to close..."; exit 1; }
python3 main_gui.py || read -p "Locking Zip closed with an error above. Press Enter to close..."
