#!/usr/bin/env bash
# Forward Supabase-local ports from host.docker.internal to 127.0.0.1
# inside the devcontainer so that `supabase start`'s health checks
# (which probe 127.0.0.1) reach the actual Supabase containers running
# on the host under docker-outside-of-docker.
#
# Each forwarder runs in its own supervised loop so a transient socat
# exit (idle, peer reset) doesn't leave a port unbridged.
#
# Logs go to $HOME/.supabase-portforward.log.

set -u

PORTS=(54320 54321 54322 54323 54324 54327 54329)
LOG_FILE="$HOME/.supabase-portforward.log"
TARGET_HOST="host.docker.internal"

# Kill any forwarders from a prior start.
pkill -f "socat.*TCP-LISTEN:543" >/dev/null 2>&1 || true
# Give the OS a beat to release the sockets before we rebind.
sleep 0.2

for port in "${PORTS[@]}"; do
    setsid bash -c "
        while true; do
            /usr/bin/socat \
                'TCP-LISTEN:${port},bind=127.0.0.1,reuseaddr,fork' \
                'TCP:${TARGET_HOST}:${port}' \
                >> '${LOG_FILE}' 2>&1
            sleep 1
        done
    " </dev/null >/dev/null 2>&1 &
done

echo "Supabase port forwarders started: ${PORTS[*]} → ${TARGET_HOST}"
