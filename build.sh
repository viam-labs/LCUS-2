#!/bin/sh
# Package the module for the Viam registry. Dependencies install on the
# target machine from setup.sh, which is also the module's first_run script.
set -eu
cd "$(dirname "$0")"
mkdir -p dist
tar -czf dist/archive.tar.gz \
  --exclude '__pycache__' \
  meta.json \
  run.sh \
  setup.sh \
  requirements.txt \
  src
