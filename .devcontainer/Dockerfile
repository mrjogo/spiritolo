# [repo-mixin:devcontainer-python-uv] Python base image.
# Pins Python 3.12 via the upstream Microsoft devcontainer image (Debian
# bookworm, vscode user preinstalled). Change the tag to pin a different
# Python version (e.g., :3.11, :3.13).
FROM mcr.microsoft.com/devcontainers/python:3.12
# [/repo-mixin:devcontainer-python-uv]

# [repo-mixin:devcontainer-claude] Install tmux for session persistence.
# Claude Code sessions survive IDE disconnects when run inside tmux.
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    tmux \
    && rm -rf /var/lib/apt/lists/*

# [repo-mixin:devcontainer-python-uv] Verify non-root user exists before switching.
# Fails fast if a custom base image doesn't include the vscode user.
RUN id vscode > /dev/null 2>&1 || { echo "Error: user 'vscode' does not exist in base image"; exit 1; }
USER vscode
# [/repo-mixin:devcontainer-python-uv]

# [repo-mixin:devcontainer-claude] Install Claude Code standalone.
# Installs to ~/.local/bin which is added to PATH via devcontainer.json remoteEnv.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN curl -fsSL https://claude.ai/install.sh | bash

# [repo-mixin:devcontainer-python-uv] Install uv (Astral's Python package/project manager).
# Installs to ~/.local/bin, which the Microsoft python devcontainer already has on PATH.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
# [/repo-mixin:devcontainer-python-uv]

# [repo-mixin:devcontainer-claude] Readline config for up/down arrow history prefix search
COPY --chown=vscode .inputrc /tmp/.inputrc
RUN cp /tmp/.inputrc ~/
# [/repo-mixin:devcontainer-claude]
