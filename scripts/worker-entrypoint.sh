#!/usr/bin/env bash
# Worker container entrypoint: bring up Tailscale in userspace mode, join the
# tailnet, then hand off (exec) to the worker as PID 1.
#
# Only barbot's Ollama (the free local provider) needs the tailnet; hosted APIs
# take the direct route. So this exports TS_LOCAL_PROXY (which the local
# provider client reads) but deliberately does NOT export a global ALL_PROXY /
# HTTPS_PROXY — that would tunnel every hosted API call through barbot's uplink.
set -euo pipefail

# 1. tailscaled in userspace-networking mode with a local SOCKS5 proxy on :1055.
#    Ephemeral in-memory state (--state=mem:) so the node re-authenticates each
#    boot and self-cleans on exit; no NET_ADMIN, no /dev/net/tun.
/usr/local/bin/tailscaled \
  --tun=userspace-networking \
  --socks5-server=localhost:1055 \
  --state=mem: &

# 2. Join the tailnet with an ephemeral, pre-approved auth key. The :? guard
#    (with set -u) fails fast if the key is missing rather than booting a worker
#    that can never reach barbot.
/usr/local/bin/tailscale up \
  --authkey="${TAILSCALE_AUTHKEY:?TAILSCALE_AUTHKEY required}" \
  --hostname="spiritolo-worker" \
  --accept-routes

# 3. Point the local provider client at the tailnet proxy. Hosted providers
#    ignore this and stay on the direct route.
export TS_LOCAL_PROXY="socks5://localhost:1055"

# 4. Hand off to the worker as PID 1 so Railway's stop/restart signals reach it.
exec uv run --package spiritolo-ingredients python -m ingredients.worker
