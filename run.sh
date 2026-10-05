#!/bin/sh
# Entrypoint for viam-server. The socket path is passed through to the module.
set -eu
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  ./setup.sh
fi

exec .venv/bin/python -m src.main "$@"
