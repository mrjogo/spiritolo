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
buckets, so this is a dashboard step). Their credentials never go in the
vault: attach each bucket to the service with **Bucket → Credentials → Add to
service**, which injects the keys and endpoint as **reference variables**
(auto-rotating, never visible to Claude).

- **Litestream replica** — `spiritolo-litestream`. Litestream reads
  `LITESTREAM_ACCESS_KEY_ID`, `LITESTREAM_SECRET_ACCESS_KEY`,
  `LITESTREAM_ENDPOINT` and `LITESTREAM_REPLICA_URL`
  (`s3://spiritolo-litestream/spiritolo`). If the attach dialog only offers
  the `AWS_*` naming style, attach it anyway and map the names with reference
  variables (`LITESTREAM_ACCESS_KEY_ID=${{ … }}`), or ask Claude to adapt
  `litestream.yml` to the names Railway created.
- **HTML corpus** — the existing `spiritolo-corpus` bucket lives in the old
  Railway project and cannot be referenced across projects. Create
  `spiritolo-corpus` in this project, attach it in the **AWS SDK (Generic)**
  style (`AWS_ENDPOINT_URL`, `AWS_S3_BUCKET_NAME`, `AWS_DEFAULT_REGION`,
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, read by
  `ingredients/pipeline/corpus.py`), and copy the objects over once (e.g.
  `rclone sync` with both buckets' credentials in a local shell). The corpus
  is only read by future `extract-recipe` runs — migrated recipes already
  carry their `source` — so the copy can follow the cut-over.

## 3. 1Password vault

One vault (`spiritolo-prod`) of **API Credential** items named after the env
var, field `credential`, read by `secrets.env`:

| Item | Holds |
|---|---|
| `SESSION_SECRET` | a long random string (`openssl rand -base64 48`) |
| `DEEPSEEK_API_KEY` (and optionally `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) | hosted LLM keys; `secrets.env` lists only the items that exist, since `op run` fails on a missing reference |
| `TAILSCALE_AUTHKEY` | the Tailscale OAuth client secret (tag `tag:worker`), if a tailnet Ollama is used |

A **service account** (1Password → Developer → Service accounts) with read
access to that vault only gives `OP_SERVICE_ACCOUNT_TOKEN`.

## 4. Service variables

Plain (non-secret) variables on the service:

```
PUBLIC_ORIGIN=https://spiritolo-staging.up.railway.app
SPIRITOLO_DB=/data/spiritolo.db
STATIC_DIR=/app/web/dist
RUN_EXECUTOR=1
LOG_LEVEL=INFO
LITESTREAM_REPLICA_URL=s3://spiritolo-litestream/spiritolo
```

Reference variables from the attached buckets (step 2): `LITESTREAM_ENDPOINT`,
`LITESTREAM_ACCESS_KEY_ID`, `LITESTREAM_SECRET_ACCESS_KEY`, and the corpus
bucket's `AWS_ENDPOINT_URL`, `AWS_S3_BUCKET_NAME`, `AWS_DEFAULT_REGION`,
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (+ `AWS_S3_URL_STYLE=path`).

Optional: `OLLAMA_BASE_URL=http://barbot:11434` for a tailnet Ollama; the
entrypoint only starts tailscaled when `TAILSCALE_AUTHKEY` resolves from the
vault.

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
