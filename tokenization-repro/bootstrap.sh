#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -m venv "$BUNDLE_DIR/.venv"
"$BUNDLE_DIR/.venv/bin/python" -m pip install -r "$BUNDLE_DIR/requirements.txt"
"$BUNDLE_DIR/.venv/bin/python" "$BUNDLE_DIR/check_setup.py" --require-model-b
