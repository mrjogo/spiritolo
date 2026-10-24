#!/usr/bin/env bash
# Runs the API process (uvicorn via uv) as the child of Litestream's -exec.
#
# Litestream reports "failed to run ... exit status 143" when its child is
# ended by SIGTERM, which is exactly what happens on every Railway redeploy
# as the old container is stopped — and Railway then flags that deployment
# as crashed and emails about it. This wrapper forwards TERM/INT to uvicorn,
# waits for it, and turns the SIGTERM exit (143) into a clean 0. Every other
# exit code passes through unchanged, in particular 3, which the import
# feature uses to ask for a restart (see spiritolo.importdb.schedule_exit).
set -u

uv run --no-sync --package spiritolo-app uvicorn spiritolo.main:app --factory \
  --host 0.0.0.0 --port "${PORT:-8000}" &
child=$!

forward() { kill -TERM "$child" 2>/dev/null; }
trap forward TERM INT

wait "$child"; rc=$?
# `wait` returns early when a trapped signal arrives; wait again for the real exit.
while kill -0 "$child" 2>/dev/null; do
  wait "$child"; rc=$?
done

if [ "$rc" -eq 143 ]; then
  echo "run-app: uvicorn stopped by SIGTERM (shutdown), exiting 0" >&2
  rc=0
fi
exit "$rc"
