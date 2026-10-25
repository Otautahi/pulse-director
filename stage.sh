#!/usr/bin/env bash
# Portable source-only staging: no services, credentials, system configuration.
set -Eeuo pipefail
umask 077
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
DEST="${PD_STAGE_DEST:-$HOME/Projects/PulseDirector/development/v4.6-unified-stage}"
[[ "$(id -u)" != 0 ]] || { echo 'REFUSED: do not stage as root.' >&2; exit 1; }
[[ -f "$SRC/edge_dashboard.py" && -f "$SRC/tests/test_unified_profiles_v46.py" && -f "$SRC/docs/V46_SECURITY_AND_TESTING.md" && -f "$SRC/README.md" ]] || { echo 'Incomplete candidate'; exit 1; }
[[ ! -e "$DEST" && ! -L "$DEST" ]] || { echo "REFUSED: stage destination exists: $DEST" >&2; exit 1; }
# Restrict output to a source-independent development subtree and reject symlink ancestors.
python3 - "$DEST" <<'PY'
import pathlib,sys
p=pathlib.Path(sys.argv[1]).expanduser().absolute()
root=(pathlib.Path.home()/'Projects/PulseDirector/development').absolute()
if p.parent != root or not p.name.startswith('v4.6-'):
    raise SystemExit('REFUSED: stage destination must be a new v4.6-* sibling within ~/Projects/PulseDirector/development')
for part in [root,root.parent,root.parent.parent,root.parent.parent.parent]:
    if part.is_symlink(): raise SystemExit('REFUSED: symlink in development path')
PY
(cd "$SRC" && python3 -m unittest discover -s tests -q)
mkdir -p "$(dirname "$DEST")"
TMP="$(mktemp -d "$(dirname "$DEST")/.v46-stage.XXXXXXXX")"
trap '[[ ! -d "$TMP" ]] || rm -rf -- "$TMP"' EXIT
# Whitelist *source* files: never copy QR images, pairing configs, token files or logs.
cp -- "$SRC/edge_dashboard.py" "$SRC/edge2_director.py" "$SRC/edge2_https_pairing.py" "$SRC/edge2_pairing_ui.py" "$SRC/README.md" "$SRC/.gitignore" "$TMP/"
mkdir -p "$TMP/https-standard-probe" "$TMP/tests" "$TMP/docs"
cp -- "$SRC/https-standard-probe/https_probe.py" "$TMP/https-standard-probe/"
cp -- "$SRC"/tests/test_*.py "$TMP/tests/"
cp -- "$SRC/docs/V46_SECURITY_AND_TESTING.md" "$TMP/docs/"
[[ ! -f "$SRC/docs/V46_DEV_INSTALL.md" ]] || cp -- "$SRC/docs/V46_DEV_INSTALL.md" "$TMP/docs/"
# No runtime credentials, identities or cloud-enable flags are copied.
mv -- "$TMP" "$DEST"
chmod 700 "$DEST"
trap - EXIT
printf 'Candidate staged to %s\nNo systemd, cloud credentials, or production services changed.\n' "$DEST"
