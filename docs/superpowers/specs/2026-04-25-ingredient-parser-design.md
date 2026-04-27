# Ingredient Parser — Design

## Context

Per [docs/future-direction.md](../../future-direction.md), ingredient extraction is the bottleneck unlock for downstream features (search-by-ingredient, dedup, taxonomy mapping, similarity, substitutions). It is track `[A]` on the roadmap, mutually independent from `[B]` (spirits taxonomy) and `[C]` (search). It is the last step before `[D]` (mapping free-text to canonical taxonomy IDs), `[E]` (dedup), and `[F]` (search re-pointed at structured ingredients).

This spec covers `[A]` only.

## Decisions

### Architecture: zone separation

The system has two zones whose boundary is the `recipes` table in Supabase:

- **Zone 1 — scraper.db (offline, batch).** Fetch → classify URL → classify drink → extract JSON-LD. Page-keyed work queues, versioned `*_runs` eval tables, `--reset --except-version` flow. Job ends when a recipe is committed to Supabase.
- **Zone 2 — Supabase (online, reactive).** Everything derivative of `recipes`: parse ingredients, build search indexes, compute dedup hashes, map to taxonomy IDs, embeddings. Each is a reconciling function of recipe data.

**Ingredient parsing is Zone 2.** It does not run inline in the extract CLI. Doing so would couple parser-version bumps to scraper deploys and put Zone 2 logic on the wrong side of the boundary.

### Architecture: reconciling-worker pattern

`recipe_ingredients` is managed by an idempotent reconciling worker whose job is "for every `recipes` row, ensure there is a current-version parse." The wake-up mechanism evolves over time without changing the data model:

| Phase | Mechanism | Trigger |
|---|---|---|
| **v1 (this spec)** | Polling worker — Python CLI run manually or by cron | Operator invokes `parse_ingredients` |
| v2 | Postgres `LISTEN/NOTIFY` worker | `recipes` insert fires NOTIFY; worker reacts |
| v3 | Supabase Edge Function (Deno/TS) | Realtime/webhook on `recipes` insert |

Same `recipe_ingredients` schema, same `parser_version` versioning, same eval discipline in all three. Only the wake-up code changes.

### Architecture: three top-level Python packages with a shared `common`

Repo layout:

```
spiritolo/
├── common/                  (new, shared utilities)
│   ├── pyproject.toml
│   └── src/spiritolo_common/
│       ├── supabase_client.py
│       ├── progress.py
│       ├── summary.py
│       ├── cli_common.py    (shared --site / --limit / --dry-run / --reset arg parsing)
│       └── ...
├── scraper/                 (existing, Zone 1; uses common)
│   ├── pyproject.toml
│   └── src/scraper/...
├── ingredients/             (new, Zone 2; uses common)
│   ├── pyproject.toml
│   ├── src/ingredients/
│   │   ├── parser.py        (pure-function rules, no I/O)
│   │   ├── units.py         (canonical unit table)
│   │   ├── eval_set.py      (golden cases for --review)
│   │   ├── cli.py
│   │   └── ...
│   └── tests/
├── web/
├── supabase/
└── data/
```

Wired together as a uv workspace at the repo root: a top-level `pyproject.toml` declares `[tool.uv.workspace]` with `members = ["common", "scraper", "ingredients"]`. Each member depends on `spiritolo-common` via a workspace source so editing `common/` updates both consumers without re-publishing.

Three reasons:

1. **Hard isolation between Zones, AI-safe.** Separate `pyproject.toml` and venvs mean code in `ingredients/` cannot import from `scraper/` — failure is at import time, not code review. Concrete bright line.
2. **Lifecycle and dependency independence.** Scraper needs httpx, bs4, ollama, scraperapi adapters. Ingredients needs Supabase client and (likely) `ingreedypy`. Common stays minimal. They diverge cleanly as Zone 2 grows.
3. **Single source of truth for shared things.** A `supabase_client.py` duplicate across scraper and ingredients is exactly the AI-safe-boundary problem we are trying to avoid (an AI fixing a bug in one copy and not the other). Better to start with `common/` than to refactor under pressure later.

**What goes into `common/` at v1 launch:** the utilities both Zones need today.

- `supabase_client.py` — currently in `scraper/src/scraper/supabase_client.py`. Move; update scraper imports.
- `progress.py` — the shared `X/Y (Z%) rows/s ETA ...` progress line.
- `summary.py` — per-site / per-category summary printer.
- `cli_common.py` — argparse helpers for `--site`, `--limit`, `--dry-run`, `--reset --yes`, `--except-version`, `--older-than`.

Scraper-specific things stay in scraper: `client.py` (HTTP), `db.py` (scraper.db SQLite layer), ollama clients, fetcher/classifier/extractor stages.

**Scraper migration is part of this work.** Both packages must use `spiritolo-common` from day one. Keeping copies in place is exactly what we're avoiding. Plan-time decomposes the migration into "carve out common, update scraper imports, then build ingredients on top." Scraper functionality and tests must be unchanged after the migration.

### Approach: rule-based, not LLM

Reality-check on 49,500 ingredient lines from the three sites loaded so far (diffordsguide, liquor, punch):

| Pattern | Share | Notes |
|---|---:|---|
| `<qty> <recognized unit> <name>` | 90.1% | Trivial regex |
| `<qty> <count noun>` (e.g. `7 fresh Mint leaves`) | 4.3% | Closed list of count nouns |
| `Garnish: <thing>` | 3.0% | Mostly liquor.com |
| No qty, no keyword (`Float ...`, `..., to top`) | 1.9% | Patterned tail |
| `Top up with <thing>` | 0.6% | Mostly diffordsguide |
| Tail (garnish keyword, empty) | 0.2% | |

Rule-based parsing comfortably handles the head and adds two-three site-specific rules to handle the tail. No "I have no idea what this string means" category appears; every weird bucket is itself patterned.

**Hand-rolled rules, no library dependency.** The leading Python option for ingredient parsing as of 2026 is `ingredient-parser-nlp` (strangetom/ingredient-parser, 147 stars, 26K downloads/month, actively maintained), but it is a trained sequence-labelling model rather than a rule-based parser. Sequence labellers do not naturally implement strict abstain — they emit labels for every token with some confidence. To match our precision-over-recall discipline you would threshold per-token confidence and treat low-confidence parses as unparseable. Possible but a different evaluation discipline. The cocktail-ingredient surface is simple enough (90% structurally regular per the reality check above) that there is no library worth its dependency cost in v1. Hand-rolled regex against a closed unit table is the right tool. ingredient-parser-nlp stays in the back pocket as a possible fallback for the unparseable bucket if v1's rate exceeds target.

LLM is also rejected for v1: slower, costs, nondeterministic, harder to test. Rule output is deterministic, which makes the eval-set discipline tighter than the existing LLM stages.

**Caveat.** Only 3 of 13 sites are loaded. Food-cooking sites (foodnetwork, bonappetit, foodandwine, etc.) have not extracted yet. From an HTML peek, foodandwine has at least one ugly pattern (occasional `Name: qty unit` reverse and rows where the ingredient list got concatenated into one string). We expect the clean percentage to dip a few points but not collapse — JSON-LD authors generally publish structured strings to satisfy Google.

### Approach: precision over recall (strict abstain discipline)

Parser must abstain rather than guess. Better to skip an ambiguous row than ingest it wrong: skipped rows stay queryable and re-runnable, wrongly-parsed rows are silent garbage.

Rules:

- Each rule is a **closed-form regex** with all named groups bound; partial binds do not "best-effort" populate fields.
- The **unit table is closed.** Surface forms outside the table do not match the qty/unit rule.
- The **count-noun list is closed.** Same discipline.
- **No fall-through** to "name = whole string." If no rule matches, `parse_status='unparseable'`, every other field null, raw_text preserved.
- Downstream consumers filter to `parse_status='parsed'`.

### Approach: defer modifier extraction, defer normalization beyond hygiene

V1 does not split modifiers from names. `"good bourbon"` parses as `name='good bourbon'`. `"fresh lime juice"` parses as `name='fresh lime juice'`. Reasoning: modifier-vs-name is the judgment call where rules struggle and where canonical-mapping (`[D]`) will resolve the right answer anyway. Doing it in two stages would mean doing it twice.

V1 does perform surface hygiene: NFKC unicode normalization, unicode-fraction → ASCII (`½` → `1/2`), whitespace collapse, lowercase the name field. No synonym collapsing, no typo correction, no fuzzy matching.

## Data model

### `recipe_ingredients`

```sql
create table recipe_ingredients (
  id              bigserial primary key,
  recipe_id       bigint not null references recipes(id) on delete cascade,
  position        int not null,        -- 0-based index within JSON-LD recipeIngredient array
  raw_text        text not null,       -- original string, untouched
  amount          numeric,             -- null for unparseable / no-quantity rows
  amount_max      numeric,             -- upper bound for ranges ("1/2 to 3/4 oz")
  unit            text,                -- canonical form: oz, ml, cl, dash, drop, leaf, cube, ...
  name            text,                -- remainder after qty+unit; lowercased + whitespace-collapsed; null when unparseable
  modifier        text,                -- v1: always null (deferred to mapping stage)
  parse_status    text not null,       -- 'parsed' | 'unparseable'
  parser_rule     text,                -- 'qty_unit' | 'garnish_prefix' | 'topup' | 'count_noun' | null when unparseable
  parser_version  text not null,
  parsed_at       timestamptz not null default now(),

  unique (recipe_id, position)
);

create index recipe_ingredients_recipe_idx on recipe_ingredients (recipe_id);
create index recipe_ingredients_name_idx on recipe_ingredients (name) where name is not null;
create index recipe_ingredients_unit_idx on recipe_ingredients (unit) where unit is not null;
```

Notes:

- `(recipe_id, position)` uniqueness makes reconciliation a single `delete from recipe_ingredients where recipe_id=R; insert ...` per recipe, no duplicate handling.
- Unparseable rows are stored so per-recipe completeness is recoverable. A recipe's ingredient list is `select * from recipe_ingredients where recipe_id=R order by position`, including the failures.
- `recipes_public` view is unchanged for now. A future projection that joins parsed rows lands when the website needs ingredient access.

### Future: canonical ingredients (out of scope for this spec)

Planned shape, included here for cross-validation against the `recipe_ingredients` schema. **Not built in v1.**

```sql
-- Curated catalog of canonical ingredients.
create table ingredients (
  id           bigserial primary key,
  canonical    text not null unique,           -- 'bourbon', 'gin', 'lime juice', 'simple syrup'
  category     text,                           -- 'spirit' | 'citrus' | 'syrup' | 'modifier' | 'garnish' (nullable until taxonomy lands)
  parent_id    bigint references ingredients(id),  -- 'bourbon' -> 'whiskey' -> 'spirit'
  ...
);

-- Resolved by [D] / taxonomy mapping.
alter table recipe_ingredients add column ingredient_id bigint references ingredients(id);
```

`recipe_ingredients` keeps its parsed `name` (e.g. `'good bourbon'`) AND, post-`[D]`, the canonical FK. Many parsed names converge to a few hundred canonical IDs. The spirits taxonomy hierarchy lives via `parent_id`. Modifier extraction (`'good bourbon'` → name=`bourbon` + modifier=`good`) happens at mapping time, where it can use the canonical catalog as ground truth — cheaper than splitting blind.

## Parser ladder

A pure function `parse(raw: str, site: str | None) -> ParseResult` tries rules in order; first match wins; no match yields `unparseable`. Site is informational — used to dispatch site-specific quirks where useful, never to relax strictness.

1. **Pre-clean** (always applied). NFKC normalize. Replace unicode fractions (`½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞`) with ASCII fractions. Collapse internal whitespace. Trim. Strip surrounding punctuation (trailing `,`, `.`).
2. **`garnish_prefix`** — `^Garnish\s*:\s*(?P<name>.+)$`. Returns `amount=null, unit=null, name=<rest>`. Most useful on liquor.
3. **`topup`** — `^Top up with\s+(?P<name>.+)$`. Returns `amount=null, unit=null, name=<rest>`. Most useful on diffordsguide.
4. **`qty_unit`** — `^<QTY>\s+<UNIT_FROM_TABLE>\s+<NAME_NONEMPTY>$`. The 90% case. `UNIT_FROM_TABLE` is a strict closed vocabulary mapping each surface form to a canonical unit:
   - volume: `oz` ← `oz`, `oz.`, `ounce`, `ounces`, `fluid ounce`, `fl oz`
   - volume: `ml` ← `ml`, `mL`
   - volume: `cl` ← `cl`
   - volume: `tsp` ← `tsp`, `tsp.`, `teaspoon`, `teaspoons`, `T` (only in unambiguous contexts)
   - volume: `tbsp` ← `tbsp`, `tbsp.`, `tablespoon`, `tablespoons`
   - volume: `cup` ← `cup`, `cups`
   - bartending counts: `dash`, `drop`, `splash`, `barspoon`, `pinch`
   - canonical list maintained in `ingredients/units.py`
5. **`count_noun`** — `^<QTY>\s+(?:fresh\s+|dried\s+|whole\s+)?<COUNT_NOUN>\s+<NAME>$`. Count nouns are a closed list (`leaf`/`leaves`, `slice`, `wedge`, `cube`, `stick`, `sprig`, `piece`, `wheel`, `egg white`, ...). Canonical `unit` is the count noun. The leading `fresh|dried|whole` qualifier is dropped (raw_text preserves it).
6. **No match** → `parse_status='unparseable'`, all other fields null.

`<QTY>` covers integers, fractions (`1/2`), mixed numbers (`1 1/2`), decimals (`0.25`, `1.5`), and ranges (`1/2 to 3/4`). Ranges produce `amount=lower, amount_max=upper`.

Discipline check: any rule that would bind only some named groups must abstain. A row is `parsed` only when its rule populates a complete shape (qty+unit+name for `qty_unit` and `count_noun`; just name for `garnish_prefix` and `topup`).

## Eval set and version workflow

Same convention as `classify_url_runs`, `validate_html_runs`, `extract_runs` in scraper. Single checked-in fixture file, three buckets:

1. **Should-parse-as-X** — golden cases per rule, per site. Coverage: clean head, ranges, unicode fractions, count-nouns, decimals, `Garnish:` prefix, `Top up with`.
2. **Should-abstain** — examples that must NOT over-match. Coverage: foodandwine concatenated bug (`0.5 oz Santoni Amaro3 oz Lambrusco...`), reverse format (`D'Usse VSOP: 30 ml`), parenthesized equivalent volumes (`1 (375ml) bottle (1 1/2 cups) rye whiskey`), footnote artifacts (`Coconut ice sphere*`).
3. **CLI:** `parse_ingredients --review` runs the eval set with no DB writes; prints pass/fail per case. Mirrors `classify --review`.

Iteration loop when adding a unit, count-noun, or rule:

1. Add it to `units.py` / rules module.
2. `--review` until eval set passes.
3. Bump `PARSER_VERSION`.
4. `parse_ingredients --reset --except-version V --yes` re-parses old rows.

Deterministic outputs make the eval set tighter than the existing LLM stages; a regression is a code change.

## CLI shape

`ingredients/src/ingredients/cli.py` exposes `parse_ingredients` matching the existing scraper conventions:

```
cd ingredients && uv run python -m ingredients.cli [options]

  --site S                   restrict to one source site
  --limit N                  cap rows processed
  --dry-run                  parse and report; no DB writes
  --review                   run the eval set; no DB
  --reset --yes              clear all recipe_ingredients rows in scope before re-parsing
    --except-version V       (with --reset) keep rows already at version V
    --older-than ISO_TS      (with --reset) only clear rows parsed before this timestamp
```

Work queue: `recipes` rows where no `recipe_ingredients` row exists OR all `recipe_ingredients` rows are at a version other than current `PARSER_VERSION`. Per-recipe processing is atomic (delete-then-insert in a transaction).

Progress + summary lines match scraper format (`X/Y (Z%) rows/s ETA ...`, per-site breakdown).

## Scope: what is and is not in v1

**In:** Polling worker + CLI; `recipe_ingredients` table; pre-clean + 4 parser rules + abstain; eval set; `PARSER_VERSION` versioning; reconciling re-parse via `--reset --except-version`.

**Out:**

- Modifier extraction. `name` keeps adjectives.
- Synonym collapsing. `rye` and `rye whiskey` stay distinct.
- Fuzzy matching, typo correction.
- LLM fallback for unparseable rows. Re-evaluate after a full-corpus pass measures the unparseable rate. Target: <3%. If we exceed, we revisit (more rules first, then LLM).
- Postgres trigger / Edge Function. Polling-only for v1.
- `recipes_public` ingredient projection. Lands when the website needs it.
- Canonical `ingredients` table and taxonomy mapping (`[D]`). Separate spec.

## Open questions for plan-time

- **Where does `PARSER_VERSION` and the canonical units table physically live in the new package?** Default: `ingredients/src/ingredients/parser.py` (`PARSER_VERSION`) and `ingredients/src/ingredients/units.py` (canonical units, count nouns).
- **Does `parse_ingredients --reset` accept `--site`?** Default: yes, mirroring scraper convention. Filters AND together.
- **Library fallback for the unparseable bucket?** Default: none in v1. After a full-corpus pass measures the unparseable rate and shape, if the rate exceeds 3% target, evaluate `ingredient-parser-nlp` (the SOTA Python option) as a confidence-thresholded second pass — only on rows where rules abstained, and only accepting parses above a calibrated probability threshold. Decision deferred to a follow-up; v1 ships with rules only.
- **One transaction per recipe vs. batch?** Default: batch with savepoints — one savepoint per recipe so one bad row doesn't roll back a thousand good ones.
- **Migration ordering in plan-time.** Does plan-time tackle (1) workspace skeleton, (2) carve out `common`, (3) migrate scraper to depend on `common`, (4) build `ingredients` package, (5) ship parser, in that order? Default: yes. Each step is independently verifiable; scraper tests must stay green throughout.
