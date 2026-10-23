# Deployment

One Railway service, one environment. The Railway project is **spiritolo-neo**
(environment `staging`, service `spiritolo`); there is no separate production
environment yet, so staging doubles as the live demo.

## What runs

A single container (the repo's [`Dockerfile`](../Dockerfile)) runs one
FastAPI process, `spiritolo.main:app`, which serves:

- the public API (`/api/recipes…`, `/api/taxonomy…`) and the operator API
  (`/api/ops/*`, admin passkey session required);
- the built React app as static files, with an SPA fallback for every
  non-`/api` path;
- the pipeline **executor**, a thread inside the same process that claims
  `queued` runs and processes their `job_items`. There is no worker daemon,
  heartbeat, reaper or `worker_status`.

State is a SQLite file (WAL mode) at `/data/spiritolo.db` on the service's
Railway volume. Litestream wraps the process (`litestream replicate -exec …`)
and streams every WAL change to an S3-compatible Railway bucket; on a fresh or
replaced volume the entrypoint restores from that replica before the app
starts. Plain SQL migrations in `common/src/common/db/migrations/` apply at
boot, tracked in `schema_migrations`.

## Branches and triggers

- `main` — integration trunk. Feature branches (`claude/<topic>-<id>`) merge
  here via PR.
- The Railway service deploys from the branch set in its **Settings → Source**
  (the API refuses that change to a project token, so it is a UI setting).
  During the Supabase → Railway changeover it deploys from the work branch
  `claude/project-thread-0e8m4j`; once that lands it should point at `main`.
  `railway.json` pins the Dockerfile builder, the `/api/health` check, a single
  replica and the on-failure restart policy, so a push to the deploy branch is
  the whole release.

The old `staging` promotion branch, the Supabase migrations workflow and the
Vercel project are gone.

## URL

<https://spiritolo-staging.up.railway.app> (Railway-provided domain, port 8000).
`PUBLIC_ORIGIN` must equal this origin: it is the WebAuthn relying-party origin
and decides whether the session cookie is `Secure`.

## Configuration

Non-secret configuration is plain Railway variables on the service:

| Variable | Value |
|---|---|
| `PUBLIC_ORIGIN` | `https://spiritolo-staging.up.railway.app` |
| `SPIRITOLO_DB` | `/data/spiritolo.db` (also the image default) |
| `STATIC_DIR` | `/app/web/dist` (image default) |
| `RUN_EXECUTOR` | `1` |
| `LOG_LEVEL` | `INFO` |
| `LITESTREAM_REPLICA_URL` | `s3://<litestream bucket>/spiritolo` |
| `LITESTREAM_ENDPOINT` | the bucket's S3 endpoint |
| `AWS_ENDPOINT_URL`, `AWS_S3_BUCKET_NAME`, `AWS_DEFAULT_REGION`, `AWS_S3_URL_STYLE` | the HTML corpus bucket (read by the extract stage) |
| `OLLAMA_BASE_URL`, `TAILSCALE_AUTHKEY` | only if a tailnet Ollama is used |

Secrets never live in Railway variables. [`secrets.env`](../secrets.env) holds
`op://vault/item/field` references; the entrypoint runs the app under
`op run --env-file /app/secrets.env` when `OP_SERVICE_ACCOUNT_TOKEN` is set,
which is the service's only sealed variable. The referenced items are the
session-cookie secret, the hosted-LLM API keys, the Litestream bucket keys and
the corpus bucket keys. Without the token (local docker runs) the process boots
with whatever the environment already has.

## Auth

Operators sign in with a **passkey** (WebAuthn). There is no email, magic link
or self-signup. While the `operators` table is empty, `/login` offers a
first-time setup form that registers the first passkey as an admin; after that,
registration requires an existing signed-in operator. Sessions are a signed,
HttpOnly cookie (`SESSION_SECRET` from the vault; a random per-process secret
otherwise, which logs everyone out on restart).

## Health and restarts

`GET /api/health` runs a trivial query and reports executor liveness. Railway
restarts the container on failure (`ON_FAILURE`, 10 retries). The database
import feature deliberately exits the process (code 3) after staging a file so
the entrypoint can swap it in cold; see [migration.md](migration.md).

## Backups

Litestream is the continuous backup (7-day retention, daily snapshot). See
[backups.md](backups.md) for restore and the optional `VACUUM INTO` snapshot.

See [devops-runbook.md](devops-runbook.md) for the zero-to-deployed steps.
