# Data migration — local corpus → hosted pipeline

One-time move of the existing data into the hosted system. Almost nothing is
"converted": the pipeline **regenerates** everything from two durable inputs, so
the job is (1) get those inputs into their hosted homes and (2) re-run the
stages. Infra standup (Supabase Pro, the Railway Storage Bucket, the Railway
worker, Tailscale) is [devops-runbook.md](devops-runbook.md); this is the data.

## What moves vs. regenerates

| Data | Now | Action |
|---|---|---|
| HTML corpus | local files (`data/html/`) | **load → object store** |
| `pages` state (URLs + `content_type`) | local SQLite (`data/scraper.db`) | **import → Postgres** |
| recipes / ingredients / steps / clusters / exports | staging (old schema) | **drop + regenerate** |
| taxonomy + cocktail_aliases | staging | **keep** (migrations don't drop them) |

"Dropping staging" happens *for free* in step 1: the rebuild migration drops the
old content tables and creates the new relational ones, while leaving
`taxonomy_*` and `cocktail_aliases` untouched. Don't delete the Supabase
project — you'd throw away the curated taxonomy for nothing.

## Prereqs

- Infra stood up per [devops-runbook.md](devops-runbook.md) (Supabase Pro, the
  Railway Storage Bucket, the Railway worker deployed).
- Local `data/scraper.db` and `data/html/` present.
- `.env` (repo root) has, for the hosted DB and the object store:

```bash
# The hosted DB (session pooler). Single environment: staging == live, so both
# names point at the same URL — pipeline steps read SUPABASE_DB_URL, the backup
# reads SUPABASE_STAGING_DB_URL.
SUPABASE_DB_URL=postgresql://postgres.atvlzbgrquiseczzeczn:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres
SUPABASE_STAGING_DB_URL=postgresql://postgres.atvlzbgrquiseczzeczn:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres
# Object store — from the Railway bucket's Credentials tab. Any S3-compatible
# store works; these are the generic S3 vars the code reads.
S3_ENDPOINT=https://storage.railway.app
S3_ACCESS_KEY_ID=<key>
S3_SECRET_ACCESS_KEY=<secret>
S3_BUCKET=<globally-unique bucket name>
S3_REGION=auto
```

Every step below is idempotent — safe to re-run. Keep `data/scraper.db` and
`data/html/` until step 5 verifies.

## 0. Back up + pre-flight

**Back up staging first** — rollback insurance before a schema change that drops
the old content tables:

```bash
set -a && source .env && set +a
scripts/backup-supabase.sh --dest /tmp/premigrate   # reads SUPABASE_STAGING_DB_URL
```

The migrations CI `validate` job already forward-applies the whole chain on a
throwaway Postgres, so it's proven to apply from scratch. The one thing that job
can't see is how the rebuild behaves on top of **existing staging data** — so
confirm that's safe: the content-model migration
(`20260720120000_content_relational_model.sql`) drops only the regenerable
content tables (`recipes`, `recipe_ingredients`, `recipe_clusters`,
`recipegf_*`) with `drop … if exists`, and never touches `taxonomy_*` or
`cocktail_aliases`. To preview the exact delta, `migra`-diff staging against a
shadow (see [backups.md](backups.md)).

## 1. Promote the schema to staging

```bash
gh pr create --base staging --head main \
  --title "Promote main → staging" --body "Rebuild schema + hosted pipeline"
```

Merge that PR with a **merge commit — never squash** (a squash diverges the
branches and breaks the next promotion). CI (`deploy-migrations.yml`) applies
the migrations to the Pro DB: old content tables dropped, new relational schema
created, `pages` table added, taxonomy kept.

## 2. Import the pages work-queue (SQLite → Postgres)

Moves URLs + their LLM `content_type` classifications + fetch outcome into the
hosted `pages` table — no re-crawl, no re-classify. Leaves `r2_key` NULL (step 3
sets it).

```bash
cd scripts && uv run python -m corpus_loader import-pages --sqlite ../data/scraper.db
# → read=<N> extractable=<N> denylisted=<N>
```

## 3. Load the HTML corpus (local → object store) and mark pages extractable

Uploads each fetched page's HTML to the object store (write-once; skips keys
already there) and sets `pages.r2_key = sha256(url)` so `extract` can find it.
Denylisted and un-fetched pages are skipped by design.

```bash
cd scripts && uv run python -m corpus_loader load-corpus \
  --sqlite ../data/scraper.db --html-dir ../data/html
# → uploaded=<N> skipped_existing=<N> missing=<N> r2_key_set=<N> not_in_pg=<N>
```

`missing` should be ~0 (a large value means `--html-dir` is wrong). `not_in_pg`
should be 0 — it's >0 only if step 2 was skipped, in which case run
`import-pages` and re-run this.

## 4. Regenerate content

**4a — deterministic cold build (free, fast).** Runs every stage's
alias/lexical tier against the hosted DB; anything only an LLM could resolve
parks as `pending`.

```bash
cd ingredients && uv run python -m ingredients.cli cold-build
```

**4b — LLM residue (the worker).** The Railway worker drains what parked,
resolving against the *preserved* taxonomy — so most lands via alias/lexical and
only genuinely-new names hit an LLM. Point its chain at free local `barbot`
(Tailscale) for the bulk.

1. Open the ops console (your Vercel URL) → **`/ops`** and sign in as admin.
2. For each stage still showing queue depth, click **Trigger** → **whole queue**.
3. A metered stage opens a cost confirm — approve it.
4. Watch `railway logs` (or `/ops` live status) until queue depths reach 0.

## 5. Verify

1. Supabase SQL editor → [new query](https://supabase.com/dashboard/project/atvlzbgrquiseczzeczn/sql/new), run:

   ```sql
   select
     (select count(*) from pages)                                as pages,
     (select count(*) from pages where content_type in ('likely_drink_recipe','confirmed_drink') and r2_key is not null) as extractable,
     (select count(*) from recipes)                              as recipes,
     (select count(*) from recipe_exports)                       as exports;
   ```

   `extractable` ≈ `recipes` ≈ `exports` once the pipeline drains.
2. `/ops` dashboard → every stage's content-queue-depth is **0**.
3. Spot-check a bundle in `/ops` → **Exports** → preview.

## 6. Decommission the local data

Once step 5 checks out, the corpus lives in the object store and the pages
state in Postgres. The bucket has no versioning or object-lock, so keep one cold
archive of `data/scraper.db` + `data/html/` as the only other copy of the
irreplaceable scrape — don't delete them.
