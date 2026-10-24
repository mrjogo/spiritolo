#!/usr/bin/env bash
# Service entrypoint. In order:
#   1. (optional) Tailscale in userspace mode, only when TAILSCALE_AUTHKEY is set
#      — it is the one route to a tailnet Ollama for the free local LLM tier.
#   2. Restore the SQLite file from the Litestream replica if the volume is
#      empty (a fresh volume, or a volume swap) — a no-op when the file exists.
#   3. Hand off to Litestream, which replicates the database continuously and
#      runs uvicorn as its child, so the process tree stays one PID 1 chain.
#
# Secrets (session secret, LLM keys, the Tailscale key) are resolved by
# `op run` from 1Password at boot when OP_SERVICE_ACCOUNT_TOKEN is present:
# secrets.env holds only op:// references. Bucket credentials arrive as Railway
# reference variables, so they are already in the environment. Without the token (local docker
# runs, tests) the process starts with whatever the environment already has.
set -euo pipefail

DB_PATH="${SPIRITOLO_DB:-/data/spiritolo.db}"
mkdir -p "$(dirname "$DB_PATH")"

# 0. A staged import (/ops → Import, then Apply) replaces the live database.
#    The app exits to get here, so this runs before Litestream or uvicorn
#    have the file open; Litestream then starts a new generation for it.
if [ -f "$DB_PATH.import" ]; then
  echo "entrypoint: applying staged database import" >&2
  rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"
  mv "$DB_PATH.import" "$DB_PATH"
  rm -f "$DB_PATH.import.json"
fi

run_with_secrets() {
  if [ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
    exec op run --env-file /app/secrets.env --no-masking -- "$@"
  else
    echo "entrypoint: OP_SERVICE_ACCOUNT_TOKEN not set; running without 1Password secrets" >&2
    exec "$@"
  fi
}

# 1–3 run under `op run` so TAILSCALE_AUTHKEY (a vault item) resolves too.
run_with_secrets bash -c '
  set -euo pipefail
  # Railway attaches a bucket to the service as BUCKET_* reference variables.
  # Derive the Litestream settings from them unless set explicitly.
  if [ -z "${LITESTREAM_REPLICA_URL:-}" ] && [ -n "${BUCKET_NAME:-}" ]; then
    export LITESTREAM_REPLICA_URL="s3://${BUCKET_NAME}/spiritolo"
    export LITESTREAM_ENDPOINT="${LITESTREAM_ENDPOINT:-${BUCKET_ENDPOINT:-}}"
    export LITESTREAM_REGION="${LITESTREAM_REGION:-${BUCKET_REGION:-us-east-1}}"
    export LITESTREAM_ACCESS_KEY_ID="${LITESTREAM_ACCESS_KEY_ID:-${BUCKET_ACCESS_KEY_ID:-}}"
    export LITESTREAM_SECRET_ACCESS_KEY="${LITESTREAM_SECRET_ACCESS_KEY:-${BUCKET_SECRET_ACCESS_KEY:-}}"
  fi
  export LITESTREAM_REGION="${LITESTREAM_REGION:-us-east-1}"
  # 1. Tailscale (optional): only when an auth key is present.
  if [ -n "${TAILSCALE_AUTHKEY:-}" ]; then
    /usr/local/bin/tailscaled --tun=userspace-networking --socks5-server=localhost:1055 --state=mem: &
    /usr/local/bin/tailscale up \
      --authkey="${TAILSCALE_AUTHKEY}?ephemeral=true&preauthorized=true" \
      --advertise-tags=tag:worker --hostname="spiritolo" --accept-routes
    export TS_LOCAL_PROXY="socks5://localhost:1055"
  fi
  if [ -n "${LITESTREAM_REPLICA_URL:-}" ]; then
    if [ ! -f "'"$DB_PATH"'" ]; then
      echo "entrypoint: no database on the volume; restoring from the replica if one exists" >&2
      litestream restore -if-replica-exists -config /etc/litestream.yml "'"$DB_PATH"'" || true
    fi
    exec litestream replicate -config /etc/litestream.yml \
      -exec "uv run --no-sync --package spiritolo-app uvicorn spiritolo.main:app --factory --host 0.0.0.0 --port ${PORT:-8000}"
  else
    echo "entrypoint: LITESTREAM_REPLICA_URL not set; running without replication" >&2
    exec uv run --no-sync --package spiritolo-app uvicorn spiritolo.main:app --factory --host 0.0.0.0 --port "${PORT:-8000}"
  fi
'
