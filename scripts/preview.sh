#!/usr/bin/env bash
# Run a branch against a copy of a live-database snapshot, on this machine.
#
#   scripts/preview.sh [branch]                 serve it: /ops at http://<host>:8000
#   scripts/preview.sh --smoke [branch]         run the LLM smoke test headless, print the report
#
# Options: --snapshot FILE (data/live-snapshot.db), --corpus DIR (data/html),
#          --provider P (default deepseek), --model M, --map N (20), --extract N (5),
#          --cap-cents N (50), --port N (8000), --keep (leave the scratch files).
#          data/ is the main checkout's, also when this runs from a worktree.
#
# What it does: checks the branch out into a scratch worktree, copies the
# snapshot (scripts/fetch-snapshot.sh makes one) into a scratch file, and runs
# the app (or `python -m ingredients.smoke`) on that copy. Page HTML for
# extract-recipe comes from the scraper's local cache (--corpus, indexed by the
# scraper.db beside it), not the bucket. This machine holds no prod
# credentials: only the LLM keys in scripts/preview.env, via `op run`, or a
# plain KEY=value file named by PREVIEW_ENV_FILE. The served copy signs you in
# at /api/auth/dev-login with no passkey (DEV_LOGIN; plain-http origins only).
# Ctrl-C (or the end of a smoke run) removes the worktree and the database copy;
# the snapshot itself is never written.
#
# Needs on this machine: git, uv, sqlite3, npm (serve mode), and op unless
# PREVIEW_ENV_FILE holds plain values.
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
MAIN="$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")"

SMOKE=0 KEEP=0 PORT=8000 PROVIDER=deepseek MODEL="" N_MAP=20 N_EXTRACT=5 CAP=50 BRANCH=""
SNAPSHOT="$MAIN/data/live-snapshot.db" CORPUS="$MAIN/data/html"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --smoke) SMOKE=1; shift ;;
    --keep) KEEP=1; shift ;;
    --snapshot) SNAPSHOT="$2"; shift 2 ;;
    --corpus) CORPUS="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --map) N_MAP="$2"; shift 2 ;;
    --extract) N_EXTRACT="$2"; shift 2 ;;
    --cap-cents) CAP="$2"; shift 2 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) BRANCH="$1"; shift ;;
  esac
done

ENV_FILE="${PREVIEW_ENV_FILE:-$ROOT/scripts/preview.env}"
BRANCH="${BRANCH:-$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)}"
WORK="${PREVIEW_DIR:-$HOME/.cache/spiritolo-preview}/$(echo "$BRANCH" | tr '/' '_')"
SRC="$WORK/src" DB="$WORK/spiritolo.db"

for tool in git uv sqlite3; do
  command -v "$tool" >/dev/null || { echo "preview: '$tool' is not installed" >&2; exit 1; }
done
[[ -f "$SNAPSHOT" ]] || { echo "preview: no snapshot at $SNAPSHOT (scripts/fetch-snapshot.sh)" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "preview: no env file at $ENV_FILE" >&2; exit 1; }
if [[ "$N_EXTRACT" != 0 || "$SMOKE" == 0 ]]; then
  [[ -d "$CORPUS" && -f "$(dirname "$CORPUS")/scraper.db" ]] \
    || { echo "preview: no HTML cache at $CORPUS (with scraper.db beside it)" >&2; exit 1; }
fi

# Run "$@" with the env file's keys: through `op run` when it holds 1Password
# references, else by sourcing its plain values in a subshell.
with_secrets() {
  if grep -q 'op://' "$ENV_FILE"; then
    command -v op >/dev/null || { echo "preview: 'op' is not installed" >&2; return 1; }
    op run --env-file "$ENV_FILE" -- "$@"
  else
    (set -a; . "$ENV_FILE"; set +a; exec "$@")
  fi
}

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

echo "preview: copying $SNAPSHOT into $DB" >&2
sqlite3 "$SNAPSHOT" ".backup '$DB'"
# The snapshot may hold runs that were queued or running live; park them so the
# preview's executor never spends on them.
sqlite3 "$DB" "update jobs set state = 'cancelled' where state in ('queued', 'running', 'cancelling');"
export CORPUS_DIR="$CORPUS"

if [[ "$SMOKE" == 1 ]]; then
  REPORT="$MAIN/data/smoke-$(date -u +%Y%m%dT%H%M%SZ).md"
  mkdir -p "$MAIN/data"
  (cd "$SRC/ingredients" && with_secrets uv run --no-sync python -m ingredients.smoke \
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
with_secrets env SPIRITOLO_DB="$DB" STATIC_DIR="$SRC/web/dist" \
  PUBLIC_ORIGIN="http://$HOST_NAME:$PORT" DEV_LOGIN=1 PORT="$PORT" \
  uv run --no-sync --package spiritolo-app python -m spiritolo
