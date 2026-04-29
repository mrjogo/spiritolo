# Spirits Taxonomy — Schema and Content Rules

Backs Track [B] in [future-direction.md](future-direction.md). Resolves free-text ingredient strings to canonical IDs (Track [D]) and supplies hard-constraint filters during search and substitution.

## Stance

**Lean taxonomy. Vector layer carries soft similarity.** If a concept is fuzzy, sensory, or stylistic, it is not a node.

The taxonomy exists to do three things vectors are bad at: (1) deterministic alias resolution, (2) hard-constraint filtering, (3) interpretable browse / explore surfaces. Everything else is the vector layer's job.

## Schema

Three tables, vanilla Postgres, no extensions. Works on Supabase as-is.

```sql
-- One row per concept: a category, a brand, an expression, a fresh ingredient.
taxonomy_nodes (
  id            bigint PRIMARY KEY,
  slug          text UNIQUE NOT NULL,         -- 'rye_whiskey', 'lemon', 'buffalo_trace_eagle_rare_10'
  display_name  text NOT NULL,                -- 'Rye Whiskey'
  role          text CHECK (role IN ('brand', 'expression')),  -- nullable; see Roles below
  created_at    timestamptz NOT NULL DEFAULT now()
)

-- Many-to-many parents. The DAG.
taxonomy_edges (
  parent_id     bigint NOT NULL REFERENCES taxonomy_nodes(id) ON DELETE CASCADE,
  child_id      bigint NOT NULL REFERENCES taxonomy_nodes(id) ON DELETE CASCADE,
  PRIMARY KEY (parent_id, child_id),
  CHECK (parent_id <> child_id)
)
-- Cycle prevention enforced at app level. Add a defensive trigger if needed.

-- Free-text strings the [D] mapper resolves to a canonical node.
-- Same alias may have multiple rows pointing at different nodes; mapper picks via context.
taxonomy_aliases (
  alias         text NOT NULL,
  node_id       bigint NOT NULL REFERENCES taxonomy_nodes(id) ON DELETE CASCADE,
  PRIMARY KEY (alias, node_id)
)
```

Recursive CTEs (`WITH RECURSIVE`) traverse the DAG. Add a materialized closure table only if recursion becomes a hotspot — at expected node counts (low thousands), it won't.

## Roles

A `role` marks a node's *role in the data model* — what kind of thing-in-the-schema it is, not what kind of substance it represents. Substance lives in the DAG. Soft groupings (smoky, brown liquor) belong to the vector layer.

Closed vocabulary, enforced by `CHECK`:

| Role | Meaning |
|---|---|
| `brand` | Node represents a manufacturer's brand line (Buffalo Trace, Smirnoff). |
| `expression` | Node represents a specific SKU / release (Eagle Rare 10, Smirnoff No. 21). |
| `NULL` | Everything else — categories, types, fresh ingredients. |

Adding a role requires a migration and a defensible reason. A candidate role must describe a node's *role in the schema*, never a sensory or stylistic property. If it describes how the node feels or groups by vibe, it's not a role.

## What belongs as a node

Add a node when the concept is:

- **Definitional or regulatory** — `whiskey`, `bourbon`, `rye_whiskey`, `london_dry_gin`, `single_malt_scotch`, `vermouth`, `amaro`.
- **A brand or expression** (`role = 'brand'` / `'expression'`) — `buffalo_trace`, `eagle_rare_10`. Hand-curate the well-known; let the [D] mapper auto-create the long tail when it exists.
- **A category whose children share substitution semantics** — `citrus` (parent of `lemon`, `lime`), `berries` (parent of `strawberry`, `raspberry`).

## What does not belong as a node

Do not add a node for:

- **Sensory descriptors** — smoky, rich, herbal, citrusy, bitter, dry, sweet.
- **Style or occasion** — summer drink, holiday, after-dinner, brunch.
- **Colloquial groupings** — brown liquor, white liquor, barrel-aged.
- **Single-node properties** — proof, ABV, vintage, age statement, mash bill, region. These describe one node and don't group; surface via the vector layer or a typed column when a real consumer wants them.

## Promotion rule

A soft grouping becomes a node **only when** a product surface (UI section, filter chip, curated list) is literally named after it. No speculative promotion. Adding the node later is cheap; removing one with edges and aliases attached is not.

## Aliases vs nodes

An alias is a free-text variant that resolves to a single existing node. Use aliases for:

- **Capitalization or punctuation variants** — `'anejo'` / `'añejo'`, `'peychaud''s'` / `'peychauds'`.
- **Language variants of one canonical name** — `'rosso vermouth'` / `'italian vermouth'` / `'sweet vermouth'`.
- **Generic substance terms covered by the brand-as-substance carve-out** — `'aromatic bitters'` → `angostura_bitters` (the cocktail community treats Angostura as the substance, not a brand call).

Do **not** use aliases for:

- **Brand or product names.** "Regan's Orange Bitters", "Bittermens Xocolatl Mole Bitters", "Fee Brothers Whiskey Barrel-Aged" are real products. Each gets its own `role='expression'` node, parented under its `role='brand'` node and (for non-brand-as-substance items) under the appropriate type node. Aliasing a product name to a type erases brand provenance, collapses what the [E] dedup variant-key is meant to keep distinct, and pre-empts the [D] mapper's auto-create flow for the long tail.

Hand-curate the well-known brand and expression nodes in the seed; the [D] mapper auto-creates the long tail when a recipe forces the issue.

## Antichain shape

`taxonomy_nodes.is_cluster_node` marks the cluster-identity cut for the [E] dedup pipeline. **The cut does not have to sit at uniform DAG depth.** Different branches mark different levels:

- For substance types where many brands cluster together (orange bitters, chocolate bitters, bourbon, london_dry_gin), `is_cluster_node` lives on the **type** node. Brand and expression descendants roll up to it.
- For brand-as-substance items (Angostura, Peychaud's, Campari, Aperol, Fernet-Branca, Chartreuse, Cynar, Suze, Bénédictine, Drambuie, Pimm's) — products the recipe community treats as a substance — `is_cluster_node` lives on the **expression**. The brand is its own `role='brand'` node above; there is no cluster-node type node intermediate.

Required invariant: no `is_cluster_node = true` node has an `is_cluster_node = true` ancestor. Checked at seed-load time; the dedup CLI refuses to run if violated.

Concrete example (the `bitters` family):

```
bitters (parent, role_default='bitters')
├── angostura (role='brand')
│   └── angostura_bitters (role='expression', is_cluster_node=true)   ← brand-as-substance
├── peychauds (role='brand')
│   └── peychauds_bitters (role='expression', is_cluster_node=true)   ← brand-as-substance
├── orange_bitters (is_cluster_node=true)                              ← type-level cluster
│   └── regans (role='brand')
│       └── regans_orange_bitters (role='expression')
├── chocolate_bitters (is_cluster_node=true)                           ← type-level cluster
│   └── ⟨expressions parented multi-parent: [chocolate_bitters, brand]⟩
└── creole_bitters (is_cluster_node=true)                              ← type-level cluster
    └── ⟨expressions parented multi-parent: [creole_bitters, brand]⟩
```

For multi-product brands (Bittermens, Fee Brothers, The Bitter Truth), the brand sits directly under the family parent (`bitters`) and each expression has two parents — its brand and its type — so the rollup deterministically lands at the type's cluster_node.

## Taxonomy vs vectors

| Task | Use |
|---|---|
| Resolve free-text ingredient → canonical ID | **Taxonomy** (deterministic alias lookup) |
| Filter "all whiskeys" / "all bourbons" | **Taxonomy** |
| Hard constraints (NA-only, vegan, allergen-free) | **Taxonomy** (typed columns added when needed) |
| Browse / explore by category | **Taxonomy** |
| Substitution candidate generation | **Vectors** |
| "Similar drinks" | **Vectors** |
| Sensory / stylistic groupings | **Vectors** |
| Substitution final ranking | **Hybrid** — vector candidates → taxonomy filter for hard constraints → re-rank |

**Never** use vectors for alias resolution or hard-constraint filtering.
**Never** use the taxonomy to express sensory similarity.
