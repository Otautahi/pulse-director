#!/usr/bin/env bash
# Copies a verified candidate to its OWN workspace; never modifies installed services.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="/home/otautahi/Projects/PulseDirector/development/v4.6-unified"
[[ -f "$SRC/edge_dashboard.py" && -f "$SRC/tests/test_unified_profiles_v46.py" ]] || { echo 'Incomplete candidate' >&2; exit 1; }
[[ ! -e "$DEST" ]] || { echo "REFUSED: staging destination already exists: $DEST" >&2; exit 1; }
[[ "$SRC" != "$DEST" ]] || { echo 'Refused source=destination' >&2; exit 1; }
python3 -m compileall -q "$SRC"
(cd "$SRC" && python3 -m unittest discover -s tests -q)
mkdir -p "$(dirname "$DEST")"
install -d -m 0700 "$DEST"
cp -a "$SRC/edge_dashboard.py" "$SRC/edge2_director.py" "$SRC/edge2_https_pairing.py" "$SRC/edge2_pairing_ui.py" "$SRC/https-standard-probe" "$SRC/tests" "$SRC/README_V46_UNIFIED.md" "$SRC/V46_SECURITY_AND_TESTING.md" "$SRC/.gitignore" "$DEST/"
find "$DEST" -type d -name __pycache__ -prune -exec rm -rf {} +
echo "Staged to $DEST"
echo 'No systemd, cloud credentials, Pi-hole, WireGuard, or other services changed.'
echo "To verify: cd '$DEST' && python3 -m unittest discover -s tests -q"
