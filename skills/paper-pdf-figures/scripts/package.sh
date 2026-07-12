#!/usr/bin/env bash
# Package the paper-pdf-figures skill into a .skill (zip) for distribution.
# Usage: bash scripts/package.sh
#
# Produces:
#   dist/paper-pdf-figures-<version>.skill   (zip, top-level dir paper-pdf-figures/)
#   dist/MANIFEST.txt                         (file list + sha256)
#
# Matches the wolai-to-github.skill precedent in this repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# package.sh is at <repo>/skills/paper-pdf-figures/scripts/package.sh
# repo root is 3 levels up from scripts/: scripts -> paper-pdf-figures -> skills -> <repo>
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
DIST="$REPO_ROOT/dist"

VERSION="$(cat "$SKILL_ROOT/VERSION" | tr -d '[:space:]')"
PKG_NAME="paper-pdf-figures-${VERSION}.skill"
PKG_PATH="$DIST/$PKG_NAME"

echo "==> Packaging paper-pdf-figures v$VERSION"

# 1. check_deps (required deps must be present)
echo "==> Checking dependencies"
if ! python3 "$SKILL_ROOT/scripts/check_deps.py" >/tmp/pkg_deps.txt 2>&1; then
    cat /tmp/pkg_deps.txt
    echo "ERROR: check_deps.py reports missing required deps. Install them before packaging."
    echo "  pip install -r requirements.txt  (required)"
    echo "  pip install -r requirements-ml.txt  (optional, for auto mode)"
    exit 1
fi
echo "    deps OK ($(grep -c '\[OK\]' /tmp/pkg_deps.txt) OK, $(grep -c '\[WARN\]' /tmp/pkg_deps.txt) WARN)"

# 2. build a clean staging dir (no caches / pyc / test artifacts)
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
STAGE_SKILL="$STAGE/paper-pdf-figures"
mkdir -p "$STAGE_SKILL"

# copy everything except caches / pyc / pytest / models / __pycache__
cd "$SKILL_ROOT"
find . -type f \
    ! -path './__pycache__/*' \
    ! -path '*/__pycache__/*' \
    ! -name '*.pyc' \
    ! -path './.pytest_cache/*' \
    ! -path '*/.pytest_cache/*' \
    ! -path './models/*' \
    ! -name '*.skill' \
    -print0 | while IFS= read -r -d '' f; do
    mkdir -p "$STAGE_SKILL/$(dirname "$f")"
    cp "$f" "$STAGE_SKILL/$f"
done

# 3. ensure dist exists + remove prior package of same version
mkdir -p "$DIST"
rm -f "$PKG_PATH"

# 4. zip into .skill (top-level dir = paper-pdf-figures/)
#    Use python3 zipfile (no external zip dependency).
echo "==> Creating $PKG_NAME"
python3 -c "
import sys, zipfile
from pathlib import Path
stage = Path('$STAGE/paper-pdf-figures')
with zipfile.ZipFile('$PKG_PATH', 'w', zipfile.ZIP_DEFLATED) as z:
    for p in sorted(stage.rglob('*')):
        if p.is_file():
            z.write(p, arcname='paper-pdf-figures/' + str(p.relative_to(stage)))
print('zip ok')
"

# 5. write MANIFEST.txt (file list + sha256)
MANIFEST="$DIST/MANIFEST.txt"
{
    echo "paper-pdf-figures skill package manifest"
    echo "version: $VERSION"
    echo "package: $PKG_NAME"
    echo "created: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo ""
    echo "contents (path + sha256):"
    ( cd "$STAGE/paper-pdf-figures" && find . -type f | sort | while read -r f; do
        # strip leading ./
        rel="${f#./}"
        sha="$(sha256sum "$f" | awk '{print $1}')"
        printf '  %s  %s\n' "$sha" "$rel"
    done )
    echo ""
    echo "install:"
    echo "  unzip $PKG_NAME -d ~/.claude/skills/   # or .claude/skills/ in a project"
    echo "  cd ~/.claude/skills/paper-pdf-figures && bash scripts/install_deps.sh"
    echo "  python3 scripts/check_deps.py          # verify"
} > "$MANIFEST"

echo "==> Done"
echo "    package: $PKG_PATH"
echo "    manifest: $MANIFEST"
echo "    size: $(du -h "$PKG_PATH" | awk '{print $1}')"
echo "    files: $(python3 -c "import zipfile; print(len(zipfile.ZipFile('$PKG_PATH').namelist()))")"
