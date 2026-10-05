#!/bin/sh
# Create the virtualenv viam-server uses to run this module.
set -eu
cd "$(dirname "$0")"

if ! python3 -c "import venv" 2>/dev/null; then
  echo "python3 venv is required. On Debian/Ubuntu: sudo apt install python3-venv" >&2
  exit 1
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install -r requirements.txt
