# DevOps runbook — zero to a running worker

Fully-cloud, single environment (`staging` == live). One Supabase Pro Postgres
(queue + serving) · one Railway worker + Storage Bucket (HTML corpus) · Vercel
SPA. The worker polls `jobs` (`FOR UPDATE SKIP LOCKED`) — no broker, no inbound
port.

**Tools:** `gh` (authed), `supabase`, `railway` (`npm i -g @railway/cli`),
`vercel`, `aws-cli`, `psql`/`pg_restore` v17+, Node; a Tailscale account with
`barbot` on the tailnet.

**Fill in once** (paste real values; commands below reference these):

```bash
export DB_URL="postgresql://postgres.atvlzbgrquiseczzeczn:<pw>@aws-1-us-east-2.pooler.supabase.com:5432/postgres"
export SCRAPERAPI_KEY=
export OPENAI_API_KEY=
export ANTHROPIC_API_KEY=
export DEEPSEEK_API_KEY=
export RECIPEGF_TOKEN=      # read-only PAT for mrjogo/RecipeGF (skip if public)
```

> Use the **session pooler** host (`aws-1-us-east-2.pooler.supabase.com:5432`).
> The direct `db.<ref>` host is IPv6-only; the transaction pooler (6543) breaks
> session DDL and `pg_dump`.

**Required vs optional:** only `DB_URL` is required (the worker exits without
it). `SCRAPERAPI_KEY` matters only if you re-scrape (the `fetch` stage). The
hosted-LLM keys are optional — a missing one fails only that provider's jobs
(not the worker), and none are read if the provider chain uses only local
`barbot`.

---

## 1. Supabase Pro

1. Dashboard → project `spiritolo-staging` → **Settings → Billing** → upgrade to **Pro**. Same project — don't recreate it (keeps the ref + every secret/Vercel env). Removes the 7-day pause + egress cap.
2. Link the CLI (for `supabase migration list` / ad-hoc ops):

   ```bash
   supabase login
   supabase link --project-ref atvlzbgrquiseczzeczn
   ```

Migrations apply themselves — CI (`deploy-migrations.yml`) runs `supabase db push` to the Pro DB when you promote to `staging` (§9). No manual push.

## 2. Repo secrets

```bash
gh secret set SUPABASE_STAGING_DB_URL --body "$DB_URL"
gh secret set RECIPEGF_TOKEN          --body "$RECIPEGF_TOKEN"   # skip if RecipeGF is public
```

- **`RECIPEGF_TOKEN`** — a GitHub **fine-grained PAT** (Settings → Developer settings → Fine-grained tokens) scoped to **`mrjogo/RecipeGF` only**, permission **Contents: Read-only** (Metadata: Read auto-adds). It authenticates the private `recipegf` clone in `ingredients-ci.yml` and in the Railway image build (set as a plain worker variable in §5 — `worker.Dockerfile`'s `ARG RECIPEGF_TOKEN` receives it at build). Skip it if RecipeGF is public. PATs expire → rotate the repo secret + the worker variable when it lapses.

## 3. Tailscale OAuth client

The worker authenticates with a Tailscale **OAuth client secret**, which never
expires (plain auth keys cap at 90 days), so it re-auths on every boot forever —
no rotation. The entrypoint (`scripts/worker-entrypoint.sh`) already passes
`--advertise-tags=tag:worker ...?ephemeral=true&preauthorized=true`. One-time setup:

1. **Define the tag.** Admin console → **Access controls → Tags → Create tag** → **Tag name** `tag:worker`, **Tag owner** = your Tailscale login email → **Save tag**. (If you've tightened access rules beyond the open default, also allow `tag:worker` → barbot on `:11434`.)
2. **Create the OAuth client.** Admin console → **Settings → Trust credentials** (<https://login.tailscale.com/admin/settings/trust-credentials>) → **Credential** → **OAuth** → enable the **`auth_keys`** *Write* scope → attach tag **`tag:worker`** → **Generate credential** → copy the **secret** (shown once).
3. **Capture it** — this is the worker's `TAILSCALE_AUTHKEY` (§5): `export TAILSCALE_AUTHKEY=<client secret>`.
4. Confirm `barbot` is on the tailnet (`http://barbot:11434`). The worker joins tagged `tag:worker`, ephemeral, each boot.

## 4. Railway project + Storage Bucket

```bash
railway login
railway init --name spiritolo            # the project (holds the worker service + the bucket); or `railway link` to an existing one
railway bucket create spiritolo-corpus   # pick a US-East region at the prompt (nearest Supabase us-east-2)
```

- Corpus bucket: S3-compatible (Tigris), $0.015/GB, free egress. **No object-lock/versioning** → your local `data/html/` is the corpus's only other copy; keep it.
- **Region:** pick a **US-East** region at the bucket prompt (nearest Supabase `us-east-2`); the worker's region is set when its service is created in §5.

## 5. Railway worker

1. **Connect the repo** — creates the worker service (auto-deploys on push):
   - Project canvas → **Create** → **GitHub Repo**.
   - If `mrjogo/spiritolo` isn't listed → grant the **Railway GitHub App** access to it on GitHub → back in Railway, **Refresh**.
   - Pick `mrjogo/spiritolo`; rename the service to **`worker`**.
   - Service → **Settings**: **branch = `staging`**, **region = `us-east4-eqdc4a`**. Leave build command / root dir / start command at defaults — `railway.json` + `worker.Dockerfile` pin the builder, replicas, and entrypoint.
   - Rename the environment **Production → staging** (environment settings).
2. **Connect the bucket → the worker** — the `spiritolo-corpus` bucket → **Credentials** → **Add to service** → Service **`worker`**, Style **AWS SDK (Generic)** → **Add Variables**. This injects `AWS_ENDPOINT_URL` / `AWS_S3_BUCKET_NAME` / `AWS_DEFAULT_REGION` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` as auto-syncing references — the worker reads these directly.
3. **Set the app variables** — `railway link` → the `worker` service. **Set only the ones you have a value for; omit the rest** — Railway rejects an empty `KEY=`. (`RECIPEGF_TOKEN` is a plain variable; `worker.Dockerfile`'s `ARG RECIPEGF_TOKEN` reads it at build.)

   ```bash
   railway variables \
     --set SUPABASE_DB_URL="$DB_URL" \
     --set TAILSCALE_AUTHKEY="$TAILSCALE_AUTHKEY" \
     --set OLLAMA_BASE_URL="http://barbot:11434" \
     --set RECIPEGF_TOKEN="$RECIPEGF_TOKEN"
   ```

   Add the hosted-LLM / scraper keys you actually use, e.g. `--set OPENAI_API_KEY="$OPENAI_API_KEY" --set SCRAPERAPI_KEY="$SCRAPERAPI_KEY"`. Only `SUPABASE_DB_URL` is strictly required (see **Required vs optional** above).
4. **Builds fail until you promote (§9)** — `railway.json` + `worker.Dockerfile` are on `main`, not yet on `staging`, so Railway falls back to Railpack auto-detect and errors with "no start command." That's expected. Once `main → staging` lands, Railway builds `worker.Dockerfile` (its `ENTRYPOINT` is the start command) and `railway logs` shows: tailscaled up, tailnet joined, poll loop started. (To smoke-test the image before promoting, point the deploy branch at `main`, build, then switch back to `staging`.)

## 6. Vercel — web SPA

```bash
vercel link
vercel env add VITE_SUPABASE_URL production             # https://atvlzbgrquiseczzeczn.supabase.co
vercel env add VITE_SUPABASE_PUBLISHABLE_KEY production  # sb_publishable_…
vercel env add VITE_SUPABASE_URL preview
vercel env add VITE_SUPABASE_PUBLISHABLE_KEY preview
```

- `production` / `preview` are Vercel's fixed environment **types** (not free-form like Railway's) — `production` = the live deployment. The `staging` branch feeds it via **Project Settings → Git → Production Branch = `staging`** (already set, since the project deploys on staging pushes). Keep `production` here; don't rename it.
- `/ops` ships inside the same SPA behind the admin gate. Deploys are native: push `staging` = production, PR = preview.

## 7. RecipeGF v0.4.0 pin

```bash
cd ~/code-projects/RecipeGF && git checkout main && git pull
(cd python && uv run pytest) && (cd spec/conformance && npm test)      # green before tagging
git tag -a v0.4.0 -m "Ingredient seams + unit registry as sole authority" && git push origin v0.4.0
gh release create v0.4.0 --title v0.4.0 --notes "Optional-additive; schema const unchanged."
cd ~/code-projects/spiritolo && uv lock --upgrade-package recipegf
(cd ingredients && uv run --extra dev pytest)
```

## 8. Smoke the loop

1. `/ops` → sign in as admin → enqueue a **1-URL** scoped `fetch` job → approve it (metered → confirm-before-cost).
2. Expect: bytes land in the bucket; `pages` + `stage_runs` rows appear; `/ops` shows live status; an `audit_log` row records the mutation.
3. `railway logs`: tailscaled up, tailnet joined, poll loop running.

## 9. Promote to staging

```bash
gh pr create --base staging --head main --title "Promote main → staging" --body "…"
```

- Merge with a **merge commit — never squash** (a squash diverges the branches and breaks the next promotion). Vercel, the migrations workflow, and the worker all pick it up.

---

## CD wiring

| Path changed | Trigger | Effect |
|---|---|---|
| `supabase/migrations/**` (PR → main) | `deploy-migrations.yml` validate job | forward-apply on a throwaway Postgres; blocks a broken migration |
| `supabase/migrations/**` (push → staging) | `deploy-migrations.yml` push job | `supabase db push` to the Pro DB |
| `ingredients/**`, `common/**` (PR → main) | `ingredients-ci.yml` | pytest gate |
| `web/**` (PR → main) | `web-ci.yml` | Vitest gate |
| worker code / image / config (push → staging) | Railway GitHub App | rebuilds `worker.Dockerfile` + redeploys the worker |
| `web/**` (push → staging / any PR) | Vercel native | prod / preview deploy |
