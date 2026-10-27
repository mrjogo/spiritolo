#!/usr/bin/env bash
# Download a copy of the live database from its Litestream replica.
#
#   scripts/fetch-snapshot.sh [out.db]       default: data/live-snapshot.db in the main checkout
#
# The cold-start path for scripts/preview.sh, which only ever reads a local
# snapshot; once /ops can hand out a download, prefer that. Run it where you
# are willing to hold the replica bucket's credentials (your laptop), then
# copy the file to the preview machine. Restore only: nothing is written to the
# replica.
#
# Credentials: LITESTREAM_BUCKET / _ENDPOINT / _ACCESS_KEY_ID /
# _SECRET_ACCESS_KEY from the environment if set; otherwise resolved by
# `op run --env-file scripts/snapshot.env`. Needs git and litestream (and op
# for the second form).
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
MAIN="$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")"
OUT="${1:-$MAIN/data/live-snapshot.db}"
[[ -e "$OUT" ]] && { echo "fetch-snapshot: refusing to overwrite $OUT" >&2; exit 1; }
command -v litestream >/dev/null || { echo "fetch-snapshot: 'litestream' is not installed" >&2; exit 1; }
mkdir -p "$(dirname "$OUT")"

# litestream.yml names the replica; its db path is only a key here.
restore=(env SPIRITOLO_DB=/data/spiritolo.db LITESTREAM_REGION="${LITESTREAM_REGION:-auto}"
  litestream restore -config "$ROOT/litestream.yml" -o "$OUT" /data/spiritolo.db)
if [[ -n "${LITESTREAM_ACCESS_KEY_ID:-}" ]]; then
  "${restore[@]}"
else
  op run --env-file "$ROOT/scripts/snapshot.env" -- "${restore[@]}"
fi
echo "fetch-snapshot: wrote $OUT ($(du -h "$OUT" | cut -f1))" >&2
