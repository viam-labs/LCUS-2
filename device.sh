#!/bin/sh
# Pulse an attached LCUS-2: each coil on, then off.
set -eu
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  ./setup.sh
fi

exec .venv/bin/python -m scripts.device "$@"
