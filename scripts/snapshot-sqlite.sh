#!/usr/bin/env bash
# Take a compact, self-contained snapshot of a live SQLite database with
# `VACUUM INTO`, which is safe against a WAL database that readers and the
# writer are using. Litestream is the continuous backup; this is the cold copy.
#
#   scripts/snapshot-sqlite.sh /data/spiritolo.db /data/snapshots/spiritolo-$(date -u +%Y%m%dT%H%M%SZ).db
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $(basename "$0") <source.db> <snapshot.db>" >&2
  exit 2
fi
SRC="$1"; OUT="$2"
[[ -f "$SRC" ]] || { echo "no such database: $SRC" >&2; exit 1; }
[[ -e "$OUT" ]] && { echo "refusing to overwrite $OUT" >&2; exit 1; }
mkdir -p "$(dirname "$OUT")"

python3 - "$SRC" "$OUT" <<'PY'
import sqlite3, sys
src, out = sys.argv[1], sys.argv[2]
conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
try:
    conn.execute("vacuum into ?", (out,))
finally:
    conn.close()
check = sqlite3.connect(out)
try:
    ok = check.execute("pragma integrity_check").fetchone()[0]
finally:
    check.close()
if ok != "ok":
    sys.exit(f"snapshot failed integrity_check: {ok}")
print(f"snapshot written: {out}")
PY
