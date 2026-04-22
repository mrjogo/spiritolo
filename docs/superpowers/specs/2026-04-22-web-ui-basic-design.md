## Goal

Stand up the first, dead-basic version of the web frontend: a local SPA that lists recipes from the `recipes_public` view and renders an individual recipe from its `jsonld` blob. This is not a throwaway — it is the seed of the real app (eventually Vercel-hosted, possibly paired with a React Native client), built with durable technologies but deliberately minimal surface area.

## Scope

**In scope**
- A Vite + React + TypeScript SPA under `/web` at the repo root.
- Two routes: paginated recipe list and single-recipe detail view.
- Direct browser-to-Supabase data access via the anon key and the existing `recipes_public` view.
- A small JSON-LD Recipe normalizer that flattens the messy Schema.org shapes into a clean display model.
- Minimal plain CSS. No component library.

**Out of scope**
- Backend / API server. Browser talks to Supabase directly.
- Authentication, user accounts, saved recipes, favorites.
- Search, filters, sort, tag browsing. Pagination is the only list control.
- Server-side rendering, static generation, edge functions. Plain client-side SPA.
- Vercel deployment. Local `npm run dev` only for now.
- Styling beyond the bare minimum needed to read content. No Tailwind yet.
- React Native / mobile. Reserved for later.
- Testing. No test framework wired in for this iteration; the whole app is a manual-verification tool against real extracted data.
- Error pages / 404 polish, loading skeletons, empty-state illustrations.

## Architectural Decisions

### Vite + React + TypeScript
Named by the user; also the most durable path toward the stated endgame (Vercel + possible React Native). React is the framework shared with RN; Vite is the dev tooling; TypeScript is non-negotiable given `schema-dts` types and a growing codebase.

### Direct browser → Supabase, no backend
`recipes_public` + RLS on the base table already enforce the right boundary: anon keys can read the public view, nothing else. The anon key is public by design. No reason to introduce a backend just to proxy reads.

### Small local normalizer instead of a JSON-LD library
There is no well-maintained npm library that normalizes Schema.org Recipe JSON-LD for display. `schema-dts` gives TypeScript types but does no runtime normalization; `jsonld.js` is a canonicalization tool, not a display helper. Every real recipe site writes a local normalizer because the variant shapes (`HowToStep` vs string, `Person` vs string, `ImageObject` vs URL array) are domain-specific. We do the same. The normalizer is a pure function, easy to port to a shared package later if we add the RN client.

### Minimum viable dependencies
Five runtime packages: `react`, `react-dom`, `react-router-dom`, `@supabase/supabase-js`, `schema-dts`. Plus Vite + TS + the React types as dev deps. No UI kit, no data layer (TanStack Query), no styling framework. All three can be added later when they earn their keep; none of them would add value to this iteration.

### Pagination over fetch-all
Recipe count will grow into the thousands. Even at small counts, fetching everything on mount is a bad pattern to normalize. We use Supabase JS's `.range(from, to)` with `count: 'exact'` for the total, 50 rows per page, Prev/Next navigation, page number in the URL (`?page=2`) so refresh and back-button work.

### Devcontainer-friendly, no socat
The Vite dev server serves JS; the *browser* on the Mac host does the Supabase fetches. VS Code auto-forwards the Vite port (5173) from container to host. From the browser's perspective Supabase is at `http://localhost:54321` regardless of where Vite runs. No `host.docker.internal`, no socat, no port-forward plumbing. (This is a deliberate reversal of the complexity we tried and reverted earlier for the extractor's Python-side Postgres connection.)

## Directory layout

```
web/
  index.html
  package.json
  tsconfig.json
  vite.config.ts
  .env.local.example
  .gitignore
  src/
    main.tsx              # router setup, mounts <App />
    App.tsx               # route definitions
    supabase.ts           # createClient() singleton from env
    types.ts              # RecipeRow (matches recipes_public), NormalizedRecipe
    normalizeRecipe.ts    # jsonld blob -> NormalizedRecipe
    pages/
      RecipeList.tsx      # GET recipes_public, paginated
      RecipeDetail.tsx    # GET one row, normalize, render
    components/
      Pagination.tsx      # Prev / Next / page N of M
    styles.css            # one stylesheet, plain CSS
```

All files are small. If any one component grows past ~150 lines, that's a signal it needs breaking up.

## Data flow

### List page (`/?page=N`)

1. Read `page` from URL (`useSearchParams`). Default 1.
2. Compute `from = (page - 1) * 50`, `to = from + 49`.
3. `supabase.from('recipes_public').select('id, site, name, image_url', { count: 'exact' }).order('id').range(from, to)`.
4. Render a simple grid: thumbnail (if `image_url`), name, site, link to `/recipes/:id`.
5. Pagination component at bottom: `Prev` / `Next`, disabled at bounds, shows `Page N of M`.

### Detail page (`/recipes/:id`)

1. Parse `id` from URL.
2. `supabase.from('recipes_public').select('*').eq('id', id).single()`.
3. Pass the `jsonld` blob through `normalizeRecipe()`.
4. Render: image, name, byline (author + site), yield + times, ingredients list, ordered instructions, link back to `source_url`.
5. "Back to list" link goes to `/` (the browser's back button handles preserving `?page=N`; we don't stash state).

### States

Each page handles three states: `loading`, `error`, `loaded`. Simple early returns, no skeletons. An error on the list page shows the error message; on the detail page it offers a link back to the list. No retry button, no Sentry, nothing fancy.

## `normalizeRecipe.ts`

Input: the raw `jsonld` JSONB as seen in `recipes_public.jsonld`. Output:

```ts
type NormalizedRecipe = {
  name: string;
  author: string | null;
  images: string[];            // zero or more URLs
  description: string | null;
  yield: string | null;
  prepTime: string | null;     // human-formatted, e.g. "15 min"
  cookTime: string | null;
  totalTime: string | null;
  ingredients: string[];
  instructions: InstructionStep[];
  sourceUrl: string | null;    // jsonld.url if present; caller falls back to row.source_url
};

type InstructionStep =
  | { kind: 'step'; text: string }
  | { kind: 'section'; heading: string; steps: string[] };
```

Field rules:
- **images**: accept string, `ImageObject` (`.url`), or an array of either; dedupe, preserve order, drop falsy.
- **author**: string, `Person` (`.name`), or array of either (join with " & "); null if missing.
- **ingredients**: `recipeIngredient` (array) or legacy `ingredients` (string → split on newlines, strip empties).
- **instructions**: three variants — plain string (split on newlines into steps), array of strings / `HowToStep` (each `{ kind: 'step', text }`), array of `HowToSection` with nested `itemListElement` (each `{ kind: 'section', heading, steps }`).
- **times**: ISO-8601 duration (`PT15M`, `PT1H30M`) formatted to `"15 min"`, `"1 h 30 min"`. Unparseable → null.

Pure function, no I/O, no React imports. Defensive on missing or off-type fields — never throws on valid JSON. Returns a best-effort normalization; the test is that nothing in the real extracted dataset crashes the detail page.

## Env and config

`.env.local` (gitignored):

```
VITE_SUPABASE_URL=http://localhost:54321
VITE_SUPABASE_ANON_KEY=<paste from `supabase status`>
```

`.env.local.example` committed with the URL filled in and a placeholder anon key + a one-line instruction to copy from `supabase status`.

`supabase.ts` reads both at module load and fails loudly if either is missing — bad env should be a dev-time error, not a silent runtime one.

## Running it

From the repo root:

```bash
cd web
npm install
npm run dev
```

Vite binds to `localhost:5173`; VS Code forwards the port; the Mac browser opens it. Requires local Supabase to be running on the Mac host (same setup as the extractor).

## Repo updates outside `/web`

- **Root `CLAUDE.md`**: add a short "Web UI" section documenting the commands above and pointing at `web/.env.local.example`.
- **Root `.gitignore`**: confirm `web/node_modules/` and `web/.env.local` are ignored (likely covered by existing globs; check and add if not).

## Success criteria

- `npm run dev` starts without errors on a fresh clone (given a populated `.env.local` and running Supabase).
- The list page at `http://localhost:5173/` shows 50 extracted recipes with name, site, and thumbnail; Prev/Next move through pages and update the URL; page count matches the row count in `recipes_public`.
- Clicking a list item lands on `/recipes/:id` and renders a readable recipe: image, name, ingredients list, numbered instructions, source link, times where present.
- `normalizeRecipe()` survives every row currently in `recipes_public` without throwing. Manual spot-check: visit 10 random recipes, verify nothing crashes and content looks right.
- Directly querying the base `recipes` table with the anon key returns nothing (RLS still enforced); `recipes_public` returns the expected columns. (Existing extractor behavior; verified by the UI succeeding while no new grants are added.)
