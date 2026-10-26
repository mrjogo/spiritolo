#!/usr/bin/env bash
# Run a branch against a fresh copy of the live database, on this machine.
#
#   scripts/preview.sh [branch]                 serve it: /ops at http://<host>:8000
#   scripts/preview.sh --smoke [branch]         run the LLM smoke test headless, print the report
#
# Options: --provider P (default deepseek), --model M, --map N (20), --extract N (5),
#          --cap-cents N (50), --port N (8000), --keep (leave the scratch files).
#
# What it does: checks the branch out into a scratch worktree, restores the
# live database from the Litestream replica into a scratch file, and runs the
# app (or `python -m ingredients.smoke`) under `op run --env-file
# scripts/preview.env`, so keys come from 1Password and none touch the disk.
# The served copy signs you in at /api/auth/dev-login with no passkey
# (DEV_LOGIN; plain-http origins only). Nothing is written to the live
# database or its replica: Litestream only restores here, never replicates.
# Ctrl-C (or the end of a smoke run) removes the worktree and the database copy.
#
# Needs on this machine: git, uv, sqlite3, npm (serve mode), litestream, and an `op`
# session that can read the spiritolo-prod vault (OP_SERVICE_ACCOUNT_TOKEN or
# a signed-in CLI).
set -euo pipefail

SMOKE=0 KEEP=0 PORT=8000 PROVIDER=deepseek MODEL="" N_MAP=20 N_EXTRACT=5 CAP=50 BRANCH=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --smoke) SMOKE=1; shift ;;
    --keep) KEEP=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --map) N_MAP="$2"; shift 2 ;;
    --extract) N_EXTRACT="$2"; shift 2 ;;
    --cap-cents) CAP="$2"; shift 2 ;;
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) BRANCH="$1"; shift ;;
  esac
done

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
ENV_FILE="$ROOT/scripts/preview.env"
BRANCH="${BRANCH:-$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)}"
WORK="${PREVIEW_DIR:-$HOME/.cache/spiritolo-preview}/$(echo "$BRANCH" | tr '/' '_')"
SRC="$WORK/src" DB="$WORK/spiritolo.db"

for tool in git uv litestream op sqlite3; do
  command -v "$tool" >/dev/null || { echo "preview: '$tool' is not installed" >&2; exit 1; }
done

cleanup() {
  if [[ "$KEEP" == 1 ]]; then echo "preview: kept $WORK" >&2; return; fi
  git -C "$ROOT" worktree remove --force "$SRC" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "preview: checking out origin/$BRANCH" >&2
git -C "$ROOT" fetch --quiet origin "$BRANCH"
git -C "$ROOT" worktree remove --force "$SRC" 2>/dev/null || true
rm -rf "$WORK" && mkdir -p "$WORK"
git -C "$ROOT" worktree add --quiet --detach "$SRC" "origin/$BRANCH"
(cd "$SRC" && uv sync --quiet --frozen --all-packages)

echo "preview: restoring the live database into $DB" >&2
# The repo's litestream.yml names the replica; its db path is only a key here.
op run --env-file "$ENV_FILE" -- env SPIRITOLO_DB=/data/spiritolo.db LITESTREAM_REGION=auto \
  litestream restore -config "$SRC/litestream.yml" -o "$DB" /data/spiritolo.db
# The copy may hold runs that were queued or running live; park them so the
# preview's executor never spends on them.
sqlite3 "$DB" "update jobs set state = 'cancelled' where state in ('queued', 'running', 'cancelling');"

if [[ "$SMOKE" == 1 ]]; then
  REPORT="$ROOT/data/smoke-$(date -u +%Y%m%dT%H%M%SZ).md"
  mkdir -p "$ROOT/data"
  (cd "$SRC/ingredients" && op run --env-file "$ENV_FILE" -- uv run --no-sync python -m ingredients.smoke \
      --db "$DB" --provider "$PROVIDER" ${MODEL:+--model "$MODEL"} --map "$N_MAP" \
      --extract "$N_EXTRACT" --cap-cents "$CAP" --out "$REPORT")
  echo "preview: report saved to $REPORT" >&2
  exit 0
fi

command -v npm >/dev/null || { echo "preview: 'npm' is not installed" >&2; exit 1; }
echo "preview: building the web app" >&2
(cd "$SRC/web" && npm ci --silent && npm run --silent build)

HOST_NAME="$(hostname)"
echo "preview: open http://$HOST_NAME:$PORT/api/auth/dev-login (Ctrl-C stops and cleans up)" >&2
cd "$SRC"
op run --env-file "$ENV_FILE" -- env SPIRITOLO_DB="$DB" STATIC_DIR="$SRC/web/dist" \
  PUBLIC_ORIGIN="http://$HOST_NAME:$PORT" DEV_LOGIN=1 PORT="$PORT" \
  uv run --no-sync --package spiritolo-app python -m spiritolo
