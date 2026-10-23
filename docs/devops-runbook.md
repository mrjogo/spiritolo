# DevOps runbook — zero to a running service

One Railway service (`spiritolo`, project `spiritolo-neo`, environment
`staging`) running the FastAPI app + executor over a SQLite file on a volume,
replicated by Litestream to a Railway bucket, with secrets read from a
1Password vault at boot. No Postgres, no separate frontend host, no worker daemon.

**Tools:** `gh` (authed), `railway` (`npm i -g @railway/cli`) or the Railway
dashboard, the 1Password CLI (`op`) for setting up the vault, `pg_restore`
only for the one-time data migration.

Everything the service needs is declared in the repo:
[`railway.json`](../railway.json) (builder, health check, restart policy),
[`Dockerfile`](../Dockerfile), [`scripts/entrypoint.sh`](../scripts/entrypoint.sh),
[`litestream.yml`](../litestream.yml) and [`secrets.env`](../secrets.env)
(1Password references). The steps below are the parts that live outside the
repo: the Railway resources, the vault, and the few plain variables.

---

## 1. Railway project, service, volume

1. Dashboard → **New project** → **GitHub Repo** → `mrjogo/spiritolo`. Name the
   project `spiritolo-neo`, the service `spiritolo`, and rename the
   environment to `staging`.
2. Service → **Settings → Source**: set the **deploy branch** (during the
   changeover: `claude/project-thread-0e8m4j`; afterwards `main`). Leave
   build/start commands empty — `railway.json` declares the Dockerfile builder
   and the entrypoint is the start command.
3. Service → **Volumes** → add a volume mounted at **`/data`** (name
   `spiritolo-volume`). The database lives at `/data/spiritolo.db`.
4. Service → **Settings → Networking** → **Generate domain** on port `8000`.
   This is the `PUBLIC_ORIGIN` (currently `https://spiritolo-staging.up.railway.app`).

The health check (`/api/health`, 120 s), single replica and `ON_FAILURE`
restart policy come from `railway.json`; the API also accepts them via
`serviceInstanceUpdate` if you prefer to set them explicitly.

## 2. Buckets

Two S3-compatible Railway buckets (project-token API access cannot create
buckets, so this is a dashboard step):

- **Litestream replica** — new bucket, e.g. `spiritolo-litestream`. Litestream
  writes `s3://<bucket>/spiritolo/…`.
- **HTML corpus** — the existing `spiritolo-corpus` bucket (page HTML the
  extract stage reads). It currently lives in the old Railway project; either
  reuse it (put its credentials in the vault) or create a new one and copy the
  objects over.

For each bucket, open **Credentials** once and put the access key id + secret
into the vault (step 3). Do **not** add them to the service as variables.

## 3. 1Password vault

Create a vault for the service and the items `secrets.env` references (names
are the spec defaults — if yours differ, edit `secrets.env`, not the vault):

| Reference | Holds |
|---|---|
| `op://spiritolo/app/session-secret` | a long random string (`openssl rand -base64 48`) |
| `op://spiritolo/llm/anthropic-api-key`, `…/openai-api-key`, `…/deepseek-api-key` | hosted LLM keys (omit a line in `secrets.env` for a provider you don't use) |
| `op://spiritolo/litestream-bucket/access-key-id`, `…/secret-access-key` | the Litestream bucket credentials |
| `op://spiritolo/corpus-bucket/access-key-id`, `…/secret-access-key` | the corpus bucket credentials |

Then create a **service account** (1Password → Developer → Service accounts)
with read access to that vault only, and copy its token: that is
`OP_SERVICE_ACCOUNT_TOKEN`.

## 4. Service variables

Plain (non-secret) variables on the service:

```
PUBLIC_ORIGIN=https://spiritolo-staging.up.railway.app
SPIRITOLO_DB=/data/spiritolo.db
STATIC_DIR=/app/web/dist
RUN_EXECUTOR=1
LOG_LEVEL=INFO
LITESTREAM_REPLICA_URL=s3://<litestream bucket>/spiritolo
LITESTREAM_ENDPOINT=<litestream bucket S3 endpoint>
AWS_ENDPOINT_URL=<corpus bucket S3 endpoint>
AWS_S3_BUCKET_NAME=spiritolo-corpus
AWS_DEFAULT_REGION=<corpus bucket region>
AWS_S3_URL_STYLE=path
```

Optional: `OLLAMA_BASE_URL=http://barbot:11434` + `TAILSCALE_AUTHKEY` (a
Tailscale OAuth client secret tagged `tag:worker`) if a run should use a
tailnet Ollama; the entrypoint only starts tailscaled when the key is present.

One **sealed** variable: `OP_SERVICE_ACCOUNT_TOKEN`. With it set the entrypoint
runs everything under `op run`, so every `secrets.env` line resolves; without
it the service boots secret-less (sessions reset on restart, hosted LLM tiers
unavailable, Litestream skipped if its URL is unset).

Setting any of these from the API is `variableCollectionUpsert` with
`skipDeploys: true`, then one redeploy.

## 5. RecipeGF

`recipegf` is a git dependency pinned to `mrjogo/RecipeGF@v0.4.0`. If that repo
is private, the image build needs a `RECIPEGF_TOKEN` **build argument**
(fine-grained PAT, Contents: read on that repo only) — set it as a service
variable; the Dockerfile reads it as `ARG` and never bakes it into the image —
and `python-ci.yml` needs the same value as a repo secret. Making the repo
public removes both.

## 6. First deploy and passkey setup

1. Push to the deploy branch (or **Deploy** in the dashboard). Watch the build,
   then `GET https://<domain>/api/health` → `{"ok": true, "executor": {...}}`.
2. Open `https://<domain>/login`. With no operators yet the page offers
   **first-time setup**: pick a handle, register a passkey → you are the admin.
   From then on registration needs a signed-in operator.
3. Seal `OP_SERVICE_ACCOUNT_TOKEN` (if you deployed without it first) and
   redeploy; the logs should show `op run` resolving `secrets.env` and
   Litestream starting replication.

## 7. Data migration (one time)

The staging Supabase data is exported with the *Backup staging database*
GitHub Action, converted with `scripts/pg_to_sqlite`, and loaded through
**/ops → Import**. Full steps in [migration.md](migration.md).

## 8. Smoke the loop

1. `/ops → Runs` → create a `parse-ingredients` run on local `ollama` (free),
   add a handful of recipes, **Start**.
2. Expect: items go `pending → applied`, `recipe_ingredients` rows appear, the
   audit log records each mutation with `actor_kind = worker`, and
   `/api/ops/executor` shows the run id while it is live.
3. Railway logs: `spiritolo up: db=/data/spiritolo.db …`, Litestream `sync`
   lines after the writes.

---

## CD wiring

| Path changed | Trigger | Effect |
|---|---|---|
| `app/**`, `common/**`, `ingredients/**`, `scripts/**` (PR → main) | `python-ci.yml` | pytest gates for every workspace member (SQLite, no services) |
| `web/**` (PR → main) | `web-ci.yml` | Vitest gate |
| deploy artifacts (PR → main) | `workflows-ci.yml` | shape tests over Dockerfile, entrypoint, railway.json, litestream.yml, secrets.env, this runbook |
| anything (push → deploy branch) | Railway GitHub App | builds the Dockerfile, health-checks `/api/health`, swaps the deployment |
