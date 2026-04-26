## Goal

Add a basic search box to the web UI that filters the recipe list as the user types, with the query mirrored to the URL so a search is bookmarkable and back-button-restorable. Search runs entirely against the existing `recipes` table — no new tables, no new columns, no JSON-LD re-extraction. The mechanism is a pair of pg_trgm GIN indexes plus `ILIKE` from the Supabase JS client.

This is the "starts cheap" Track [C] item from `docs/future-direction.md` — it ships before structured ingredient extraction (Track [A]) lands, and the future re-point to `recipe_ingredients` (Track [F]) is a small index swap, not a rewrite.

## Scope

**In scope**
- A single search input above the recipe list on the `RecipeList` page.
- Filter-as-you-type behavior with a 250ms debounce on URL writes.
- URL is the source of truth: `?q=<query>&page=<n>`. Pre-filling the box from the URL on initial render and on back/forward navigation.
- Two `pg_trgm` GIN functional indexes on `recipes`: one on `name`, one on `(jsonld->>'recipeIngredient')`.
- Multi-term AND semantics: each whitespace-separated term must match `name` OR ingredients.
- Alphabetical-by-`name` ordering of results. Pagination preserved.
- Tests: pure-function unit tests for the query builder, and `RecipeList` integration tests for typing/URL/clearing/empty-results behavior.

**Out of scope**
- Relevance ranking. Defer the `search_recipes(q text)` RPC and `similarity()`-based ordering until alphabetical clearly hurts.
- Match highlighting / `ts_headline` / matched-term bolding.
- Autocomplete suggestions, dropdown previews, recent-searches list.
- Per-site filter or any other facet. Track listed in `future-direction.md` as cheap to add later; not core to "search starts cheap".
- A new route. The search lives on `/`; there is no `/search`.
- Server-side search, Supabase Edge Functions, or any backend. The browser still talks directly to `recipes_public`.
- Search across `description`, `instructions`, `author`, or any other field. Name + ingredients only. Adding a field later is one filter clause.

## Architectural Decisions

### `pg_trgm` over `tsvector`
The future-direction doc names tsvector. We deliberately depart for two reasons:

1. **Substring match feels right for type-as-you-go.** `tsvector` matches whole tokens (or token prefixes via `q:*`). `pg_trgm` matches anywhere within a string, so "neg" hits "Negroni" mid-word and "marg" hits "Margarita" without thinking about token boundaries. Ginger / gin substring overlap is intentional, not a bug — the user disambiguates by typing more.
2. **Typo tolerance is real for cocktail names.** Caipirinha, Daiquiri, Sazerac, Aperol — proper-noun-heavy. Trigram similarity handles "manhatan" → "Manhattan" naturally. tsvector does not.

Tradeoffs accepted: no built-in stemming ("negronis" doesn't auto-match "negroni") and no built-in relevance ranking. Stemming is a small loss for a recipe-name search; ranking we punt to a future RPC if it earns its keep.

### No table or column changes
Both indexes are pure expression indexes:

```sql
create extension if not exists pg_trgm;

create index recipes_name_trgm_idx
  on recipes using gin (name gin_trgm_ops);

create index recipes_ingredients_trgm_idx
  on recipes using gin ((jsonld->>'recipeIngredient') gin_trgm_ops);
```

`jsonld->>'recipeIngredient'` returns the array as a JSON-encoded text blob, e.g. `'["2 oz gin", "0.75 oz lemon juice", ...]'`. The bracket and quote noise is irrelevant to substring matching; user terms never contain JSON syntax. No generated column, no view rewrite, nothing in `recipes_public` to change. Drop the indexes and the schema is identical to today.

### Query builder is a pure function
URL → PostgREST filter args goes through a single pure function `buildSearchFilters(q: string): SearchFilters` in a new `web/src/searchQuery.ts` module. The function:

- caps the input length at 200 characters (defense against pathological pasted text),
- trims and tokenizes on `\s+`,
- strips leading and trailing non-alphanumeric characters from each term (so `"gin,"` becomes `"gin"`, `"(rye)"` becomes `"rye"`) — internal punctuation like `St-Germain` is preserved,
- drops terms shorter than 3 characters,
- escapes ILIKE special chars (`\`, `%`, `_`) in each remaining term,
- returns `{ terms: string[], orFilters: string[] }` where each `orFilter` is a PostgREST `or(...)` argument string of the form `name.ilike.*term*,jsonld->>recipeIngredient.ilike.*term*`.

The `RecipeList` component chains one `.or(filter)` call per term, which PostgREST AND's together — giving the desired "every term must match name or ingredients" semantics. (Multiple top-level `or` filters in a PostgREST query are AND'd; the implementation step should verify this empirically. If the SDK turns out to coalesce or overwrite, the fallback is a one-page `search_recipes(q)` SQL function called via `.rpc()` — same component call site, builder still pure.)

Keeping this in a pure module means the bulk of the logic is testable without rendering or touching Supabase.

### URL as source of truth, debounced writes
- The input is controlled, value derived from `useSearchParams().get('q') ?? ''`.
- Local state mirrors the input value for instant typing feedback.
- A 250ms debounce delays URL writes so each keystroke does not push a history entry.
- URL writes use `setSearchParams(..., { replace: true })` so back-button history contains "navigated-to" searches (e.g. clicking into a recipe from a search), not every intermediate keystroke.
- `useEffect` keys on `q` and `page` from the URL, refetches when either changes.
- Pre-filling from the URL is automatic — no extra code path.

### Loading and empty states
- While a fetch is in flight, the existing list is dimmed (CSS `opacity`) rather than blanked. Less flicker for fast typists; the previous results stay readable until the new ones arrive.
- Zero-results renders "No recipes match '<q>'." with a "Clear" link that empties `q` (which restores the all-recipes view).
- A small `×` button inside the input clears `q` directly without re-typing.

### Min query length: 3 characters
Trigram-aligned. `gin_trgm_ops` GIN substring matching extracts trigrams (3-grams) from the query pattern at planning time; query strings shorter than 3 characters yield no usable trigrams, and the planner falls back to a sequential scan over `name` + the larger `jsonld->>'recipeIngredient'` text expression. On 25k rows that scan is 200ms+ per keystroke — exactly the lag we want to avoid mid-typing. Three characters also disambiguates most cocktail names well enough to make the first-frame results useful: "neg" (Negroni), "mar" (Margarita), "mar" + Manhattan also matching is fine, the user keeps typing. Sub-3-char terms in a multi-term query are silently ignored, not treated as an error: typing "a gin" still matches by "gin".

### Result ordering: alphabetical by `name`
Two reasons:

1. The current list is ordered by `id` (insertion order, effectively random from a user's perspective). Alphabetical is a strict improvement once a search returns 30+ results.
2. Alphabetical does not require a relevance signal. Adding `similarity()`-based ranking via the future RPC swaps `.order('name')` for `.rpc('search_recipes', { q })` — same call site, same shape, same component. We do not want to commit to ranking semantics now.

Recipes with `NULL` name sort last (`nullslast`), matching `RecipeList`'s "Untitled" fallback.

## Architecture

### Components touched

```
web/src/
├── pages/
│   ├── RecipeList.tsx       (modified: add search input + URL/q wiring)
│   └── RecipeList.test.tsx  (modified: add typing/URL/empty-results tests)
├── searchQuery.ts           (new: buildSearchFilters pure function)
├── searchQuery.test.ts      (new: unit tests for buildSearchFilters)
└── styles.css               (modified: search input + clear-button styles)

supabase/migrations/
└── <timestamp>_recipes_search_trgm.sql   (new: extension + 2 indexes)
```

No changes to `App.tsx`, routing, the Supabase client, the `recipes_public` view, or the `normalizeRecipe` module.

### Data flow

```
User types → input onChange → setLocalState (instant)
                ↓ (250ms debounce)
            setSearchParams({ q, page: '1' }, { replace: true })
                ↓
            useSearchParams() returns new q
                ↓
            useEffect fires → buildSearchFilters(q)
                ↓
            supabase.from('recipes_public')
              .select('id, site, name, image_url', { count: 'exact' })
              .or(filter1).or(filter2)...        // one .or() per term
              .order('name', { nullsFirst: false })
              .range(from, to)
                ↓
            setState({ status: 'loaded', rows, total })
                ↓
            list re-renders, dim flag clears
```

### Filter clause shape, concretely

For `q = "gin lime"`:

```js
const { orFilters } = buildSearchFilters('gin lime');
// orFilters = [
//   'name.ilike.*gin*,jsonld->>recipeIngredient.ilike.*gin*',
//   'name.ilike.*lime*,jsonld->>recipeIngredient.ilike.*lime*',
// ]

let q = supabase.from('recipes_public').select(...).order('name');
for (const f of orFilters) q = q.or(f);
```

PostgREST's URL-style ILIKE uses `*` for the wildcard (the SDK translates this internally), so the builder emits `*term*`. Escaping handles user-typed `*`, `%`, `_`, `\` so they match literally.

## Testing

TDD throughout, matching the existing web test conventions (Vitest + `@testing-library/react`, `*.test.ts(x)` next to the source).

### `searchQuery.test.ts` (new)
- Empty string returns `{ terms: [], orFilters: [] }`.
- Whitespace-only string returns empty.
- Single term: `"negroni"` → one orFilter, one term.
- Multi-term: `"gin lime"` → two orFilters in input order.
- Mixed-length terms: `"a gin"` → drops `"a"`, keeps `"gin"`.
- All-short input: `"a b"` → empty result.
- Special chars in user input: `"50%"`, `"_test"`, `"foo\\bar"` — verify each is escaped so the resulting filter string contains literal `\%`, `\_`, `\\` and not unintended wildcards.
- Trim leading/trailing whitespace.
- Cap at 200 chars: 1000-char input truncates and still returns terms from the first 200.
- Trailing-punctuation stripping: `"gin, vermouth"` → terms `["gin", "vermouth"]`.
- Bracketed term: `"(rye)"` → terms `["rye"]`.
- Internal punctuation preserved: `"st-germain"` → terms `["st-germain"]`.

### `RecipeList.test.tsx` (extend)
Mock the Supabase client per existing patterns.

- Pre-existing tests (paginated render, error state) remain green.
- Initial render with `?q=foo` in URL: input pre-filled with `foo`, fetch fires with the right `or(...)` args.
- Typing into the input: input value updates immediately; URL update is delayed; after 250ms `setSearchParams` is called with the typed value and `page=1`.
- Typing while a search is in flight: list is dimmed (CSS class assertion), previous results still visible.
- Zero-results: empty array + count=0 renders "No recipes match 'foo'." with a Clear control.
- Clearing via the `×` button: empties the input, removes `q` from URL, fetches the unfiltered list.
- Changing `q` while on `page=2` resets to `page=1`.
- Back-button navigation between two searches restores the prior `q` in the URL and refetches.

### Manual smoke test (not automated)
- `cd supabase && supabase db reset --yes` (or apply the migration), confirm the indexes exist via `\d+ recipes` in psql.
- Run `cd web && npm run dev`, search a few real names ("Negroni", "marg", "gin lime"), verify ordering and counts make sense against the local Supabase data.

## Migrations and rollout

One new migration: `supabase/migrations/<timestamp>_recipes_search_trgm.sql` containing the extension and two `CREATE INDEX` statements. Reversible by dropping the indexes; the extension can stay enabled. No data backfill needed — indexes build from existing rows when created.

The migration is small enough to apply to the production Supabase project directly when the time comes; on the ~25k-row local catalog it is effectively instant.

## Future hooks

- **Track [F] re-point to structured ingredients.** When `recipe_ingredients` exists, replace `recipes_ingredients_trgm_idx` with one keyed off the joined / aggregated ingredient names from that table, and adjust `buildSearchFilters` to filter against the new shape. The function signature does not change.
- **Relevance ranking RPC.** A `search_recipes(q text) returns setof recipes_public` SQL function that orders by `similarity(name, q) desc, name asc` lets the component swap `.from(...)...order('name')` for `.rpc('search_recipes', { q })` without otherwise restructuring. Add when alphabetical results visibly hurt.
- **Per-site filter.** A second URL param `?site=<value>` plus one extra `.eq('site', site)` in the chain. Cheap.
