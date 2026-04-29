# Recipe Dedup — Design

## Context

Per [docs/future-direction.md](../../future-direction.md), Track `[E]` deduplicates recipes so the website surfaces a single canonical entry per cocktail rather than 47 rows of "Negroni" from 47 sources. Dedup is the unlock that makes search, similarity, "completeness" tracking, and the eventual substitution / similar-drinks UI meaningful — without it, every downstream feature is dominated by near-duplicate noise.

Dedup operates as **identity**, not similarity. Cluster membership is a deterministic function of recipe content; ambiguity is resolved at audit time, not by a fuzzy threshold. Soft adjacency between clusters (substitution graph, "similar drinks") is the job of `[G]`/`[H]`, not this spec.

The product shape this spec serves: each cluster is a **stack** of cards. The card at the top is the canonical recipe (most-frequent ratios, no brand call-outs); cards below show interesting variants — different ratios, brand call-outs, modifier substitutions. Identical recipes within a stack collapse to a single card with a source count. Outside the stack, a graph of related drinks (substitutions, variations) is built later from cluster-to-cluster relationships.

## Decisions

### Identity model: joint key on `(canonical_name, role-tagged ingredient set)`

```
# Allow-list, not deny-list. Adding a new role value elsewhere in the
# codebase (for search filters, sensory tags, etc.) is safe by default —
# the new role does NOT enter the cluster key until someone explicitly
# adds it here and bumps DEDUP_VERSION.
INCLUDED_ROLES = {
    'base_spirit', 'modifier', 'citrus', 'sweetener',
    'bitters', 'wash', 'other',
}

def in_cluster_key(ing):
    if ing.role == 'garnish':
        return ing.taxonomy_node.is_defining_garnish
    return ing.role in INCLUDED_ROLES

cluster_key = sha256(canonical_json({
    'canonical_name': canonical_name,
    'ingredients': sorted([
        (ing.role, ing.antichain_node_id)
        for ing in recipe.ingredients if in_cluster_key(ing)
    ])
}))
```

Both axes are required.

- **Pure-ingredient identity fails on call spirits** — a Negroni saying "Tanqueray" and one saying "Bombay" both roll up to the same antichain node, but a Negroni saying "gin" doesn't have a brand to roll up; aggressive rollup over-clusters Old Tom Negroni with London Dry Negroni; cautious rollup under-clusters Tanqueray Negroni with generic-gin Negroni. There is no antichain depth that handles call spirits and definitional spirits both.
- **Pure-name identity fails on riffs and on collisions** — "House Special" with Negroni ingredients should not be a Negroni cluster member, and "Best Old Fashioned Recipe" should not be a separate cluster from "Old Fashioned."

The joint key gets the strengths of both. Names disambiguate when ingredients coincide (Negroni vs Cardinale on sweet/dry vermouth; Negroni vs Boulevardier on gin/bourbon). Ingredients disambiguate when names coincide ("House Special" with non-Negroni ingredients lands elsewhere).

The honest concession the joint key makes: **a Martinez made with London Dry will cluster with one made with Old Tom**, because the antichain rolls Old Tom and London Dry up to `gin` and the names match. This loses the cocktail-historian distinction. Acceptable because (a) the Old Tom call survives as a brand attribute on the recipe row, surfaced as in-stack variation, and (b) the audit pass flags clusters with unusually high in-stack ingredient diversity, which is the exact signal that catches sub-spirit-defining cases.

### Antichain: a curated cut through the taxonomy DAG

A new column `taxonomy_nodes.is_cluster_node boolean` marks the antichain — the set of nodes that are cluster identities. Each `recipe_ingredients.taxonomy_node_id` rolls up via the DAG to its nearest `is_cluster_node = true` ancestor (or itself, if it is one). That ancestor's id enters the cluster key.

The antichain is hand-curated content, not derived. The cut sits at "definitional substance" level and varies per branch:

- **Spirit families.** `bourbon`, `rye_whiskey`, `scotch_whisky`, `irish_whiskey`, `japanese_whisky`, `gin`, `vodka`, `white_rum`, `dark_rum`, `aged_rum`, `blanco_tequila`, `reposado_tequila`, `anejo_tequila`, `mezcal`, `cognac`, `armagnac`, `calvados`. (`whiskey`, `rum`, `tequila`, `brandy` parents are *not* cluster nodes — they're navigation parents.)
- **Gin sub-styles where definitional.** `london_dry_gin`, `old_tom_gin`, `plymouth_gin`, `genever`. Required content addition; current seed only has `gin`.
- **Vermouth.** `sweet_vermouth`, `dry_vermouth`, `blanc_vermouth` (already in seed).
- **Amari.** Each major amaro is its own cluster node: `campari`, `aperol`, `amaro_montenegro`, `cynar`, `fernet_branca`, `amaro_nonino`, plus the long tail. Required content addition; seed currently has only `amaro`.
- **Bitters.** `angostura_bitters`, `peychauds_bitters`, `orange_bitters`, plus `creole_bitters`, `chocolate_bitters`, `aromatic_bitters_other`. Required content addition; seed currently has only `bitters`.
- **Liqueurs / cordials.** `maraschino_liqueur`, `green_chartreuse`, `yellow_chartreuse`, `cointreau` (or `triple_sec` if Cointreau/Combier collapse), `creme_de_violette`, `creme_de_cassis`, `benedictine`, `drambuie`, `pimms_no_1`, etc.
- **Fortified wines.** `dry_sherry`, `oloroso_sherry`, `pedro_ximenez`, `lillet_blanc`, `lillet_rouge`, `madeira`, `port`, `cocchi_americano`.
- **Citrus juices** (form-nodes from D). `lemon_juice`, `lime_juice`, `orange_juice`, `grapefruit_juice`.
- **Sweeteners.** `simple_syrup`, `demerara_syrup`, `honey_syrup`, `agave_syrup`, `grenadine`. (Generic `sugar` and `honey` may or may not be antichain — reviewed during seed expansion.)
- **Definitional garnishes** (see *Garnish handling*). Antichain *and* `is_defining_garnish = true`.

`is_cluster_node` is **independent of `role`**. The antichain is a separate, orthogonal annotation on top of the taxonomy's existing structure. In practice:

- Most antichain members are `role = NULL` substance categories (`bourbon`, `london_dry_gin`, `sweet_vermouth`, `lemon_juice`).
- Brand-level nodes (`role = 'brand'`) almost always *roll up* to a substance-level antichain ancestor — Tanqueray rolls up to `london_dry_gin`, Maker's Mark rolls up to `bourbon`. They are not themselves antichain.
- A handful of products are commercially branded but *function as their own definitional substance* (Angostura, Peychaud's, Campari, Aperol, Fernet-Branca, Chartreuse). The taxonomy models these as **substance nodes** (`role = NULL`, `is_cluster_node = true`), with the brand-as-company captured via aliases. We prefer the substance modeling because the cluster identity is what the recipe community recognizes (a recipe says "Campari," not "the Davide Campari Group's flagship aperitivo"). If a separate `role = 'brand'` or `role = 'expression'` node exists for the same name, it is a sibling in the data model and the alias mapper resolves user-facing names to the substance node.

A check or app-level invariant enforces antichain integrity: no `is_cluster_node = true` node has another `is_cluster_node = true` ancestor.

The full antichain content is enumerated in the taxonomy seed migration, not here. This spec lists the *shape* of what must be marked.

**Antichain v1 success criterion.** The seed expansion is "done" when ≥95% of `recipe_ingredients` rows with `role IN ('base_spirit', 'modifier', 'bitters')` resolve (after rollup) to a node where `is_cluster_node = true`. Long-tail substances that don't meet the bar surface as audit-flagged underspecified clusters and are added incrementally. This bound prevents the seed work from expanding open-endedly and gives a measurable definition of "ready to ship E."

### Recipes referencing nodes above the cut: audit, do not block

Some recipes will resolve only to a node that has antichain descendants but is not itself one — e.g., a recipe specifying "amaro" generically when the antichain sits at individual amari. The roll-up function returns the node itself (the only legal answer) and the cluster key proceeds. The audit pass flags the row: `underspecified_ingredient = true`. Reviewers either upgrade the resolution by hand, accept the underspecified cluster, or flag the source recipe for re-extraction. No block in the pipeline.

### Two-level fold: cards as a derived view inside `recipe_clusters`

A **cluster** is the same drink (joint key match). A **card** is the same recipe within a cluster — same cluster key, same amounts, same brand call-outs. Multiple sources publishing the identical Negroni at 1oz/1oz/1oz collapse to one card with `source_count = N`. The same Negroni at 1.5oz/1oz/1oz is a separate card in the same cluster.

Cards are **not stored as a table** in v1. The cluster compute writes a `card_key` column on each `recipes` row; cards are the equivalence classes of recipes sharing `(cluster_id, card_key)`. A view `recipe_cards` aggregates these for the read path. Materializing as a table is a follow-up if query patterns prove that the aggregation is hot.

Card key:

```
card_key = sha256(canonical_json({
    'cluster_key': cluster_key,
    'ingredients': sorted([
        (ing.role,
         ing.antichain_node_id,
         ing.taxonomy_node_id,    # the specific node D resolved to
         ing.amount,
         ing.amount_max,
         ing.unit)
        for ing in recipe.ingredients if in_cluster_key(ing)
    ])
}))
```

`taxonomy_node_id` is whatever D resolved the ingredient to — for a recipe specifying "Tanqueray" it's the `tanqueray` brand node; for one specifying just "gin" it's `gin`. This makes a Tanqueray Negroni and a Bombay Negroni different cards in the same cluster (same `antichain_node_id = london_dry_gin`, different `taxonomy_node_id`), while two Tanqueray Negronis collapse to the same card. `amount` distinguishes ratio variants. Recipes with no brand specification share a card when their amounts and units agree.

The UI renders the cluster's representative card on top, with the rest as expand-to-see variants. Identical-recipe duplicates within a card show as a source count.

### Roles on ingredients

`recipe_ingredients.role` is a closed-vocabulary tag added by E:

| Role | In cluster key | Examples |
|---|---|---|
| `base_spirit` | yes | bourbon, gin, mezcal |
| `modifier` | yes | sweet vermouth, Campari, maraschino |
| `citrus` | yes | lemon juice, lime juice |
| `sweetener` | yes | simple syrup, honey, demerara |
| `bitters` | yes | Angostura, Peychaud's, orange bitters |
| `wash` | yes | absinthe rinse, smoke wash |
| `dilution` | **no** | ice, soda water, hot water |
| `garnish` | configurable | twist (no), cocktail onion (yes) |
| `other` | yes | unclassifiable; flagged for review |

**Role is a closed vocabulary tied to dedup.** Adding new values requires (a) a migration altering the CHECK constraint, (b) explicit consideration of whether the new role should enter the cluster key (see `INCLUDED_ROLES` above — additions there are *opt-in*, so an unrelated team adding a role for a search-filter feature won't accidentally shift cluster identities), and (c) a `DEDUP_VERSION` bump if the cluster-key membership changes.

Substance *attributes* that aren't about how the ingredient is used in the drink (ABV, region, color, sensory profile, organic, allergen) belong on `taxonomy_nodes` (as columns or a separate tag table), not as `role` values. Mixing the two leads to category errors — a node is "Campari" with attributes "high-abv, bitter, Italian" and a usage role of "modifier"; conflating the latter two muddles both.

Role classification is deterministic in code: a function over `(taxonomy_node_id, amount, unit, position)`. Three layers, in order:

1. **Taxonomy default.** `taxonomy_nodes.role_default` (new column, nullable) stores the role for nodes whose role is unambiguous from substance — `bourbon` → `base_spirit`, `lemon_juice` → `citrus`, `simple_syrup` → `sweetener`, `angostura_bitters` → `bitters`, form-node garnishes → `garnish`. Most rows resolve here.
2. **Contextual rules.** A small set of hardcoded overrides for known edge cases:
   - Bitters substance with amount ≥ 1.5 oz → `base_spirit` (Trinidad Sour).
   - Vermouth or fortified wine in position 1 with amount ≥ 1.5 oz → `base_spirit` (Reverse Manhattan, Adonis, Bamboo).
   - "Rinse"/"spritz" hint in raw text + tiny amount → `wash`.
   - Position 1, amount ≥ 1.5 oz, no `role_default` set → `base_spirit` (heuristic for unclassified substances).
3. **Default `other`.** Everything else gets `role = 'other'` and `role_source = 'default'`. These rows surface in the audit summary as "needs taxonomy work" rather than blocking the pipeline.

No LLM in the role classifier. **Role classification runs as a sub-step of cluster compute**, not as an independent stage — the work is small (a pure function with a tiny taxonomy lookup) and dedup is its only consumer in v1. The `recipe_ingredients.role` column is still written and remains available for downstream features (search filters, similarity weighting), but it shares the `DEDUP_VERSION` lifecycle. If a future feature needs to invalidate roles independently of clusters, role-tag can be split into its own stage at that point — the data shape doesn't change, only the orchestration.

### Garnish handling: `is_defining_garnish` allowlist

A new column `taxonomy_nodes.is_defining_garnish boolean default false`. Set to `true` only for garnishes that change the drink's identity:

- `cocktail_onion` (Gibson)
- `salt_rim`
- `sugar_rim`
- `chili_rim` / `tajin_rim`
- (Long tail added by audit as we discover them.)

The cluster key includes a garnish row only when the resolved node is a defining garnish. Stylistic garnishes (twist, peel, wedge, sprig, cherry, olive) are filtered out regardless of recipe. The UI may still surface the stylistic garnish on the recipe card; it just doesn't enter the cluster identity.

The list grows slowly through the audit signal "stylistic-garnish recipes mismatched with otherwise-identical neighbors that lack the garnish."

### Name normalization: phased cascade, deterministic first

Cocktail names need normalization before they can join a cluster key. Editorial titles ("Best Old Fashioned Recipe"), articles ("The Negroni"), generic suffixes ("Negroni Cocktail"), parentheticals ("Negroni (Italian Aperitivo)"), typos ("Daquiri") — all of these need to map to the canonical name.

Three layers, **phased**:

| Phase | Layer | Source value | Mechanism |
|---|---|---|---|
| 1 | `alias` | `cocktail_aliases.canonical_name` | exact match after light normalization (lowercase, strip punctuation, drop stop-set: "the", "classic", "best", "perfect", "cocktail", "recipe") |
| 1 | `lexical` | `cocktail_aliases.canonical_name` | `pg_trgm` similarity. Accept only when `top1.similarity ≥ 0.92 AND top1.similarity > 1.5 × top2.similarity` |
| 2 | `llm` | LLM-proposed canonical | provider TBD, see *LLM provider deferral* below |

Phase 1 runs as part of every dedup invocation — cheap, idempotent, no external dependencies. Strings that don't resolve get `source = 'pending_llm'` and stop. Phase 2 is a separate subcommand operating on the `pending_llm` queue.

**Phase 2 ships as part of v1, not as an opt-in extension.** Editorial titles ("Best Old Fashioned Recipe", "How to Make a Perfect Manhattan") are common enough that without phase 2 the dedup feature visibly under-clusters. Cost is bounded: a worst-case run against ~10K residuals through Claude Haiku at ~$0.001/call is ~$10; through Ollama qwen3:14b it is free. The phasing exists for cost visibility and for the option to hand-curate small queues as aliases — not as a deferral mechanism for shipping v1.

Resolution is written directly onto `recipes` (`canonical_name`, `canonical_name_source`, `normalizer_version`, `normalized_at`). This mirrors D's pattern — D writes resolution + source + version directly onto `recipe_ingredients` rather than maintaining a separate cache table. Re-runs find unresolved rows by `canonical_name IS NULL OR normalizer_version <> current`. The "canonical name" pool builds bottom-up: hand-seed the top ~100–200 well-known cocktails (Negroni, Old Fashioned, Manhattan, etc.) into `cocktail_aliases`, let LLM and alias additions grow the list as new drinks appear in the data.

Mirrors D's cascade pattern; differs in being phased rather than eager, because E's LLM volume is not pre-known and the head-cover ratio for recipe names is likely high enough that phase 1 alone covers most rows.

### LLM provider deferral

Phase 2's provider is **deferred** until phase 1's residual count is known. The `--provider` flag accepts at minimum:

- `ollama` — qwen3:14b (already running locally for URL classification). Free, lower-quality on niche cocktail knowledge, sufficient for "is this Negroni-shaped?" judgments on the long tail.
- `claude` — Anthropic Claude Haiku 4.5 with optional Sonnet 4.6 escalation. Mirrors D. Modest cost.

The CLI prints residual count and top-N residuals before the LLM call so an operator can decide whether to send to LLM, hand-curate as aliases, or skip.

Versioned `NORMALIZER_VERSION = "v1"`. Bumping it requires `--reset --except-version v1` against `recipes.normalizer_version`.

### Audit signals

Five queries, surfaced via a CLI subcommand. None require additional tables.

- **Name divergence within cluster** — clusters where recipes carry many distinct raw names. Could indicate a real edit-distance miss in normalization, or a real cluster with intentionally-different titles. Threshold: `count(distinct r.name) >= 4`.
- **Same canonical name across clusters** — `recipe_clusters` rows sharing `canonical_name`. Real cases (Negroni / White Negroni / Negroni Sbagliato — all use "Negroni" loosely in some sources). Surfaces ingredient-set differences for review.
- **Underspecified-ingredient flag** — recipes that hit a node above the antichain. A small list per cluster suggests the cluster is fine; a high concentration suggests source data is too vague.
- **High in-stack ingredient diversity** — clusters where the antichain set is consistent but specific brands or sub-spirits vary unusually widely. Surfaces the "is a sub-spirit definitional here?" cases (Martinez with mixed gin sub-styles).
- **Singleton clusters with editorial-looking names** — single-recipe clusters where the raw name contains "best", "perfect", "ultimate", suggesting a normalization miss.

**Owner / workflow.** The whole dedup pipeline is operator-invoked (CLI), and so is audit. After each `cluster` run, the operator runs `cluster audit` and triages the output by hand — adding aliases, marking definitional garnishes, or filing follow-ups. No automated remediation in v1. A web review surface is deferred (see *Open / deferred*).

### Versioning: two constants

- `NORMALIZER_VERSION = "v1"` — name normalization (alias + lexical + LLM layers, phase 1 + phase 2)
- `DEDUP_VERSION = "v1"` — cluster compute (which includes role classification and card-key derivation)

Each is independently re-runnable with `--reset --except-version <prior>`. Bumping `DEDUP_VERSION` re-derives roles, cluster keys, and card keys but doesn't re-resolve names. Bumping `NORMALIZER_VERSION` invalidates clusters too (changed names → changed cluster keys); the operator must re-run `cluster --reset --except-version v1` afterward.

### Hard prerequisites

E hard-blocks on:

- **D shipping its v0** — `recipe_ingredients` rows must carry `taxonomy_node_id` from at least D's alias + lexical layers. Coverage need not be 100%; the dedup pipeline tolerates `taxonomy_node_id IS NULL` rows by treating them as `role = 'other'` and excluding them from the cluster key (with a flag for audit). But the typical recipe must resolve enough ingredients for the cluster key to be meaningful.
- **Taxonomy seed expansion** — the seed in [supabase/seeds/taxonomy_nodes.sql](../../../supabase/seeds/taxonomy_nodes.sql) must include the antichain content listed under *Antichain* above (gin sub-styles, individual amari, individual bitters, key liqueurs, fortified wines). The migration that adds `is_cluster_node`, `role_default`, and `is_defining_garnish` is part of this E spec; the *content* edits to the seed are an E deliverable, but coordinated with D's parallel taxonomy expansion to avoid conflict.

E does **not** modify D's mapper code. E consumes D's output. The taxonomy seed is shared territory; E's seed edits go in alongside D's, on a coordinated branch.

### Post-D auto-create cleanup (substance promotion)

D auto-creates nodes for unmatched ingredient strings. By the time E begins, D has likely created `role='brand'` or `role='expression'` nodes for some commercially-branded-but-definitional substances (Campari, Aperol, Angostura, Peychaud's, Fernet-Branca, Chartreuse, etc.). E's antichain modeling expects these as `role=NULL` substance nodes, not brand/expression nodes — but pre-seeding before D would require coordinating with D's already-in-flight work, which is too entangled.

Instead, E ships a one-shot **substance-promotion procedure** that runs after D and before E's first cluster compute:

1. **Identify candidates.** Query `taxonomy_provenance` for `source = 'llm-mapper'` rows whose `taxonomy_nodes.role IN ('brand', 'expression')` and whose display_name matches a hand-curated allowlist of "definitional substance" names (Campari, Aperol, Fernet-Branca, Angostura, Peychaud's, Chartreuse, Cynar, Suze, Bénédictine, Drambuie, Pimm's, etc.).
2. **Promote each.** Set `role = NULL`, `is_cluster_node = true`. Re-parent if needed (e.g., point `campari` directly under `amaro`). Update aliases.
3. **Re-point recipe_ingredients.** Any rows whose `taxonomy_node_id` points at a now-promoted node remain valid; no row updates needed (the node id didn't change, just its role and antichain flag).
4. **Audit log.** Each promotion writes a row to a `taxonomy_provenance`-style log so the change is reviewable.

A CLI subcommand (`promote-substances`) walks the allowlist interactively, surfacing each candidate for confirmation before promoting. The allowlist lives in code so it's reviewable in PR. The procedure is one-shot for v1; new substances added later go through the same CLI.

This is option (c) from the design discussion — chosen because pre-seeding before D would entangle the two specs, and post-process cleanup keeps D's spec untouched at the cost of a small E-side migration step.

## Schema changes

```sql
-- 1. Antichain marker, role default, defining-garnish flag.
alter table taxonomy_nodes
  add column is_cluster_node     boolean not null default false,
  add column role_default        text,
  add column is_defining_garnish boolean not null default false;

-- App-level invariant (or trigger): no is_cluster_node node has an
-- is_cluster_node ancestor in taxonomy_edges.
```

```sql
-- 2. Role on recipe_ingredients (written by cluster compute; shares DEDUP_VERSION).
alter table recipe_ingredients
  add column role         text check (role in (
                            'base_spirit', 'modifier', 'citrus',
                            'sweetener', 'bitters', 'dilution',
                            'garnish', 'wash', 'other')),
  add column role_source  text check (role_source in
                            ('default', 'rule', 'manual'));

create index recipe_ingredients_role_idx
  on recipe_ingredients (role) where role is not null;
```

```sql
-- 3. Name normalization output written directly onto `recipes`.
--    Mirrors D's pattern of writing resolution + source + version onto the
--    source table (`recipe_ingredients` for D, `recipes` for E) — no
--    separate cache table needed.
alter table recipes
  add column canonical_name        text,
  add column canonical_name_source text check (canonical_name_source in
                                     ('alias', 'lexical', 'pending_llm',
                                      'llm', 'abstain')),
  add column normalizer_version    text,
  add column normalized_at         timestamptz;

create index recipes_pending_normalize_idx
  on recipes (canonical_name_source) where canonical_name_source = 'pending_llm';
```

```sql
-- 4. Cocktail alias table — exact analogue of taxonomy_aliases.
--    Used by Phase-1 alias-layer lookups and grown by Phase-2 LLM resolutions.
create table cocktail_aliases (
  alias          text not null,
  canonical_name text not null,
  source         text not null check (source in ('seed', 'llm', 'manual')),
  created_at     timestamptz not null default now(),
  primary key (alias, canonical_name)
);

create index cocktail_aliases_canonical_idx
  on cocktail_aliases (canonical_name);
```

```sql
-- 5. Cluster identity (the stack).
create table recipe_clusters (
  id                       bigserial primary key,
  cluster_key              text unique not null,
  canonical_name           text not null,
  ingredient_set           jsonb not null,           -- sorted [{role, node_id, slug}]
  representative_recipe_id bigint references recipes(id),
  recipe_count             int not null default 0,
  source_count             int not null default 0,   -- distinct sites
  dedup_version            text not null,
  created_at               timestamptz not null default now()
);

create index recipe_clusters_canonical_idx on recipe_clusters (canonical_name);
```

```sql
-- 6. Card-level fold as a view; equivalence classes of recipes sharing
--    (cluster_id, card_key). Materializing as a table is a follow-up if
--    query patterns prove the aggregation is hot.
create view recipe_cards as
  select
    cluster_id,
    card_key,
    min(id)                       as representative_recipe_id,
    count(*)                      as recipe_count,
    count(distinct site)          as source_count
  from recipes
  where cluster_id is not null and card_key is not null
  group by cluster_id, card_key;
```

```sql
-- 7. Recipe → cluster assignment + card_key (cards are derived).
alter table recipes
  add column cluster_id    bigint references recipe_clusters(id),
  add column card_key      text,
  add column dedup_version text;

create index recipes_cluster_idx
  on recipes (cluster_id) where cluster_id is not null;
create index recipes_cluster_card_idx
  on recipes (cluster_id, card_key) where cluster_id is not null;
```

```sql
-- 8. Public projection.
create or replace view recipes_public as
  select id, source_url, site, name, author, image_url, jsonld,
         cluster_id, card_key
  from recipes;
```

The web UI gains the ability to group by `cluster_id` and `card_key` without further schema changes (or to query `recipe_cards` for the aggregated view). RLS on `recipes` already blocks anon reads of the base table; the view is the public surface.

## Code structure

E lives inside the existing `ingredients/` package. The mapper is already there; dedup is the next stage operating on the same data and uses the same infrastructure (DB connection helpers, CLI conventions, eval set runner).

```
ingredients/src/ingredients/
├── parser.py                        (existing)
├── eval_set.py                      (existing — parser eval)
├── cli.py                           (gain dedup subcommands)
├── mapping/                         (existing — D)
│   ├── mapper.py
│   ├── alias_layer.py
│   ├── lexical_layer.py
│   ├── llm_layer.py
│   ├── prompt.py
│   ├── proposals.py
│   └── eval_set.py
└── dedup/                           (new — E)
    ├── __init__.py
    ├── normalizer.py                (NORMALIZER_VERSION; phase-1 alias + lexical)
    ├── normalizer_llm.py            (phase-2 LLM provider abstraction)
    ├── role_classifier.py           (helper invoked from cluster.py)
    ├── cluster.py                   (DEDUP_VERSION; role tagging + key hashing + cluster compute)
    ├── promote_substances.py       (one-shot post-D substance-promotion CLI)
    ├── audit.py                     (the five audit queries)
    ├── prompt.py                    (LLM prompt for name normalization)
    └── eval_set.py                  (dedup eval cases — separate from parser/mapper)
```

`normalizer.py` takes distinct `recipes.name` strings, runs the phase-1 cascade (alias + lexical), and writes `canonical_name`/`canonical_name_source`/`normalizer_version` directly onto each `recipes` row. `normalizer_llm.py` is the phase-2 orchestrator; it imports `LLMProvider` and the Claude/Ollama implementations from `mapping/` (see *Reuse from [D]*) rather than duplicating them. `role_classifier.py` is a pure function over `(taxonomy_node_id, amount, unit, position)` plus a small DB lookup for `taxonomy_nodes.role_default`; it is imported by `cluster.py` rather than orchestrated as its own stage. `cluster.py` reads the joined view of `recipes` × `recipe_ingredients` × `taxonomy_nodes`, runs the role classifier, computes cluster and card keys, populates `recipe_clusters`, and writes `cluster_id` and `card_key` back to `recipes`. `promote_substances.py` is the post-D auto-create cleanup procedure.

## Reuse from [D]

D shipped a clean LLM cascade infrastructure. E reuses the low-level pieces directly rather than parallel-implementing them; only the domain-specific layers (cocktail-name normalization rules, the cluster compute) are E-original.

| Concern | Reuses from D | E adds |
|---|---|---|
| LLM provider abstraction | `ingredients.mapping.llm_provider.LLMProvider` (Protocol), `ProviderResult` dataclass | nothing — same Protocol used as-is |
| LLM provider implementations | `mapping.llm_provider_claude.ClaudeProvider`, `mapping.llm_provider_ollama.OllamaProvider` | nothing — imported and instantiated |
| Retry-with-backoff around an LLM call | `mapping.llm_resolver._resolve_with_retry` (lift to module-level export, or extract to `mapping/llm_runtime.py` if a third caller appears) | nothing |
| Light-string normalization | `mapping.normalize.normalize_name` (lowercase + whitespace) | a heavier `dedup.normalize.normalize_cocktail_name` that wraps `normalize_name` and adds stop-word stripping ("the", "best", "classic", "cocktail", "recipe"), parenthetical removal, punctuation handling appropriate to recipe titles |
| Alias-layer SQL pattern | `mapping.alias_layer.resolve_alias` shape (parameterized table) | identical shape against `cocktail_aliases` instead of `taxonomy_aliases`; small helper module `dedup.alias_layer` |
| Lexical-layer pg_trgm pattern | `mapping.lexical_layer` shape (threshold + tiebreaker) | identical shape against `cocktail_aliases.alias` instead of `taxonomy_nodes.display_name ∪ taxonomy_aliases.alias` |
| Typed cascade results | `mapping.types.Resolved`/`Pending`/`Abstain` shape | E's analogue in `dedup/types.py` carries `canonical_name: str` instead of `taxonomy_node_id: int`; otherwise identical |
| CLI argument plumbing | `spiritolo_common.cli_common.add_reset_args`, `confirm_reset`, `describe_reset_scope` | nothing — used directly |
| Run summary + progress | `spiritolo_common.summary.print_summary`, `spiritolo_common.progress.make_progress` | nothing — used directly |
| Supabase connection | `spiritolo_common.supabase_client` | nothing — used directly |
| Eval-against-fixture pattern | `mapping.eval_fixture` + `mapping.eval_set` shape | E's analogue: `dedup/eval_fixture.py` (a fixture taxonomy with antichain marked + a fixture cocktail-alias seed) and `dedup/eval_set.py` |

**Verb naming.** Phase-2 LLM CLI is `resolve-pending`, mirroring D's `map resolve-pending`. The `--provider {claude, ollama}` flag, residual-count confirmation prompt, and `--limit` semantics are the same.

**What is *not* reused.** D's `mapping/prompt.py` is taxonomy-specific (candidates with parents). E's prompt asks "given this raw recipe title and these candidate canonical cocktail names, pick one or propose a new one"; the shape diverges enough to warrant a separate `dedup/prompt.py`. Similarly, D's `mapping/proposals.py` (`taxonomy_proposals` queue for form-node review) doesn't map cleanly onto cocktail-name proposals — for v1, LLM-proposed canonical names auto-add to `cocktail_aliases` with `source='llm'` and the audit pass surfaces them, no human-review queue. If LLM cocktail-name hallucinations turn out to be a real problem, a `cocktail_proposals` mirror of `taxonomy_proposals` is the natural follow-up.

## CLI surface

New subcommands on the existing `ingredients` CLI. Flags mirror the parser, mapper, and the broader stage convention documented in [CLAUDE.md](../../../CLAUDE.md).

```bash
# Phase 1: alias + lexical name normalization.
cd ingredients && uv run python -m ingredients.cli normalize-names

# Inspect what's pending LLM.
cd ingredients && uv run python -m ingredients.cli normalize-names list-pending
cd ingredients && uv run python -m ingredients.cli normalize-names list-pending --limit 50

# Phase 2: send pending strings to LLM (mirrors D's `map resolve-pending`).
cd ingredients && uv run python -m ingredients.cli normalize-names resolve-pending --provider ollama
cd ingredients && uv run python -m ingredients.cli normalize-names resolve-pending --provider claude

# Eval set, no DB writes.
cd ingredients && uv run python -m ingredients.cli normalize-names --review

# One-shot: walk auto-created brand/expression nodes that should be substances and promote them.
cd ingredients && uv run python -m ingredients.cli promote-substances

# Cluster compute. Tags roles, computes cluster/card keys, writes recipe_clusters,
# stamps cluster_id and card_key on recipes.
cd ingredients && uv run python -m ingredients.cli cluster

# Audit. Prints the five signal queries.
cd ingredients && uv run python -m ingredients.cli cluster audit

# Run normalize + cluster in order.
cd ingredients && uv run python -m ingredients.cli dedup-all

# Standard flags on each subcommand:
--site SITE  --limit N  --dry-run  --review  --sample N
--reset [--except-version V] [--older-than ISO_TS] [--yes]
```

`--reset` semantics:

- `normalize-names --reset` nulls `recipes.canonical_name`, `canonical_name_source`, `normalizer_version`, `normalized_at` for rows in scope.
- `cluster --reset` clears `recipe_clusters`, nulls `recipes.cluster_id` / `card_key` / `dedup_version`, and nulls `recipe_ingredients.role*` columns in scope. (Roles are part of the cluster compute output and reset together.) Does not touch upstream tables.

## Eval set & review workflow

A new file `ingredients/src/ingredients/dedup/eval_set.py`. Each case has the shape:

```python
@dataclass
class DedupEvalCase:
    raw_name: str
    parsed_ingredients: list[ParsedIngredient]   # (taxonomy_node_slug, amount, unit, position)
    expect_canonical_name: str | None            # name normalizer expectation
    expect_normalizer_source: str | None         # 'alias' | 'lexical' | 'pending_llm' | 'llm'
    expect_cluster_key: str | None               # full hash; or None to assert "matches cluster X"
    expect_cluster_label: str | None             # e.g. "negroni-classic"
    expect_role_per_ingredient: list[str] | None
```

Cases are added in three situations:

1. A new pattern was taught (alias seed addition, role rule, garnish addition) → a should-resolve-as-X case.
2. A wrong cluster was caught (Negroni and Cardinale collided; House Special joined a Negroni stack) → a should-not-cluster case, plus the corrective change (alias, antichain edit, role override).
3. A new audit signal fired meaningfully → an eval that asserts the signal *fires* on the relevant input.

`--review` runs eval cases against a fixture taxonomy (defined in `ingredients/tests/fixtures/`) so eval results are reproducible without depending on production seed state. Same pattern as D.

## Error handling

- **D-mapper output incomplete.** Recipes with `taxonomy_node_id IS NULL` on some rows aren't blockers. The cluster compute treats them as `role = 'other'` and excludes them from the key, then flags the cluster as "partially mapped" in the audit summary. Adding more D coverage in a later run upgrades the cluster on the next `cluster --reset`.
- **Antichain integrity violation.** A taxonomy seed edit that creates an `is_cluster_node = true` node with an `is_cluster_node = true` ancestor must be caught at seed-load time (a CHECK or a startup integrity query). The dedup CLI refuses to run if this query returns rows.
- **Roll-up traversal cycle.** Should be impossible by `taxonomy_edges` invariants, but a defensive `WITH RECURSIVE` depth cap (e.g., 10) protects against pathology.
- **LLM API failure (phase 2).** Same as D: retry 3× with backoff, leave `pending_llm` unchanged on exhaustion. No `abstain` write for network errors — `abstain` is reserved for "model considered and declined."
- **LLM proposes a canonical name not in `cocktail_aliases`.** Auto-add the alias with `source = 'llm'`. The audit pass surfaces these for human review in batch (analogous to D's `taxonomy_provenance`).
- **Concurrent dedup runs.** The cluster compute is idempotent given fixed inputs: every (joint key) maps to one cluster_key. Two operators racing produce duplicate work, not corruption. UPSERT on `cluster_key` resolves the writes.
- **Underspecified ingredients.** Recipes resolving only to nodes above the antichain produce a cluster key with the parent node verbatim. The audit flags this; no block.

## Testing approach

- **Unit.** `normalizer.py` (alias + lexical layers, pure-function entry points), `role_classifier.py` (pure function table-driven), `cluster.py` (key hashing) tested without DB. `normalizer_llm.py` mocked at the provider boundary.
- **DB integration.** `ingredients/tests/test_dedup_db.py` against `TEST_DB_URL`, applying all migrations (E's plus D's plus prior). Fixture taxonomy seeded in test setup; cascade exercised end-to-end without LLM (using a stub).
- **Eval.** `ingredients/dedup/eval_set.py` driven by `--review`, runs against fixture taxonomy + fixture recipes, asserts every case lands in the expected cluster / card / role. CI gate.
- **Cost guard.** Phase 2 LLM cost surfaced in CLI summary (call count, token usage). Operator sees the bill before re-running with `--reset`.
- **Antichain integrity.** A unit test runs the integrity query against the production seed and fails CI if it finds violations.

## Open / deferred

- **Promotion / demotion of clusters.** Hand-merging two clusters that should be one (or splitting one that should be two) has no UI yet. v1 stores cluster identity but does not provide override tooling. A `recipe_cluster_overrides` table or a `manual_cluster_id` column on `recipes` is the natural extension when curators arrive.
- **Representative-recipe scoring.** v1 picks the cluster's representative recipe by simple heuristic (most-frequent ratios, fall back to highest-source-count card). A scored representative (using the existing `classify_drink_runs.score`, source quality, image presence) is a small follow-up.
- **Audit workflow.** v1 ships the five queries via a CLI summary. A web-based audit/review surface — show flagged clusters, click to inspect, propose a merge or split — is deferred.
- **Inter-cluster relationships.** Substitution edges and "similar drinks" are `[G]`/`[H]`. v1 stops at within-cluster identity.
- **Re-running clustering as new recipes land.** v1 expects the operator to invoke `cluster` after parser / mapper runs. A reactive trigger (`LISTEN/NOTIFY`, Edge Function) is deferred.
- **Form-level distinctions in cluster key.** v1 treats `lemon_juice` and `lemon` (whole / wedge) as different antichain nodes — different cluster keys. Edge case: a "Whiskey Sour" recipe specifying a "lemon wedge" instead of "lemon juice" would split off into its own cluster despite intent. The audit pass surfaces these; canonicalization is deferred to a form-aware roll-up if the data shows it matters.
- **Pre-seeding the canonical-name list.** v1 hand-seeds the top ~100–200 well-known cocktails. Curating that list is deferred to implementation; the IBA list, the *Death & Co* index, and similar canonical-cocktail compilations are reasonable starting points.
- **Status snapshot.** A real measurement of unique `recipes.name` count and the head-distribution shape — analogous to D's "25,912 unique strings, top 15 = ~16% of rows" — is gathered during implementation, not at design time, because the parser / mapper output is still in flux.
