#!/usr/bin/env bash
# Install dependencies for paper-pdf-figures.
# Usage: bash install_deps.sh [--dry-run] [--ml]
set -euo pipefail

DRY_RUN=0
ML=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --ml)      ML=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQS="$SCRIPT_DIR/../requirements.txt"
ML_REQS="$SCRIPT_DIR/../requirements-ml.txt"

echo "==> Installing Python dependencies"
run python3 -m pip install --user -r "$REQS"
if [[ "$ML" -eq 1 ]]; then
  echo "==> Installing ML dependencies (auto mode: torch + doclayout-yolo)"
  run python3 -m pip install --user -r "$ML_REQS"
fi

echo "==> Checking for system package manager"
if command -v apt-get >/dev/null 2>&1; then
  if sudo -n true 2>/dev/null; then
    echo "==> Installing poppler-utils via apt (sudo available)"
    run sudo apt-get install -y poppler-utils
  else
    echo "WARN: apt-get present but sudo not available non-interactively."
    echo "      Run manually: sudo apt-get install -y poppler-utils"
    echo "      Without poppler-utils, SVG export (pdftocairo) is unavailable."
  fi
else
  echo "WARN: apt-get not found. Install poppler-utils manually for SVG export."
  echo "      Without poppler-utils, SVG export (pdftocairo) is unavailable."
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "==> [dry-run] Done (no changes made)"
else
  echo "==> Done. Verify with: python3 scripts/check_deps.py"
fi
