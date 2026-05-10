#!/bin/bash
# [repo-mixin:devcontainer-claude] Host-side initialization script.
# Runs on the HOST before the container starts (via initializeCommand).
# Captures host-side state that the container needs for path bridging and auth.
set -e

# Build env file for the container (passed via runArgs --env-file).
# This file is gitignored. It captures values that only exist on the host.
ENV_FILE=".devcontainer/.env.devcontainer"
: > "$ENV_FILE"

# Capture host project directory for Claude Code history path bridging.
# Claude keys conversation history by absolute path, which differs between host and container.
echo "HOST_PROJECT_DIR=$PWD" >> "$ENV_FILE"

# Forward GitHub CLI auth token into the container.
# gh reads GH_TOKEN natively — no login step needed inside the container.
if command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
    echo "GH_TOKEN=$(gh auth token 2>/dev/null)" >> "$ENV_FILE"
fi

# Forward the host's SSH agent socket into a stable location for devcontainer.json to mount.
# The mount source uses ${localEnv:XDG_RUNTIME_DIR:/run}/devcontainer-ssh-agent.sock:
#   - Linux: XDG_RUNTIME_DIR is set (e.g., /run/user/1000), user-writable, Docker resolves on host
#   - macOS: XDG_RUNTIME_DIR is unset, falls back to /run, Docker resolves in its LinuxKit VM
#     (because /run is outside Docker Desktop's host file-sharing set)
AGENT_SOCK="devcontainer-ssh-agent.sock"
if [ -n "$SSH_AUTH_SOCK" ]; then
    if [ "$(uname)" = "Darwin" ]; then
        # Create symlink inside Docker Desktop's VM at /run/, pointing to the
        # VM-side SSH agent relay that Docker Desktop maintains.
        docker run --rm -v /run:/vmrun alpine \
            sh -c "ln -sf /run/host-services/ssh-auth.sock /vmrun/$AGENT_SOCK && chmod 777 /vmrun/host-services/ssh-auth.sock"
    else
        # Linux: symlink in the user-writable XDG_RUNTIME_DIR.
        ln -sf "$SSH_AUTH_SOCK" "${XDG_RUNTIME_DIR:?XDG_RUNTIME_DIR must be set}/$AGENT_SOCK"
    fi
fi
