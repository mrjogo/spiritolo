# DevOps runbook — zero to a running worker

The exact CLI to stand up and continuously deploy the fully-cloud topology:
one Supabase Pro Postgres (pipeline queue + serving), a Railway Storage Bucket
for the HTML corpus, one Railway worker, and the Vercel SPA. Single environment
— `staging` doubles as live; there is no separate production yet.

Prereqs on the operator box: `gh` (authenticated), the `supabase` CLI, Node
(`npm`/`npx`), the Railway CLI (`npm i -g @railway/cli`), `aws-cli` (for
inspecting the corpus bucket), `psql`/`pg_restore` v17+, and a Tailscale
account with barbot already on the tailnet.

The worker has no inbound port and no host affinity: it polls the `jobs` table
with `SELECT … FOR UPDATE SKIP LOCKED`. There is no broker and no API server —
Postgres is the queue.

---

## 1. Supabase Pro

Upgrade the existing `spiritolo-staging` project (ref `atvlzbgrquiseczzeczn`) to
**Pro** in the dashboard (Settings → Billing) — do not create a new project, so
every secret and Vercel env keeps pointing at the same ref. Pro removes the
7-day pause and the egress ceiling. Capture the **session-pooler** URL (port
5432, `aws-0-<region>.pooler.supabase.com`); the direct `db.<ref>` host is
IPv6-only and the transaction pooler (6543) breaks session DDL / `pg_dump`.

```bash
supabase login
supabase link --project-ref atvlzbgrquiseczzeczn
supabase db push --db-url "$SUPABASE_STAGING_DB_URL" --include-all   # apply migrations
```

## 2. Repo secrets

Set the CI secrets (repo → Settings → Secrets and variables → Actions):

```bash
gh secret set SUPABASE_STAGING_DB_URL \
  --body "postgresql://postgres.atvlzbgrquiseczzeczn:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres"
gh secret set RECIPEGF_TOKEN --body "<read-only PAT for mrjogo/RecipeGF>"  # skip if the repo is public
gh secret set RAILWAY_TOKEN  --body "<railway project token>"              # only if using deploy-worker.yml
```

`RECIPEGF_TOKEN` authenticates the private `recipegf` git clone in
`ingredients-ci.yml` and in the Railway image build. `RAILWAY_TOKEN` is only
needed if you deploy via the workflow rather than Railway's native GitHub
integration.

## 3. Railway Storage Bucket — corpus

One bucket holding gzipped HTML keyed `sha256(url)`: S3-compatible (Tigris-
backed), $0.015/GB-month, free egress and free API operations. Write-once and
read-only after the one-time load — the loader never overwrites or deletes a
key, and the worker never re-scrapes.

```bash
# In the worker's project (§5's `railway init` creates it; `railway link` to it).
railway bucket create spiritolo-corpus --region <region>   # e.g. --region sjc; prompted if omitted
railway bucket credentials    # prints AWS_ENDPOINT_URL / AWS_ACCESS_KEY_ID /
                              # AWS_SECRET_ACCESS_KEY / AWS_S3_BUCKET_NAME / AWS_DEFAULT_REGION
```

Railway appends a hash to the name for global uniqueness, so take the real
`AWS_S3_BUCKET_NAME` from `credentials`, not the name you passed. §5 sets the
worker's generic `S3_*` vars from this output (`AWS_ENDPOINT_URL`→`S3_ENDPOINT`,
`AWS_ACCESS_KEY_ID`→`S3_ACCESS_KEY_ID`, and so on). (Or create it on the canvas
→ **Create → Bucket** and copy the **Credentials** tab.)

Railway has **no object-lock or versioning** yet, so the corpus's only other
copy is your local `data/html/` archive — keep it. Load the corpus per
[docs/migration.md](migration.md); egress is free afterward.

## 4. Tailscale auth key

Dashboard → Settings → Keys → Generate auth key → **Ephemeral +
Pre-approved + Reusable**. This becomes `TAILSCALE_AUTHKEY`. Confirm barbot is
on the tailnet and MagicDNS resolves `barbot` (`http://barbot:11434` for
Ollama). The worker joins the tailnet in userspace mode on boot and reaches
barbot through a local SOCKS proxy; hosted APIs take the direct route.

## 5. Railway worker

```bash
railway login
railway init --name spiritolo-worker        # or `railway link` to an existing project
railway variables \
  --set SUPABASE_DB_URL="postgresql://postgres.atvlzbgrquiseczzeczn:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres" \
  --set SCRAPERAPI_KEY=<key> \
  --set OPENAI_API_KEY=<key> --set ANTHROPIC_API_KEY=<key> --set DEEPSEEK_API_KEY=<key> \
  --set TAILSCALE_AUTHKEY=<ts_authkey> \
  --set OLLAMA_BASE_URL="http://barbot:11434" \
  --set S3_ENDPOINT=https://storage.railway.app --set S3_REGION=auto \
  --set S3_ACCESS_KEY_ID=<AWS_ACCESS_KEY_ID> --set S3_SECRET_ACCESS_KEY=<AWS_SECRET_ACCESS_KEY> \
  --set S3_BUCKET=<AWS_S3_BUCKET_NAME>
# The three <…> S3 values are the matching fields from `railway bucket
# credentials` (§3). RECIPEGF_TOKEN is a BUILD arg (worker.Dockerfile `ARG`),
# not a runtime var — the CLI can't set build args, so add it in
# dashboard → service → Settings → Build → build args (skip if RecipeGF is public).
railway up --ci                              # first deploy from worker.Dockerfile / railway.json
railway logs                                 # confirm: tailscaled up, tailnet joined, poll loop started
```

`railway.json` pins the Dockerfile builder (`worker.Dockerfile`) and
`numReplicas: 1`. Then either connect the repo in the Railway dashboard with the
watched branch set to `staging` (native deploy-on-push) or rely on
`deploy-worker.yml`.

## 6. Vercel — web SPA

The `spiritolo-staging` Vercel project already exists; deploys are native (push
to `staging` = production, PR = preview). Set the env (Production + Preview):

```bash
vercel link
vercel env add VITE_SUPABASE_URL production             # https://atvlzbgrquiseczzeczn.supabase.co
vercel env add VITE_SUPABASE_PUBLISHABLE_KEY production  # sb_publishable_…
vercel env add VITE_SUPABASE_URL preview
vercel env add VITE_SUPABASE_PUBLISHABLE_KEY preview
```

The `/ops` admin console ships inside the same SPA behind the admin gate — no
extra build target, no service-role key in the browser.

## 7. RecipeGF v0.4.0

Tag the grammar library, then bump Spiritolo's pin.

```bash
cd ~/code-projects/RecipeGF
git checkout main && git pull
(cd python && uv run pytest) && (cd spec/conformance && npm test)   # green before tagging
git tag -a v0.4.0 -m "Ingredient seams + unit registry as sole authority"
git push origin v0.4.0
gh release create v0.4.0 --title "v0.4.0" --notes "Optional-additive; schema const unchanged."
```

```bash
# In Spiritolo: pin the tag in ingredients/pyproject.toml, then relock + verify.
cd ~/code-projects/spiritolo
uv lock --upgrade-package recipegf
(cd ingredients && uv run --extra dev pytest)
```

## 8. Smoke the loop

Sign into `/ops` as an admin, enqueue a **1-URL** scoped `fetch` job, approve it
(metered → confirm-before-cost), and watch the worker claim it: ScraperAPI
fetches, bytes land in the bucket, the `pages` / `stage_runs` rows appear,
`/ops` shows live status via Realtime, and an `audit_log` row records the
mutation. `railway logs` should show tailscaled up, the tailnet joined, and the
poll loop running.

## 9. Promote to staging

```bash
gh pr create --base staging --head main \
  --title "Promote main → staging" --body "…"
```

Merge that PR with a **merge commit — never squash** (a squash fabricates a new
commit on `staging` that diverges the trees and makes the next promotion
conflict). The staging Vercel deploy, the migrations workflow, and the Railway
worker all pick it up.

---

## CD wiring summary

| Path changed | Trigger | Effect |
|---|---|---|
| `supabase/migrations/**` (PR → main) | `deploy-migrations.yml` validate job | forward-apply on a throwaway Postgres; blocks a broken migration |
| `supabase/migrations/**` (push → staging) | `deploy-migrations.yml` push job | `supabase db push` to the Pro DB |
| `ingredients/**`, `common/**` (PR → main) | `ingredients-ci.yml` | pytest gate |
| `web/**` (PR → main) | `web-ci.yml` | Vitest gate |
| worker code / image / config (push → staging) | Railway native, or `deploy-worker.yml` | `railway up` redeploys the worker |
| `web/**` (push → staging / any PR) | Vercel native | prod / preview deploy |
