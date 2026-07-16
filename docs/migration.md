# Data migration — local → hosted

Move the two durable inputs into their hosted homes, then regenerate everything.
Infra standup first: [devops-runbook.md](devops-runbook.md).

- **Move:** HTML corpus (`data/html/`) → object store · `pages` state (URLs + `content_type`) → Postgres.
- **Regenerate:** recipes / ingredients / steps / clusters / exports (re-run the pipeline).
- **Keep:** taxonomy + `cocktail_aliases` (migrations don't drop them). **Don't recreate the Supabase project.**

**Fill in once:**

```bash
export SUPABASE_DB_URL="postgresql://postgres.atvlzbgrquiseczzeczn:<pw>@aws-1-us-east-2.pooler.supabase.com:5432/postgres"
export SUPABASE_STAGING_DB_URL="$SUPABASE_DB_URL"     # same DB (single env); used by the backup

railway link                          # link to the worker's project (§4 of the runbook)
export $(railway bucket credentials --bucket spiritolo-corpus | grep '^AWS_' | xargs)   # AWS_ENDPOINT_URL / _ACCESS_KEY_ID / _SECRET_ACCESS_KEY / _S3_BUCKET_NAME / _DEFAULT_REGION — the loader reads these directly. NOTE: unquoted + grep on purpose — quoting `"$(…)"` jams every pair into AWS_ENDPOINT_URL.
```

Prereqs: infra up (devops-runbook), local `data/scraper.db` + `data/html/`
present. Every step is idempotent — safe to re-run.

---

## 1. Back up staging (rollback insurance)

```bash
scripts/backup-supabase.sh --dest /tmp/premigrate
```

- CI's `validate` job already proves the migrations apply from scratch. The drops in `20260720120000_content_relational_model.sql` are `drop … if exists` on the regenerable content tables only; `taxonomy_*` / `cocktail_aliases` are untouched.

## 2. Promote the schema

```bash
gh pr create --base staging --head main --title "Promote main → staging" --body "Rebuild schema + pipeline"
```

- Merge with a **merge commit — never squash**. CI drops the old content tables and creates the new relational schema + the `pages` table.

## 3. Import pages (SQLite → Postgres)

```bash
cd scripts && uv run python -m corpus_loader import-pages --sqlite ../data/scraper.db
# → read=N extractable=N denylisted=N
```

## 4. Load the corpus (local HTML → object store)

```bash
cd scripts && uv run python -m corpus_loader load-corpus --sqlite ../data/scraper.db --html-dir ../data/html
# → uploaded=N skipped_existing=N missing=N corpus_key_set=N not_in_pg=N
```

- `missing` ≈ 0 (a large value → wrong `--html-dir`). `not_in_pg` = 0 (if >0, step 3 was skipped — run it, then re-run this).

## 5. Regenerate content

Deterministic pass (free, fast; anything only an LLM can resolve parks as `pending`):

```bash
cd ingredients && uv run python -m ingredients.cli cold-build
```

Drain the parked LLM work on the worker (resolves against the kept taxonomy, so mostly alias/lexical; free `barbot` for the rest):

1. `/ops` → for each stage still showing queue depth, click **Trigger → whole queue**.
2. Approve any metered cost prompt.
3. Watch `railway logs` / `/ops` until every depth hits 0.

## 6. Verify

```bash
psql "$SUPABASE_DB_URL" -c "
  select
    (select count(*) from pages) as pages,
    (select count(*) from pages
       where content_type in ('likely_drink_recipe','confirmed_drink')
         and corpus_key is not null) as extractable,
    (select count(*) from recipes) as recipes,
    (select count(*) from recipe_exports) as exports;"
```

- `extractable` ≈ `recipes` ≈ `exports` once drained. `/ops` dashboard depths at 0; `/ops → Exports → preview` spot-checks a bundle.

## 7. Decommission local

- Archive `data/scraper.db` + `data/html/` cold. The bucket has no versioning, so this is the corpus's only other copy — keep it, don't delete.
