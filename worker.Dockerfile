# The pipeline worker image: the uv workspace + Tailscale in userspace mode.
#
# Runs as a single unprivileged Railway process (no inbound port). Tailscale is
# baked in as static binaries and started in userspace-networking mode by the
# entrypoint, so the container needs no extra network capability and no tunnel
# device — the only way to reach barbot's Ollama from an unprivileged container.

FROM python:3.11-slim AS base

# git is needed to clone the recipegf git dependency during `uv sync`; curl to
# fetch the uv installer. No iptables / TUN tooling: networking is userspace.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# uv (pinned by the installer script).
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Tailscale static binaries, copied from the official image. Userspace mode
# means these run unprivileged — no elevated network capability, no tunnel
# device.
COPY --from=docker.io/tailscale/tailscale:stable /usr/local/bin/tailscaled /usr/local/bin/tailscaled
COPY --from=docker.io/tailscale/tailscale:stable /usr/local/bin/tailscale  /usr/local/bin/tailscale

WORKDIR /app

# Copy the whole workspace so uv resolves every path/workspace member + the
# frozen lockfile.
COPY pyproject.toml uv.lock ./
COPY common/ common/
COPY ingredients/ ingredients/
COPY scraper/ scraper/
COPY scripts/ scripts/

# recipegf is a private git dependency. RECIPEGF_TOKEN is a BUILD ARG (never a
# runtime ENV): it authenticates the clone during `uv sync` and is not baked
# into the running image. If the repo is public the clone succeeds without it.
ARG RECIPEGF_TOKEN=
RUN if [ -n "$RECIPEGF_TOKEN" ]; then \
      git config --global \
        url."https://x-access-token:${RECIPEGF_TOKEN}@github.com/".insteadOf \
        "https://github.com/"; \
    fi \
 && uv sync --frozen --package spiritolo-ingredients \
 && git config --global --unset-all url."https://x-access-token:${RECIPEGF_TOKEN}@github.com/".insteadOf || true

COPY scripts/worker-entrypoint.sh /usr/local/bin/worker-entrypoint.sh
RUN chmod +x /usr/local/bin/worker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/worker-entrypoint.sh"]
