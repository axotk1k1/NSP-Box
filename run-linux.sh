#!/usr/bin/env bash
# Launch NSP Box from source on Linux (Arch: sudo pacman -S python tk).
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python -m venv .venv
  .venv/bin/pip install Pillow==12.2.0 zstandard==0.25.0
fi
exec .venv/bin/python src/app.py "$@"
