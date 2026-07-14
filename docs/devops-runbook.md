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

---

## 1. Supabase Pro

1. Dashboard → project `spiritolo-staging` → **Settings → Billing** → upgrade to **Pro**. Same project — don't recreate it (keeps the ref + every secret/Vercel env). Removes the 7-day pause + egress cap.
2. Apply migrations:

   ```bash
   supabase login
   supabase link --project-ref atvlzbgrquiseczzeczn
   supabase db push --db-url "$DB_URL" --include-all
   ```

## 2. Repo secrets

```bash
gh secret set SUPABASE_STAGING_DB_URL --body "$DB_URL"
gh secret set RECIPEGF_TOKEN          --body "$RECIPEGF_TOKEN"   # skip if RecipeGF is public
gh secret set RAILWAY_TOKEN           --body "<railway project token>"   # only if using deploy-worker.yml
```

## 3. Tailscale auth key

1. Tailscale dashboard → **Settings → Keys → Generate auth key** → check **Ephemeral + Pre-approved + Reusable**.
2. Capture it: `export TAILSCALE_AUTHKEY=<the key>`.
3. Confirm `barbot` is on the tailnet (MagicDNS resolves it → `http://barbot:11434`).

## 4. Railway project + Storage Bucket

```bash
railway login
railway init --name spiritolo-worker                        # or `railway link` to an existing project
railway bucket create spiritolo-corpus --region <region>    # prompted if --region omitted
eval "$(railway bucket credentials)"                        # loads AWS_ENDPOINT_URL / AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_S3_BUCKET_NAME into this shell
```

- Corpus bucket: S3-compatible (Tigris), $0.015/GB, free egress. **No object-lock/versioning** → your local `data/html/` is the corpus's only other copy; keep it.

## 5. Railway worker

Deploy from the same shell as §4 (the `AWS_*` creds are loaded):

```bash
railway variables \
  --set SUPABASE_DB_URL="$DB_URL" \
  --set SCRAPERAPI_KEY="$SCRAPERAPI_KEY" \
  --set OPENAI_API_KEY="$OPENAI_API_KEY" --set ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" --set DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  --set TAILSCALE_AUTHKEY="$TAILSCALE_AUTHKEY" \
  --set OLLAMA_BASE_URL="http://barbot:11434" \
  --set S3_ENDPOINT="$AWS_ENDPOINT_URL" --set S3_REGION=auto \
  --set S3_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" --set S3_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  --set S3_BUCKET="$AWS_S3_BUCKET_NAME"
railway up --ci        # first deploy (worker.Dockerfile / railway.json)
railway logs           # expect: tailscaled up, tailnet joined, poll loop started
```

- **`RECIPEGF_TOKEN` is a build arg**, not a runtime var — the CLI can't set it. Dashboard → the service → **Settings → Build → Build args** → add `RECIPEGF_TOKEN`. Skip if RecipeGF is public.
- **Auto-deploy:** connect the repo in the Railway dashboard (watched branch `staging`), or use `deploy-worker.yml`.

## 6. Vercel — web SPA

```bash
vercel link
vercel env add VITE_SUPABASE_URL production             # https://atvlzbgrquiseczzeczn.supabase.co
vercel env add VITE_SUPABASE_PUBLISHABLE_KEY production  # sb_publishable_…
vercel env add VITE_SUPABASE_URL preview
vercel env add VITE_SUPABASE_PUBLISHABLE_KEY preview
```

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
| worker code / image / config (push → staging) | Railway native, or `deploy-worker.yml` | `railway up` redeploys the worker |
| `web/**` (push → staging / any PR) | Vercel native | prod / preview deploy |
