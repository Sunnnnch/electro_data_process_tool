#!/bin/bash
# Run with: bash Start_Mac.command (the checkout need not retain executable bits).
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ "$(uname -s)" != "Darwin" ]]; then
  printf '%s\n' 'This launcher requires macOS 13 or newer.' >&2
  exit 1
fi
if [[ ! -x .venv-macos/bin/python ]]; then
  python3.12 -m venv .venv-macos
fi
.venv-macos/bin/python packaging/install_macos_dependencies.py --ensure
exec .venv-macos/bin/python packaging/electrochem_macos_launcher.py "$@"
