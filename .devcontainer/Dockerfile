# Base image — adapt to your stack (python:3.12, node:20, etc.)
FROM mcr.microsoft.com/devcontainers/base:ubuntu

# [repo-mixin:devcontainer-claude] Install tmux for session persistence.
# Claude Code sessions survive IDE disconnects when run inside tmux.
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    tmux \
    && rm -rf /var/lib/apt/lists/*

# Switch to non-root container user — adapt username if your base image uses a different user.
# Verify the user exists to fail fast if the base image doesn't match expectations.
RUN id vscode > /dev/null 2>&1 || { echo "Error: user 'vscode' does not exist in base image"; exit 1; }
USER vscode

# [repo-mixin:devcontainer-claude] Install Claude Code standalone.
# Installs to ~/.local/bin which is added to PATH via devcontainer.json remoteEnv.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN curl -fsSL https://claude.ai/install.sh | bash

# [repo-mixin:devcontainer-claude] Readline config for up/down arrow history prefix search
COPY --chown=vscode .inputrc /tmp/.inputrc
RUN cp /tmp/.inputrc ~/
# [/repo-mixin:devcontainer-claude]
