# Curator cross-links: recipe ↔ taxonomy

Connect the two curator-facing surfaces — RecipeDetail (`/recipes/:id`) and Taxonomy (`/taxonomy`) — so curators can walk in either direction without leaving the keyboard. On a recipe, the parsed/structured form of every ingredient line shows next to its raw text and links to the taxonomy node it mapped to. On a taxonomy node, the recipes that reference it are listed and link back. URL state on the taxonomy page reflects the current focus, so curator clicks are bookmarkable and the back button works.

This is curator-only. Non-admins see the existing pages with no behavior change.

## Goals

- On `/recipes/:id`, render a structured panel aligned 1:1 with `jsonld.recipeIngredient[i]` lines, sourced from `recipe_ingredients` joined by `position`. Admin-only.
- The structured row's `name` deep-links to `/taxonomy?node=<slug>` when the row has a `taxonomy_node_id`, opening the taxonomy page with that node focused.
- On `/taxonomy`, the pinned `NodeCard` lists every recipe whose `recipe_ingredients` resolve to the focused node. Each entry links back to `/recipes/:id`.
- Taxonomy URL state stays in sync with focus: clicking a node pushes `?node=<slug>`; clicking an edge pushes `?edge=<parent_slug>~<child_slug>`; clicking the background clears both. Mounting with a param sets initial focus.
- Header gains an inconspicuous `admin` chip next to "Sign Out" when `useIsAdmin()`.
- Server-side: tighten `recipe_ingredients` so non-admin authenticated users cannot read it. Move it from RLS tier (a) "eventually anon" to tier (c) "admin only".

## Non-goals

- No public/anon access to parsed ingredient data. Tightening, not relaxing.
- No editing UI. The structured panel is read-only; mapping/reparsing happens via CLI tools.
- No virtualization or pagination of the recipe list under a focused node — straight scroll is enough at expected sizes (~hundreds at most).
- No new `recipe_ingredients_public` view. PostgREST embeds + a slightly extended column grant cover both queries.
- No slug-character changes (underscores stay; the long-talked-about hyphen rename is a separate feature).

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│ /recipes/:id  (RecipeDetail)                                              │
│                                                                           │
│   ┌──────────── recipes_public ────────────┐                              │
│   │ id, source_url, site, name, jsonld …  │                              │
│   └────────────────────────────────────────┘                              │
│                                                                           │
│   ┌──── recipe_ingredients (admin-only RLS) ────────────────────┐         │
│   │ position, raw_text, amount, amount_max, unit, name,         │         │
│   │ modifier, role, parse_status, taxonomy_node_id, id          │         │
│   │   embed: taxonomy_nodes(slug, display_name)                 │         │
│   └─────────────────────────────────────────────────────────────┘         │
│                                                                           │
│   <StructuredIngredients> aligns by position. Click a name →              │
│   /taxonomy?node=<slug>                                                   │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│ /taxonomy?node=<slug> | ?edge=<parent>~<child>  (Taxonomy)               │
│                                                                           │
│   useTaxonomyUrlState() <─→ react-router useSearchParams                 │
│            │                                                              │
│            ├── setFocusedId(id)   ↔   ?node=<slug>                       │
│            └── setFocusedEdge(e)  ↔   ?edge=<parent>~<child>             │
│                                                                           │
│   <NodeCard> when focused:                                                │
│     ┌──── recipe_ingredients (taxonomy_node_id = X) ────┐                │
│     │   embed: recipes(id, name, site)                  │                │
│     └─────────────────────────────────────────────────────┘              │
│                                                                           │
│   List items link to /recipes/:id                                         │
└──────────────────────────────────────────────────────────────────────────┘
```

## Data access

### Recipe page query

```js
supabase
  .from('recipe_ingredients')
  .select(
    'id, position, raw_text, amount, amount_max, unit, name, modifier, ' +
    'role, parse_status, taxonomy_node_id, ' +
    'taxonomy_nodes(slug, display_name)'
  )
  .eq('recipe_id', recipeId)
  .order('position', { ascending: true })
```

PostgREST embeds `taxonomy_nodes(slug, display_name)` via the `recipe_ingredients.taxonomy_node_id → taxonomy_nodes.id` foreign key. Returns `null` for unmapped rows. Non-admin authenticated callers get zero rows back via RLS. Anon callers get a 401 from the API gateway (no GRANT).

### Node-recipe-list query

```js
supabase
  .from('recipe_ingredients')
  .select('recipe_id, recipes(id, name, site)')
  .eq('taxonomy_node_id', nodeId)
  .order('recipe_id', { ascending: true })
```

Embed traverses `recipe_ingredients.recipe_id → recipes.id`. The page is admin-only at the route layer (`RequireAdmin`), so the caller is always admin and `recipes_temp_authed_read` returns the row. We embed `recipes` directly rather than `recipes_public` because PostgREST resolves embeds via FKs, which exist on the table not the view. Site + name dedup happens client-side (a recipe can list a node multiple times if it appears under multiple roles; `Set<recipe_id>` collapses).

### Migration

Single forward-only migration: `supabase/migrations/<ts>_admin_recipe_ingredients_lockdown.sql`.

```sql
-- 1. Tighten RLS: admin only.
drop policy if exists recipe_ingredients_temp_authed_read on recipe_ingredients;
create policy recipe_ingredients_admin_read on recipe_ingredients
  for select to authenticated
  using (is_admin());

-- 2. Extend column grant. Existing grant covered (recipe_id,
-- taxonomy_node_id) for the taxonomy_public count; admins now also need
-- the parser fields.
grant select (
  id, recipe_id, position, raw_text,
  amount, amount_max, unit, name, modifier,
  role, parse_status, taxonomy_node_id
) on recipe_ingredients to authenticated;
```

The `to authenticated` GRANT is unavoidable — Postgres has no `admin` role; Supabase's standard roles are `anon`, `authenticated`, `service_role`, and admin status is an application-level predicate (`is_admin()` reads `profiles.is_admin`). Effective access is `GRANT ∩ RLS`: a non-admin authenticated caller has SELECT permission on the columns but every row fails the `is_admin()` policy, so the response is empty. Same pattern as `taxonomy_nodes_admin_read` and friends.

## UI

### `<StructuredIngredients>` (new)

`web/src/components/recipe/StructuredIngredients.tsx`. Replaces the inline `<ul>` in RecipeDetail. Always renders as a `<table>`. The right-side columns are present only when `useIsAdmin()` returns true; for non-admins the table has a single `<td>` per row holding the raw line and looks identical to the old `<ul>` visually.

Props:
```ts
interface Props {
  rawLines: string[];                       // jsonld.recipeIngredient
  parsedByPosition: Map<number, RecipeIngredientRow> | null;
  // null while loading or for non-admins (admin gating is the parent's job).
}
```

Layout (admin):
```
┌─────────────────────────────────┬────────┬──────────────┬────────┬────────────┬────┐
│ raw line                        │ amount │ name         │ mod    │ role       │ id │
├─────────────────────────────────┼────────┼──────────────┼────────┼────────────┼────┤
│ 2 oz gin                        │ 2 oz   │ gin →        │        │ base_spirit│ 17 │
│ 1 oz fresh-squeezed lime juice  │ 1 oz   │ lime juice → │ fresh  │ citrus     │ 18 │
│ dash Angostura bitters          │ 1 dash │ Angostura →  │        │ bitters    │ 19 │
│ Sweet vermouth (your favorite)  │  ░░ unparseable ░░                              │
│ Garnish: lemon twist            │        │ lemon        │ twist  │ unmapped   │ 22 │
└─────────────────────────────────┴────────┴──────────────┴────────┴────────────┴────┘
```

- **Amount column** renders `amount`, or `amount–amount_max` when both present, followed by `unit`. Falsy unit just shows the number. Falsy amount shows nothing.
- **Name column** is a `<Link to={`/taxonomy?node=${slug}`}>` when `taxonomy_node_id` is present. Otherwise the literal `name` as plain text. Link uses `taxonomy_display_name` from the embed (falls back to `name` if the embed is null — defensive only, shouldn't happen for resolved rows).
- **Role badge** is a small uppercase chip; one stable color per role (palette decision deferred to implementation; muted palette consistent with the existing site).
- **ID** is a small dim monospace value at the rightmost edge. Inconspicuous; useful for "select * from recipe_ingredients where id = 18" debugging.

Failure visuals (loud signals on the right side only — left/raw column stays plain):

- **`parse_status='unparseable'`** — right-side cells collapse into a single italic "unparseable" span tinted amber.
- **`taxonomy_node_id IS NULL`** (parsed but unmapped) — name shown as plain text + tiny "unmapped" chip; role still rendered. Right-side cells get a faint amber left-border.
- **No row at position i** (recipe predates parser run) — right-side cells show italic dim "not parsed". Grey left-border.

### `useTaxonomyUrlState` hook (new)

`web/src/components/taxonomy/useTaxonomyUrlState.ts`. Owns bidirectional sync between (`focusedId`, `focusedEdge`) and `?node=<slug>` / `?edge=<parent_slug>~<child_slug>`. Mutually exclusive params; setting one clears the other.

```ts
interface UseTaxonomyUrlStateArgs {
  rows: TaxonomyViewRow[];   // for slug → id resolution
}

interface UseTaxonomyUrlStateReturn {
  focusedId: number | null;
  focusedEdge: EdgeRef | null;
  setFocusedId: (id: number | null) => void;
  setFocusedEdge: (edge: EdgeRef | null) => void;
  clearFocus: () => void;
}
```

Behavior:
- On mount or rows change: parse `searchParams`. If `?node=<slug>` present and resolvable, set `focusedId`. If `?edge=a~b` present and both endpoints resolvable, set `focusedEdge`.
- `setFocusedId(id)` updates state and pushes `?node=<slug>` (replacing any `?edge`).
- `setFocusedEdge(e)` updates state and pushes `?edge=<parent>~<child>` (replacing any `?node`).
- `clearFocus()` removes both params and resets state.
- Unresolvable slugs (e.g., a stale bookmark to a deleted node) clear the param silently and start un-focused.

Tilde (`~`) is a URI-unreserved character per RFC 3986 §2.3; no encoding needed. Slugs already use letters/digits/underscores; no collision.

The existing `Taxonomy` component drops its local `focusedId` / `focusedEdge` state and consumes the hook instead. The pinning effect (radial layout when focused) keeps working unchanged because it depends on `focusedId`, not on its source.

### `<NodeCard>` recipe list (extension)

After the existing PROPERTIES + ALIASES + RECIPES count section, render a list when the count is > 0:

```
RECIPES (12)

  Negroni                         · imbibemagazine.com
  Boulevardier                    · punchdrink.com
  Old Pal                         · liquor.com
  …
```

- Fetches inside `NodeCard` on mount/focus change. Loading state is a simple "Loading…" line; errors show one-line "Couldn't load recipes". Empty state is rendered as the existing single "—" line when count is 0 (no fetch in that case).
- Sorted client-side by `(site, name)`.
- Each line is a `<Link to={`/recipes/${id}`}>`. Site rendered to the right, muted, in the same monospace style used for IDs/slugs elsewhere.
- Scrolls inside the existing `overflow-y: auto` container the card already has — no new overflow surface.
- The component dedupes by `recipe_id` client-side (a recipe can have multiple `recipe_ingredients` rows resolved to the same node, e.g., gin under both "base_spirit" and a wash; Set collapses).

### Header admin chip (extension)

`web/src/components/Header.tsx` gains a small `<span class="header-admin-chip">admin</span>` between the user email and the Sign Out button when `useIsAdmin()` returns true. Plain text, project typography, muted palette. No icon.

## Files

New:
- `supabase/migrations/<ts>_admin_recipe_ingredients_lockdown.sql`
- `web/src/components/recipe/StructuredIngredients.tsx`
- `web/src/components/recipe/StructuredIngredients.test.tsx`
- `web/src/components/taxonomy/useTaxonomyUrlState.ts`
- `web/src/components/taxonomy/useTaxonomyUrlState.test.tsx`

Styling for the structured table goes into the existing `web/src/styles.css` using BEM-style class names (`recipe-detail__structured`, `recipe-detail__structured-row--unparseable`, etc.) — same convention as `recipe-detail__steps`, `recipe-detail__meta`. No new `.css` file.

Modified:
- `web/src/types.ts` — add `RecipeIngredientRow`.
- `web/src/pages/RecipeDetail.tsx` — replace ingredient `<ul>` with `<StructuredIngredients>`; add the parsed-rows fetch.
- `web/src/pages/RecipeDetail.test.tsx` — admin/non-admin variants.
- `web/src/pages/Taxonomy.tsx` — adopt `useTaxonomyUrlState`.
- `web/src/pages/Taxonomy.test.tsx` — URL-state coverage.
- `web/src/components/taxonomy/NodeCard.tsx` — add recipe list.
- `web/src/components/taxonomy/NodeCard.test.tsx` — recipe list rendering.
- `web/src/components/Header.tsx` — admin chip.
- `web/src/components/Header.test.tsx` — chip visibility.
- `web/src/styles.css` — admin chip + structured-ingredient table classes.

## Tests

Strict red/green TDD per the project's TDD skill. Each test below is written first, run to confirm it fails, then implementation lands and the test goes green.

`StructuredIngredients.test.tsx`:
- non-admin (no `parsedByPosition`) renders one `<td>` per raw line, no right-side cells, content matches input order.
- admin happy-path: 3 raw lines + parsed rows for all positions render aligned cells; name col is a link to `/taxonomy?node=<slug>`.
- amount renders `amount`, `amount unit`, and `amount–amount_max unit` correctly.
- `parse_status='unparseable'` row collapses right side to italic "unparseable", left side unchanged.
- `taxonomy_node_id IS NULL` shows name as plain text with "unmapped" chip, role still visible.
- a position with no parsed row shows "not parsed" on the right.
- `recipe_ingredients.id` rendered on every parsed row.

`useTaxonomyUrlState.test.tsx`:
- mount with `?node=foo` resolves to `focusedId`; clears `?edge` if both somehow set.
- mount with `?edge=a~b` resolves to `focusedEdge`.
- mount with `?node=missing` → no focus + param removed from URL.
- `setFocusedId(7)` writes `?node=<slug>` and clears any `?edge`.
- `setFocusedEdge({source, target})` writes `?edge=<parent>~<child>` and clears any `?node`.
- `clearFocus()` removes both params.
- back-button restores prior focus (verified via memory router state).

`NodeCard.test.tsx` (extension):
- focused node with recipe_count > 0 fetches and renders sorted list of links.
- focused node with recipe_count = 0 skips fetch, shows existing "—".
- duplicate `recipe_id`s in the response collapse.
- error state shows one-line message.

`RecipeDetail.test.tsx` (extension):
- non-admin user renders existing single-column table (no right-side cells).
- admin user renders structured table with parsed rows aligned 1:1.
- admin user with parser-pending recipe (rows missing for some positions) renders "not parsed" in the gaps.

`Header.test.tsx` (extension):
- chip visible when `useIsAdmin()` returns true.
- chip absent when `useIsAdmin()` returns false.

Migration testing piggybacks on the existing `_test_db_migrations` machinery (the `ingredients` conftest auto-applies new migrations to `spiritolo_test`). No new pytest test needed for the migration itself; the auto-apply is the smoke test, and the web tests prove RLS + grants behave as intended via mocked supabase responses.

## Risks and edge cases

- **PostgREST embed FK resolution.** `recipe_ingredients.taxonomy_node_id → taxonomy_nodes.id` and `recipe_ingredients.recipe_id → recipes.id` are both real foreign keys (verified in `20260425120000_create_recipe_ingredients.sql` and `20260429140000_alter_recipe_ingredients_mapping.sql`). PostgREST will resolve embeds without manual hint comments.
- **Duplicate `recipe_ingredients` rows per node per recipe.** A single recipe can map two different lines to the same node (e.g., gin in `base_spirit` and gin in `wash`). The recipe-list dedup is client-side by `recipe_id`; otherwise the same recipe appears twice in the NodeCard list.
- **`recipes` vs. `recipes_public` for embeds.** PostgREST resolves embeds by FK, which exists on `recipes`, not the `recipes_public` view. Embedding `recipes` directly is fine because the page is admin-only at the route layer; `recipes_temp_authed_read` admits any authenticated session. If `recipes` ever gets locked down to admin-only too, this still works for the curator UI. If it goes wider (future anon access), no change needed — the embed only fires from the admin-gated taxonomy page.
- **Stale URL bookmarks** (e.g., `/taxonomy?node=removed_slug` after a node deletion) silently clear the param. No noisy error.
- **Non-admin lands on `/recipes/:id?something`.** No structured fetch issued (admin gate is in RecipeDetail before the fetch); existing page renders. The route does not gain admin-only middleware — the page gracefully degrades.
- **Backend tightening could surprise existing curators mid-session.** The migration replaces the `temp_authed_read` policy with `admin_read`. Any non-admin authenticated session reading `recipe_ingredients` directly through PostgREST starts seeing zero rows. Per the project's tier scheme this is the intended end state (the policy was named `_temp_`); no UI today exposes `recipe_ingredients` to non-admins, so the visible impact is none.

## Out of scope (future)

- Slug rename to hyphens (separately tracked).
- Inline edit on the structured panel (manual remap, role override) — currently CLI-only.
- Multi-node focus on the taxonomy page.
- Cross-link from the structured panel into `recipes_public.cluster_id` / variants (cluster-walk UI is a different feature).
