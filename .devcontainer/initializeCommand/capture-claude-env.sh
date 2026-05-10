#!/bin/bash
# [repo-mixin:devcontainer-claude] Host-side initialization script.
# Runs on the HOST before the container starts (via initializeCommand).
# Sets up the SSH agent socket symlink that devcontainer.json mounts into the container.
# HOST_HOME and HOST_PROJECT_DIR are passed via containerEnv (localEnv:HOME and
# localWorkspaceFolder), so this script no longer writes an env file.
set -e

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
