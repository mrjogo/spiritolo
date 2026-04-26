<!-- [repo-mixin:devcontainer-claude] Base CLAUDE.md with PR conventions. -->

# spiritolo

Cocktail recipe scraper + verification UI. Stages: discover → fetch → classify_url → validate (HTML + drink scoring) → extract (Schema.org Recipe JSON-LD → Supabase). Vite/React SPA reads `recipes_public`.

- `scraper/` — Python 3.11+ (uv), pytest. Stage CLIs in `scraper/src/{fetch,classify,validate,extract}.py`. Work queue: `data/scraper.db` (SQLite).
- `supabase/migrations/` — `recipes` + `taxonomy_*` tables.
- `web/` — Vite + React + TS + Vitest.
- `docs/` — design + roadmap.

Run `cd scraper && uv run …` and `cd web && npm …` from the repo root.

## Workflow

**PRs:** `gh pr create` against `main` (occasionally `development`). Optional one-paragraph description, up to 8 bullets. No sections, no test plan. After merge: check out main, pull, delete branch.

**Branches for AI agent sessions:** stay on the `claude/<topic>-<short-id>` branch named in the session task. Never push elsewhere.

## Local environment

**Supabase runs on the Mac host, not the devcontainer** (DooD vs `supabase start`'s bind mounts). Host setup: `brew install supabase/tap/supabase && supabase start`. Studio at http://localhost:54323.

Devcontainer `.env`: `SUPABASE_DB_URL=postgresql://postgres:postgres@host.docker.internal:54322/postgres`.

**Migrations from the devcontainer require the IPv4 host** — `host.docker.internal` resolves IPv6-only and isn't routable:

```bash
supabase db reset --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" --yes
```

The trailing `tls error` is misleading — migrations succeed. Verify with a `select`.

URL classifier needs ollama: `ollama pull qwen3:14b`.

## Data model

`data/scraper.db`: `pages` is the canonical per-URL state. Each stage has a `*_runs` table (latest-only UPSERT, prunable — deleting puts pages back on the work queue). A stage's queue is "qualifies AND has no `*_runs` row." Snapshot columns (`pages_*_before`) record what flipped.

Supabase: `recipes` (website-facing columns + full `jsonld`); `taxonomy_nodes` / `taxonomy_edges` / `taxonomy_aliases` (multi-parent DAG, see Spirits Taxonomy below).

## Pipeline conventions

Stage CLIs (`fetch`, `classify`, `validate`, `extract`) share `--site` / `--limit` / `--dry-run` / `--reset [--site S] [--except-version V] [--older-than ISO_TS] [--yes]`. Bare `--reset` wipes the stage's eval scope.

- `validate --reset` clears `validate_html_runs` + `classify_drink_runs` together.
- `classify --reset` also nulls `pages.content_type` (its queue gates on `content_type IS NULL`, not eval-row presence).

**Versioning:** every evaluator has a version constant in its eval rows. When you change logic, bump the constant and re-run with `--reset --except-version <prior>` so prior-version rows fall back on the work queue.

| Stage | Constant | File |
|---|---|---|
| URL classification | `PROMPT_VERSION` | [classify_prompt.py](scraper/src/classify_prompt.py) |
| HTML validation | `VALIDATOR_VERSION` | [validation.py](scraper/src/validation.py) |
| Drink scoring | `SCORER_VERSION` | [classify_drink.py](scraper/src/classify_drink.py) |
| JSON-LD extraction | `EXTRACTOR_VERSION` | [extract.py](scraper/src/extract.py) |

## Pipeline stages

- **`classify.py`** — local ollama on `content_type IS NULL` rows. Iterate prompts via `--review` against the checked-in eval set; use `--sample` for spot-checks. Bump `PROMPT_VERSION` after edits.
- **`validate.py`** — fetch runs validation + drink scoring inline, so this CLI exists only to re-evaluate cached HTML after a version bump.
- **`extract.py`** — parses Schema.org Recipe JSON-LD into Supabase `recipes`. UPSERTs on `source_url`; re-runs are idempotent. To re-extract: clear `extract_runs` rows.

## Spirits Taxonomy

DAG of canonical ingredients. **Read [docs/spirits-taxonomy.md](docs/spirits-taxonomy.md) before adding nodes** — the lean stance (taxonomy for definitional categories + hard constraints; vector layer for soft similarity) is load-bearing. Don't add sensory, stylistic, or colloquial nodes.

Add by editing `supabase/migrations/20260426120100_seed_taxonomy.sql` and re-running `supabase db reset`.

## Web UI

Reads `recipes_public` via the publishable key (`sb_publishable_…`, post-Nov-2025 replacement for the legacy anon key). No backend.

```bash
cd web && npm install
cp .env.local.example .env.local   # paste publishable key from `supabase status`
npm run dev                        # localhost:5173, VS Code auto-forwards
npm test                           # Vitest + @testing-library/react
```

Main suite: [normalizeRecipe.test.ts](web/src/normalizeRecipe.test.ts) covers messy Schema.org Recipe variants. Supabase must be running on the host for the dev server to load data.
