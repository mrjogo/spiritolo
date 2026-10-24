# Deployment

One Railway service, one environment. The Railway project is **spiritolo-neo**
(environment `production`, service `spiritolo`). There is deliberately no
standing staging environment: pipeline runs are one-shot and their results are
the real data, so a second file would only mean a second import. If a code
change ever needs a rehearsal, fork a Railway environment and let the
entrypoint restore it from a Litestream replica (see [backups.md](backups.md)).

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
  That is **`prod`**, a promotion branch: `main` is the dev branch and never
  deploys on its own. A release is a PR `main → prod`, merged with a **merge
  commit, never squash** (a squash diverges the trees and breaks the next
  promotion). (`prod` is the old `staging` branch, renamed; during the Supabase
  → Railway changeover the service deployed from `claude/project-thread-0e8m4j`.)
  `railway.json` pins the Dockerfile builder, the `/api/health` check, a single
  replica and the on-failure restart policy, so a push to the deploy branch is
  the whole release.

The Supabase migrations workflow and the Vercel project are gone.

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
| `BUCKET_NAME`, `BUCKET_ENDPOINT`, `BUCKET_REGION`, `BUCKET_ACCESS_KEY_ID`, `BUCKET_SECRET_ACCESS_KEY` | reference variables from the attached `spiritolo-litestream` bucket; the entrypoint derives `LITESTREAM_REPLICA_URL` (`s3://$BUCKET_NAME/spiritolo`), `LITESTREAM_ENDPOINT`, `LITESTREAM_REGION` and the keys from them (set a `LITESTREAM_*` variable only to override) |
| `AWS_ENDPOINT_URL`, `AWS_S3_BUCKET_NAME`, `AWS_DEFAULT_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_URL_STYLE` | reference variables from the attached `spiritolo-corpus` bucket (read by the extract stage) |
| `OLLAMA_BASE_URL`, `TAILSCALE_AUTHKEY` | only if a tailnet Ollama is used |

Secrets never live in Railway variables. [`secrets.env`](../secrets.env) holds
`op://vault/item/field` references; the entrypoint runs the app under
`op run --env-file /app/secrets.env` when `OP_SERVICE_ACCOUNT_TOKEN` is set,
which is the service's only sealed variable. The referenced items are the
session-cookie secret, the hosted-LLM API keys and the Tailscale key. Bucket
credentials are Railway reference variables, not vault items. Without the token (local docker runs) the process boots
with whatever the environment already has.

## Auth

Operators sign in with a **passkey** (WebAuthn). There is no email, magic link
or self-signup. While the `operators` table is empty, `/login` offers a
first-time setup form that registers the first passkey as an admin. After that
there are two ways to add a passkey: a signed-in operator adds one to their own
account, or an admin mints a **registration link** in `/ops → Operators`
(`POST /api/ops/operators/{id}/invites`): a single-use URL, valid 7 days, that
registers a passkey for that operator with no session (`/login?invite=<token>`).
Create the `operators` row first for a new operator, then send them a link.
Sessions are a signed, HttpOnly cookie (`SESSION_SECRET` from the vault; a
random per-process secret otherwise, which logs everyone out on restart).

### Moving to a new hostname

Passkeys are bound to the domain they were created on (the WebAuthn relying
party is `PUBLIC_ORIGIN`'s hostname), so changing the origin silently locks every
operator out, and first-time setup is closed once an operator exists. The order
that works:

1. On the current hostname, `/ops → Operators` → **Registration link** for
   yourself (and anyone else). Copy the path; it is the same on every hostname.
2. Add the custom domain to the Railway service and set `PUBLIC_ORIGIN` to it;
   redeploy.
3. Open `https://<new host>/login?invite=<token>` and register a passkey there.
4. Sign in on the new hostname; the old Railway domain can then be removed.

## Health and restarts

`GET /api/health` runs a trivial query and reports executor liveness. Railway
restarts the container on failure (`ON_FAILURE`, 10 retries). The database
import feature deliberately exits the process (code 3) after staging a file so
the entrypoint can swap it in cold; see [migration.md](migration.md).

## Backups

Litestream is the continuous backup (7-day retention, daily snapshot). See
[backups.md](backups.md) for restore and the optional `VACUUM INTO` snapshot.

See [devops-runbook.md](devops-runbook.md) for the zero-to-deployed steps.
