#!/usr/bin/env bash
# One-click installer entry for paper-pdf-figures.
# Usage: bash install.sh [--yes] [--package PATH] [--target PATH] [--ml|--no-ml] [--ml-env PYTHON] [--dry-run]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/install.py" "$@"
