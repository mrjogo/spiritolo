#!/usr/bin/env bash
set -euo pipefail

SOURCE="$HOME/code-projects/spiritolo/data/scraper.db"
DEST="$HOME/code-projects/backups_spiritolo"

usage() {
  cat <<EOF
Usage: $(basename "$0") <label> [--source PATH] [--dest DIR]

Dump the spiritolo scraper SQLite DB and zstd-compress it to a timestamped file.
Output filename: scraper_YYYYMMDD-HHMMSS_<label>.sql.zst

Arguments:
  <label>             Identifier suffix for the backup (e.g. "before-migration").

Options:
  -s, --source PATH   Source SQLite DB.
                      Default: ~/code-projects/spiritolo/data/scraper.db
  -d, --dest DIR      Destination folder (created if missing).
                      Default: ~/code-projects/backups_spiritolo
  -h, --help          Show this help.
EOF
}

LABEL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--source) SOURCE="$2"; shift 2 ;;
    -d|--dest)   DEST="$2"; shift 2 ;;
    -h|--help)   usage; exit 0 ;;
    --)          shift; break ;;
    -*)          echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    *)
      if [[ -z "$LABEL" ]]; then
        LABEL="$1"; shift
      else
        echo "Unexpected argument: $1" >&2; usage >&2; exit 2
      fi
      ;;
  esac
done

if [[ -z "$LABEL" ]]; then
  echo "Error: label is required." >&2
  usage >&2
  exit 2
fi

if [[ ! -f "$SOURCE" ]]; then
  echo "Error: source DB not found: $SOURCE" >&2
  exit 1
fi

mkdir -p "$DEST"

TS=$(date +%Y%m%d-%H%M%S)
OUT="$DEST/scraper_${TS}_${LABEL}.sql.zst"

echo "Backing up $SOURCE → $OUT"
sqlite3 "$SOURCE" .dump | zstd -15 -T0 --long=27 -o "$OUT"
ls -lh "$OUT"
