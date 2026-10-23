# The Spiritolo service image: one process serving the API, the ops console,
# the built React app and the in-process pipeline executor, over a SQLite file
# on a Railway volume that Litestream replicates to a bucket.
#
# Stage 1 builds the web app; stage 2 is the Python runtime. Secrets are not
# baked in: the entrypoint reads them from 1Password at boot (see secrets.env).

# ---------------------------------------------------------------- web build
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ------------------------------------------------------------- python runtime
FROM python:3.11-slim AS runtime

# git clones the recipegf git dependency during `uv sync`; curl fetches uv.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Litestream (SQLite replication), the 1Password CLI (secrets at boot) and
# Tailscale (userspace mode, only to reach a tailnet Ollama) as static binaries.
COPY --from=docker.io/litestream/litestream:0.3.13 /usr/local/bin/litestream /usr/local/bin/litestream
COPY --from=docker.io/1password/op:2 /usr/local/bin/op /usr/local/bin/op
COPY --from=docker.io/tailscale/tailscale:stable /usr/local/bin/tailscaled /usr/local/bin/tailscaled
COPY --from=docker.io/tailscale/tailscale:stable /usr/local/bin/tailscale  /usr/local/bin/tailscale

WORKDIR /app

# The uv workspace: lockfile first for layer caching, then the members.
COPY pyproject.toml uv.lock ./
COPY common/ common/
COPY ingredients/ ingredients/
COPY scraper/ scraper/
COPY scripts/ scripts/
COPY app/ app/

# recipegf is a private git dependency. RECIPEGF_TOKEN is a BUILD ARG (never a
# runtime ENV): it authenticates the clone during `uv sync` and is not baked
# into the running image. If the repo is public the clone succeeds without it.
ARG RECIPEGF_TOKEN=
RUN if [ -n "$RECIPEGF_TOKEN" ]; then \
      git config --global \
        url."https://x-access-token:${RECIPEGF_TOKEN}@github.com/".insteadOf \
        "https://github.com/"; \
    fi \
 && uv sync --frozen --no-dev --package spiritolo-app \
 && (git config --global --unset-all url."https://x-access-token:${RECIPEGF_TOKEN}@github.com/".insteadOf || true)

COPY --from=web /web/dist /app/web/dist
COPY litestream.yml /etc/litestream.yml
COPY secrets.env /app/secrets.env
COPY scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV SPIRITOLO_DB=/data/spiritolo.db \
    STATIC_DIR=/app/web/dist \
    PORT=8000 \
    PYTHONUNBUFFERED=1
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
