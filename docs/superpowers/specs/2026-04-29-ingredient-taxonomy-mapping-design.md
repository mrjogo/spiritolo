# Ingredient → Taxonomy Mapping — Design

## Context

Per [docs/future-direction.md](../../future-direction.md), Track `[D]` resolves the free-text `recipe_ingredients.name` strings written by the parser (Track `[A]`) into canonical `taxonomy_nodes.id` references (Track `[B]`). It is the bridge that lets every downstream feature stop doing `LIKE '%gin%'` queries: walking the taxonomy DAG by ID powers "all whiskeys" filtering, ingredient-aware search, dedup, ingredient-overlap similarity, and ultimately substitution.

This spec covers `[D]` only — specifically the mapper itself.

**Prerequisite (separate spec):** the existing taxonomy seed in [supabase/seeds/taxonomy_nodes.sql](../../../supabase/seeds/taxonomy_nodes.sql) covers spirit families and a small produce set, but is missing structurally important categories (liqueurs, syrups, juices, fresh herbs, dairy, mixers), brand and expression nodes, the alias table is empty, and form-node coverage exists only as a decision in this spec. Extending the seed is its own design+implementation track. The mapper code in this spec is built and tested against a fixture taxonomy that exercises every code path; the first end-to-end production run is gated on the taxonomy-seed-extension track landing.

## Status snapshot from the data

Counts as of writing, against `recipe_ingredients` produced by `PARSER_VERSION = "v1"`:

| Metric | Value |
|---|---|
| Total ingredient rows | 101,570 |
| Parsed rows (`parse_status='parsed'`) | 99,821 |
| Unique normalized `name` strings | 25,912 |
| Strings appearing exactly once (singletons) | 20,765 |
| Top 15 strings, share of total rows | ~16% |

Distribution is heavy-tailed. The head is concentrated enough that an alias seed for the top ~500 strings will cover the bulk of rows deterministically; the tail is what the LLM layer earns its keep on.

## Decisions

### Mapper layer ordering: strict cascade

For every unique normalized `name`, walk three layers and stop at the first confident hit. The layer that produced the answer is recorded on the row.

| Layer | Source value | Mechanism |
|---|---|---|
| 1 | `alias` | `SELECT node_id FROM taxonomy_aliases WHERE alias = :normalized_name` |
| 2 | `lexical` | `pg_trgm` similarity over `taxonomy_nodes.display_name` ∪ `taxonomy_aliases.alias`. Accept only when `top1.similarity ≥ 0.92 AND top1.similarity > 1.5 × top2.similarity` |
| 3 | `llm` | Anthropic Claude Haiku 4.5. Input: raw string, parser context (unit, site), top-20 lexical candidates with their parents. Output: a chosen node id, a brand/expression auto-create proposal, a form-node review proposal, or abstain |

If all three layers fail to resolve, the row is recorded with `mapper_source='abstain'` and `taxonomy_node_id IS NULL`.

The cascade is deliberate. Rows resolved at Layer 1 cost effectively zero on every re-run forever; LLM is only paid for strings the deterministic layers couldn't handle. The alternative (always-LLM with lexical as candidate generator) was considered and rejected: the heavy-headed distribution makes per-string LLM cost wasteful when a one-time alias seeding job buys deterministic resolution for the top of the distribution.

### Cascade thresholds and the "lexically confident, semantically wrong" risk

Layer 2's threshold is set conservatively (`sim ≥ 0.92`, `top1 > 1.5 × top2`) to fail closed — better to fall through to LLM than to confidently mis-map. The discipline that polices threshold tuning is the eval set: every case where the lexical layer was confidently wrong becomes a `should-abstain-and-fall-through-to-LLM` eval row, plus either an explicit alias entry or a threshold tightening.

### Brand and expression nodes auto-create silently

When the LLM identifies a row as a specific brand or expression that doesn't exist in `taxonomy_nodes` and proposes a parent that does exist, a node is created automatically. Provenance is written to `taxonomy_provenance` so a later audit pass (out of scope for this spec) can review what the mapper produced.

If the LLM proposes a parent that doesn't exist, the row abstains rather than auto-creating an orphan.

The doc [docs/spirits-taxonomy.md](../../spirits-taxonomy.md) explicitly endorses this stance: "Hand-curate the well-known; let the [D] mapper auto-create the long tail when it exists."

### Form nodes go through a human review queue

Form nodes (`lemon_juice`, `lemon_wheel`, `lemon_wedge`, `lemon_slice`, `lemon_twist`, `lemon_peel`, etc.) have low cardinality and high reuse — once the form set is curated for one substance, the same set tends to apply across substances. New form proposals from the LLM are written to `taxonomy_proposals` for one-by-one human review via a CLI; nothing is auto-created.

The seed (separate spec) includes the known form set. The review queue exists to absorb forms the seed missed (`lemon_zest`, `lime_oil`, `orange_supreme`, etc.) without polluting the canonical taxonomy with anything the LLM imagined unsupervised.

### Form nodes are distinct, not annotations on rows

A `recipe_ingredients` row whose parsed `name` resolves to `lemon_juice` is materially different from one resolving to `lemon_wheel` — different role in the drink, different chemistry, different unit semantics. Consequently the taxonomy carries a node per form, and the mapper resolves to the most specific node it can.

The principle: **a node represents a substance-form that everything mapping to it is synonymous with, not merely a child of.** "Wheel" and "wedge" are not synonyms — same role, different cut — so they get separate nodes. Erring on the side of separation is intentional; merging is cheap, splitting is expensive.

This principle generalizes to the spirits side: `cask_strength_bourbon` is a legitimate node under `bourbon`, not an attribute. Similarly `overproof_rum`, `bonded_whiskey`, `navy_strength_gin` — anywhere strength or style materially changes the role in a drink.

### Output shape: columns on `recipe_ingredients`

The mapper writes back to `recipe_ingredients` rather than introducing a separate mapping table. This matches how the parser writes its output and how the JSON-LD extractor writes recipe columns: each stage's output is a function of its input row, produced exactly once per version, and overwriting in place is the natural shape.

A separate table would only be justified if mappings were many-to-many or required history beyond the version field. Neither is true for v1.

### Versioning: `MAPPER_VERSION` constant, matches existing convention

`MAPPER_VERSION = "v1"` in `ingredients/src/ingredients/mapping/mapper.py`. Stored on every mapped row. Bumping the constant requires re-running with `--reset --except-version <prior>` to push prior-version rows back onto the work queue, mirroring the pattern used by `PARSER_VERSION`, `EXTRACTOR_VERSION`, etc.

The eval set must pass on every version bump.

### LLM layer: Anthropic Claude, cached per unique string

Claude Haiku 4.5 by default; escalate low-confidence calls to Sonnet 4.6. Cost back-of-envelope (assuming ~600 input + ~80 output tokens per call): worst-case all-LLM run ~$15–30 against the current 25,912 unique strings; realistic run with alias seed handling the head ~$5–10. Re-runs after `MAPPER_VERSION` bumps cost the same.

Each unique normalized `name` is resolved at most once per `MAPPER_VERSION` regardless of how many rows share it. With 25,912 unique strings against 101,570 rows, this is a ~4× reduction in LLM volume vs naive per-row resolution. Cache lives in the database — when the mapper resolves a string, it computes the answer once and `UPDATE`s every row sharing that normalized name.

### Code housing: lives inside `ingredients/`

The taxonomy mapper is added to the existing `ingredients/` workspace package rather than a new top-level package. `ingredients/` is already the Zone-2 worker that reads `recipes` and writes to `recipe_ingredients`; the mapper does the same with the same dependencies. One "runs on production data" package boundary is enough for now.

### Architecture: reconciling-worker pattern, polling for v1

The mapper inherits the same wake-up evolution path as the parser — polling worker for v1, `LISTEN/NOTIFY` later, Edge Function eventually — without changes to the data model. v1 is a Python CLI invoked manually or by cron.

## Schema changes

```sql
-- Migration: alter recipe_ingredients to carry mapping output.
alter table recipe_ingredients
  add column taxonomy_node_id bigint references taxonomy_nodes(id),
  add column mapper_source    text check (mapper_source in
    ('alias', 'lexical', 'llm', 'abstain')),
  add column mapper_version   text,
  add column mapper_at        timestamptz;

create index recipe_ingredients_taxonomy_idx
  on recipe_ingredients (taxonomy_node_id)
  where taxonomy_node_id is not null;
```

```sql
-- Migration: provenance for auto-created nodes.
create table taxonomy_provenance (
  node_id        bigint primary key references taxonomy_nodes(id) on delete cascade,
  source         text not null,         -- 'seed' | 'llm-mapper' | 'manual'
  mapper_version text,
  raw_string     text,                  -- the ingredient string that triggered creation
  prompt_hash    text,
  model_id       text,                  -- e.g. 'claude-haiku-4-5'
  created_at     timestamptz not null default now()
);
```

```sql
-- Migration: review queue for form proposals.
create table taxonomy_proposals (
  id                 bigserial primary key,
  raw_string         text not null,
  proposed_slug      text not null,
  proposed_parent_id bigint references taxonomy_nodes(id),
  candidates         jsonb not null,    -- [{node_id, display_name, similarity}]
  mapper_version     text not null,
  status             text not null default 'pending'
                     check (status in ('pending', 'approved', 'rejected')),
  decided_by         text,
  decided_at         timestamptz,
  created_at         timestamptz not null default now(),
  unique (raw_string, mapper_version)
);
```

`pg_trgm` is already enabled by [supabase/migrations/20260425193005_recipes_search_trgm.sql](../../../supabase/migrations/20260425193005_recipes_search_trgm.sql). The lexical layer reuses it; no additional extension required.

## Code structure

Inside `ingredients/src/ingredients/`:

```
ingredients/src/ingredients/
├── parser.py              (existing, unchanged)
├── eval_set.py            (existing, parser eval — unchanged)
├── cli.py                 (existing — gain a `map` subcommand)
├── ...
└── mapping/               (new submodule)
    ├── __init__.py
    ├── mapper.py          (MAPPER_VERSION, cascade orchestration)
    ├── alias_layer.py     (Layer 1)
    ├── lexical_layer.py   (Layer 2 — pg_trgm queries)
    ├── llm_layer.py       (Layer 3 — Anthropic SDK call)
    ├── prompt.py          (system prompt, candidate formatting)
    ├── proposals.py       (write/read taxonomy_proposals)
    └── eval_set.py        (mapper eval cases — separate from parser eval)
```

`mapper.py` orchestrates one cycle: pull unique normalized names lacking a current-version mapping, walk the cascade per name, batch-update `recipe_ingredients` rows that share each name. Layer modules are pure functions of `(name, parser_context, db_handle | api_client)` returning a typed result that `mapper.py` records.

## CLI surface

A `map` subcommand on the existing `ingredients` CLI. Flags mirror the parser (and the broader stage convention documented in [CLAUDE.md](../../../CLAUDE.md)):

```bash
# Main run — map every parsed-name string lacking a row at the current MAPPER_VERSION.
cd ingredients && uv run python -m ingredients.cli map

# Scoped to one site, with a row cap.
cd ingredients && uv run python -m ingredients.cli map --site punch --limit 500

# Dry-run preview, no DB writes.
cd ingredients && uv run python -m ingredients.cli map --dry-run

# Run the eval set; no DB writes. Use during rule iteration.
cd ingredients && uv run python -m ingredients.cli map --review

# Spot-check a sample of strings without committing.
cd ingredients && uv run python -m ingredients.cli map --sample 25

# After bumping MAPPER_VERSION, re-map everything left at the old version.
cd ingredients && uv run python -m ingredients.cli map --reset --except-version v1 --yes

# Walk the form-proposal review queue.
cd ingredients && uv run python -m ingredients.cli map review-proposals
```

Bare `--reset` clears the mapping columns on `recipe_ingredients` for rows in scope (the queue gates on `mapper_version IS NULL` rather than presence of an eval row).

`review-proposals` shows pending `taxonomy_proposals` one at a time:

```
proposal #42  raw_string="lemon zest"  proposed_slug="lemon_zest"
  parent: lemon (id=14)
  closest existing candidates:
    1. lemon_peel       sim=0.71
    2. lemon_twist      sim=0.65
    3. lemon            sim=0.61
[a]pprove / [r]eject / [s]kip / [e]dit slug:
```

Approval creates the node, writes a default alias, re-maps the rows that originally proposed it.

## Eval set & review workflow

Two eval files now: `ingredients/eval_set.py` (parser, existing) and `ingredients/mapping/eval_set.py` (mapper, new). Each mapper case has the shape:

```python
@dataclass
class MapperEvalCase:
    raw_name: str
    parser_unit: str | None
    site: str | None
    expect_node_slug: str | None        # exact-match expectation
    expect_source: str | None           # 'alias' | 'lexical' | 'llm' | 'abstain'
    expect_proposal_slug: str | None    # form-proposal expectation
```

Cases are added in two situations:
- A new pattern was taught (a head-string was added to alias seed; a new form was approved through the queue) → a should-resolve-as-X case.
- A wrong mapping was caught (lexical was confidently wrong; LLM picked a near-miss) → a should-abstain case plus, where applicable, the corrective alias or threshold change.

`--review` runs the eval against a fixture taxonomy (defined in `ingredients/tests/fixtures/`) so eval results are reproducible without depending on the production seed state.

## Error handling

- **LLM API failure:** retry with exponential backoff up to 3 attempts. After exhaustion, the string is left unmapped (no row written, no version recorded). Next CLI invocation retries it. The mapper does not write `mapper_source='abstain'` for a network failure — abstain is reserved for "model considered and declined."
- **LLM returns malformed JSON:** treated as failure (retried). Persistent malformed responses get logged and surface in CLI summary; the operator decides whether to escalate the call to Sonnet 4.6 or add an explicit alias.
- **LLM proposes a parent node that doesn't exist:** row abstains. No orphan auto-create. The proposed parent slug is logged so seed gaps surface during review.
- **Lexical layer threshold misfire (caught by eval):** add the offending case to the eval set; either tighten the threshold or seed the explicit alias. Both are valid responses; the eval suite enforces the choice.
- **Concurrent mapper runs:** rely on `UPDATE ... WHERE mapper_version IS NULL OR mapper_version <> :current` semantics; idempotent by version. Two operators racing produces no corruption, just wasted LLM calls.
- **Auto-created brand collides with later seed addition:** the seed-extension migration must check for existing `taxonomy_nodes` rows by slug before inserting. `taxonomy_provenance` exists partly to make this resolvable: the migration can choose to merge, replace, or rename the auto-created node and re-point `recipe_ingredients.taxonomy_node_id`.

## Testing approach

- **Unit:** layer modules are pure functions; tested without DB except `lexical_layer.py` which queries `pg_trgm`. `llm_layer.py` is tested with the Anthropic SDK mocked.
- **DB integration:** `ingredients/tests/test_mapping_db.py` against `TEST_DB_URL`, applying all migrations including the new ones. Fixture taxonomy seeded in test setup; cascade exercised end-to-end without LLM calls (using a stub).
- **Eval:** `ingredients/mapping/eval_set.py` driven by `--review`, runs against fixture taxonomy, asserts every case resolves to the expected node and source. CI gate.
- **Cost guard:** the mapper logs LLM call counts and token usage per run; CLI summary surfaces them. No automated cost cap in v1, but the operator sees the bill before re-running with `--reset`.

## Open / deferred

- **Audit-LLM pass over auto-created brands.** A second LLM (potentially Sonnet 4.6 or Opus) reviews `taxonomy_provenance` rows where `source='llm-mapper'` and flags hallucinations or wrong parents. Out of scope here; file as a follow-up once enough auto-creates exist to make the pass worthwhile.
- **Recipe-context use in LLM layer.** v1 sends parser context (unit, site) only. If we find LLM mistakes that recipe context (drink name, other ingredients in the same recipe) would have prevented, add it as a v2 signal.
- **Re-mapping triggered by node creation.** When a new node enters via approval or auto-create, the mapper currently re-resolves only strings that abstained or proposed it. A more aggressive "newly created node may absorb previously-resolved-elsewhere strings" pass is deferred.
- **Form proposals for non-citrus substances.** The form-review pattern works for any node, but the seed (separate spec) only covers citrus forms. If the eval surfaces gaps (e.g. `whiskey_neat` vs `whiskey_on_the_rocks`), they get added through the review queue.
- **Confidence scores on `recipe_ingredients`.** Not in v1. The `mapper_source` column already partitions rows into "deterministic" (alias) vs "best-effort" (lexical/llm). A numeric confidence would be useful only if a downstream consumer learned to threshold on it.
