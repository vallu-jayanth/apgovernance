#!/bin/sh
# Re-download panchayat data from eGramSwaraj and rebuild the site.
# YEAR = latest finished financial year, PLANYEAR = its first year.
set -e
cd "$(dirname "$0")/.."
YEAR=${YEAR:-2025-2026}
PLANYEAR=${PLANYEAR:-2025}
TMP=$(mktemp -d)
python3 -I scripts/fetch_gp.py "$YEAR" "$TMP/gp.csv"
python3 -I scripts/fetch_geo.py "$TMP/gp.csv" "$PLANYEAR" "$TMP/geo"
# only replace data once both downloads succeeded
cp "$TMP/gp.csv" docs/data/gp.csv
rm -f docs/geo/*.json && cp "$TMP"/geo/*.json docs/geo/
python3 scripts/build_site.py
