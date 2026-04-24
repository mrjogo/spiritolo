# Basic Local Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first version of the recipe web app — a Vite + React + TypeScript SPA that lists recipes from the local Supabase `recipes_public` view and renders individual recipes from their `jsonld` blobs. Runs locally via `npm run dev`; not throwaway, but deliberately minimal.

**Architecture:** Browser-only SPA. Two routes (`/` and `/recipes/:id`) read directly from Supabase using the anon key. Messy Schema.org Recipe JSON-LD goes through a pure `normalizeRecipe()` function before rendering. Pagination via Supabase's `.range()` + `count: 'exact'`. Basic error pages (404, missing recipe, fetch fail) share one `<ErrorPage>` component.

**Tech Stack:** Vite, React 18, TypeScript, `react-router-dom`, `@supabase/supabase-js`, `schema-dts`. Tests: Vitest + `@testing-library/react` + `jest-dom` + `jsdom`. Plain CSS.

**Spec:** [`docs/superpowers/specs/2026-04-22-web-ui-basic-design.md`](../specs/2026-04-22-web-ui-basic-design.md)

**Discipline:** Every unit of logic is built red-first. A failing test must land (and be observed failing) before its implementation. Commits pair the test with the code that makes it pass.

---

## File Structure

**New files (all under `web/` unless noted)**
- `package.json`, `package-lock.json`, `tsconfig.json`, `tsconfig.node.json`, `vite.config.ts`, `index.html` — Vite scaffold
- `.gitignore`, `.env.local.example`
- `src/main.tsx` — router setup + `<App />` mount
- `src/App.tsx` — route definitions (including catch-all)
- `src/supabase.ts` — `createClient()` singleton
- `src/types.ts` — `RecipeRow`, `NormalizedRecipe`, `InstructionStep`
- `src/normalizeRecipe.ts` — pure function, jsonld → `NormalizedRecipe`
- `src/normalizeRecipe.test.ts`
- `src/pages/RecipeList.tsx` + `.test.tsx`
- `src/pages/RecipeDetail.tsx` + `.test.tsx`
- `src/components/Pagination.tsx` + `.test.tsx`
- `src/components/ErrorPage.tsx` + `.test.tsx`
- `src/styles.css`
- `src/test/setup.ts` — Vitest setup (jest-dom, cleanup)
- `src/test/fixtures/` — real `jsonld` blobs for snapshot-ish tests

**Modified files**
- `CLAUDE.md` (repo root) — add "Web UI" section

---

## Task 1: Scaffold the Vite + React + TypeScript project

**Files:**
- Create: `web/` (Vite template output)

- [ ] **Step 1: Generate the Vite scaffold**

From the repo root:

```bash
npm create vite@latest web -- --template react-ts
```

When prompted, accept all defaults. This creates `web/` with `package.json`, `tsconfig.json`, `tsconfig.node.json`, `vite.config.ts`, `index.html`, `src/main.tsx`, `src/App.tsx`, `src/App.css`, `src/index.css`, `src/assets/react.svg`, `public/vite.svg`.

- [ ] **Step 2: Install baseline deps**

```bash
cd web && npm install
```

Expected: creates `web/node_modules/` and `web/package-lock.json`.

- [ ] **Step 3: Remove scaffold cruft we won't use**

Delete these files — we'll replace everything with our own shortly:

```bash
rm web/src/App.css web/src/index.css web/src/assets/react.svg web/public/vite.svg
```

Also clear out `web/src/App.tsx` and `web/src/main.tsx` — we'll rewrite them in a later task. For now, replace both with minimal stubs so `npm run build` still works:

`web/src/App.tsx`:
```tsx
export default function App() {
  return <div>placeholder</div>;
}
```

`web/src/main.tsx`:
```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

Also remove `<link rel="icon" ...>` and the `favicon.svg` reference from `web/index.html` (we're not shipping a favicon yet).

- [ ] **Step 4: Smoke check the build**

```bash
cd web && npm run build
```

Expected: exits 0, produces `web/dist/`.

- [ ] **Step 5: Commit**

```bash
git add web/
git commit -m "Web: scaffold Vite + React + TypeScript project"
```

---

## Task 2: Add runtime dependencies

**Files:**
- Modify: `web/package.json`, `web/package-lock.json`

- [ ] **Step 1: Install runtime deps**

```bash
cd web && npm install react-router-dom @supabase/supabase-js schema-dts
```

Expected: `package.json` gains `react-router-dom`, `@supabase/supabase-js`, `schema-dts` in `dependencies`.

- [ ] **Step 2: Verify imports resolve**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/package.json web/package-lock.json
git commit -m "Web: add react-router, supabase-js, schema-dts"
```

---

## Task 3: Wire up Vitest + React Testing Library

**Files:**
- Create: `web/src/test/setup.ts`
- Modify: `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`

- [ ] **Step 1: Install test deps**

```bash
cd web && npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom @types/react @types/react-dom
```

(`@types/react` and `@types/react-dom` are already present from the Vite template; `npm install -D` is a no-op for them but listed for safety.)

- [ ] **Step 2: Configure Vitest in `vite.config.ts`**

Replace `web/vite.config.ts` entirely:

```ts
/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    css: false,
  },
});
```

- [ ] **Step 3: Create the test setup file**

`web/src/test/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
});
```

- [ ] **Step 4: Add Vitest globals to tsconfig**

Modern Vite templates split TS config: `tsconfig.json` is a references file, and app-code `compilerOptions` live in `tsconfig.app.json`. Find the file that contains `"include": ["src"]` (or references `src/**`) — that's the one to edit. Add a `types` array to its `compilerOptions`:

```json
"types": ["vitest/globals", "@testing-library/jest-dom"]
```

Don't rewrite the whole file — just merge the `types` field into the existing `compilerOptions`, preserving everything else. If a `types` array already exists, append these two entries.

- [ ] **Step 5: Add `test` scripts to `package.json`**

Edit `web/package.json` `scripts`:

```json
"scripts": {
  "dev": "vite",
  "build": "tsc -b && vite build",
  "preview": "vite preview",
  "test": "vitest run",
  "test:watch": "vitest"
}
```

- [ ] **Step 6: Create a trivial test to prove the harness works**

`web/src/test/harness.test.ts`:

```ts
import { describe, it, expect } from 'vitest';

describe('test harness', () => {
  it('runs', () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 7: Run the test**

```bash
cd web && npm test
```

Expected: 1 passing test in `harness.test.ts`.

- [ ] **Step 8: Delete the sanity test**

```bash
rm web/src/test/harness.test.ts
```

- [ ] **Step 9: Commit**

```bash
git add web/
git commit -m "Web: configure Vitest + React Testing Library"
```

---

## Task 4: Declare shared types

**Files:**
- Create: `web/src/types.ts`

- [ ] **Step 1: Write the types file**

`web/src/types.ts`:

```ts
// Row shape of the recipes_public view.
export type RecipeRow = {
  id: number;
  source_url: string;
  site: string;
  name: string | null;
  author: string | null;
  image_url: string | null;
  jsonld: Record<string, unknown>;
};

// List-page projection (fewer columns, for speed).
export type RecipeListItem = Pick<
  RecipeRow,
  'id' | 'site' | 'name' | 'image_url'
>;

// Display-ready recipe, produced by normalizeRecipe().
export type NormalizedRecipe = {
  name: string;
  author: string | null;
  images: string[];
  description: string | null;
  yield: string | null;
  prepTime: string | null;
  cookTime: string | null;
  totalTime: string | null;
  ingredients: string[];
  instructions: InstructionStep[];
  sourceUrl: string | null;
};

export type InstructionStep =
  | { kind: 'step'; text: string }
  | { kind: 'section'; heading: string; steps: string[] };
```

- [ ] **Step 2: Type-check**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/types.ts
git commit -m "Web: shared types (RecipeRow, NormalizedRecipe)"
```

---

## Task 5: TDD `normalizeRecipe` — name, description, yield, sourceUrl, author

These are the simpler fields. One test file grows across tasks 5–9; each task adds a `describe` block + the code to pass it.

**Files:**
- Create: `web/src/normalizeRecipe.ts`
- Create: `web/src/normalizeRecipe.test.ts`

- [ ] **Step 1: Write the failing test**

`web/src/normalizeRecipe.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { normalizeRecipe } from './normalizeRecipe';

describe('normalizeRecipe: simple fields', () => {
  it('returns the name', () => {
    expect(normalizeRecipe({ name: 'Old Fashioned' }).name).toBe('Old Fashioned');
  });

  it('returns "Untitled" when name is missing', () => {
    expect(normalizeRecipe({}).name).toBe('Untitled');
  });

  it('returns the description or null', () => {
    expect(normalizeRecipe({ description: 'A classic.' }).description).toBe('A classic.');
    expect(normalizeRecipe({}).description).toBeNull();
  });

  it('returns the recipeYield as a string', () => {
    expect(normalizeRecipe({ recipeYield: '1 drink' }).yield).toBe('1 drink');
    expect(normalizeRecipe({ recipeYield: 2 }).yield).toBe('2');
    expect(normalizeRecipe({}).yield).toBeNull();
  });

  it('returns the sourceUrl from jsonld.url when present', () => {
    expect(normalizeRecipe({ url: 'https://example.com/x' }).sourceUrl).toBe(
      'https://example.com/x',
    );
    expect(normalizeRecipe({}).sourceUrl).toBeNull();
  });
});

describe('normalizeRecipe: author', () => {
  it('handles a bare string author', () => {
    expect(normalizeRecipe({ author: 'Jerry Thomas' }).author).toBe('Jerry Thomas');
  });

  it('handles a Person object', () => {
    expect(
      normalizeRecipe({ author: { '@type': 'Person', name: 'Jerry Thomas' } }).author,
    ).toBe('Jerry Thomas');
  });

  it('handles an array of authors, joining with " & "', () => {
    expect(
      normalizeRecipe({
        author: [
          { '@type': 'Person', name: 'A' },
          { '@type': 'Person', name: 'B' },
          'C',
        ],
      }).author,
    ).toBe('A & B & C');
  });

  it('returns null when author is missing or empty', () => {
    expect(normalizeRecipe({}).author).toBeNull();
    expect(normalizeRecipe({ author: [] }).author).toBeNull();
    expect(normalizeRecipe({ author: '' }).author).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- normalizeRecipe
```

Expected: fails with `Cannot find module './normalizeRecipe'`.

- [ ] **Step 3: Write minimal implementation**

`web/src/normalizeRecipe.ts`:

```ts
import type { NormalizedRecipe } from './types';

type Json = Record<string, unknown>;

function asString(x: unknown): string | null {
  if (typeof x === 'string') {
    const s = x.trim();
    return s === '' ? null : s;
  }
  if (typeof x === 'number') return String(x);
  return null;
}

function extractName(x: unknown): string | null {
  if (typeof x === 'string') return asString(x);
  if (x && typeof x === 'object' && 'name' in x) return asString((x as Json).name);
  return null;
}

function normalizeAuthor(raw: unknown): string | null {
  if (raw == null) return null;
  const arr = Array.isArray(raw) ? raw : [raw];
  const names = arr.map(extractName).filter((n): n is string => !!n);
  return names.length === 0 ? null : names.join(' & ');
}

export function normalizeRecipe(jsonld: Json): NormalizedRecipe {
  return {
    name: asString(jsonld.name) ?? 'Untitled',
    author: normalizeAuthor(jsonld.author),
    images: [],
    description: asString(jsonld.description),
    yield: asString(jsonld.recipeYield),
    prepTime: null,
    cookTime: null,
    totalTime: null,
    ingredients: [],
    instructions: [],
    sourceUrl: asString(jsonld.url),
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd web && npm test -- normalizeRecipe
```

Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/normalizeRecipe.ts web/src/normalizeRecipe.test.ts
git commit -m "Web: normalizeRecipe — name, description, yield, url, author"
```

---

## Task 6: TDD `normalizeRecipe` — images

- [ ] **Step 1: Add failing test**

Append to `web/src/normalizeRecipe.test.ts`:

```ts
describe('normalizeRecipe: images', () => {
  const img = (r: Record<string, unknown>) => normalizeRecipe(r).images;

  it('handles a single string', () => {
    expect(img({ image: 'https://x/a.jpg' })).toEqual(['https://x/a.jpg']);
  });

  it('handles an ImageObject', () => {
    expect(img({ image: { '@type': 'ImageObject', url: 'https://x/a.jpg' } })).toEqual([
      'https://x/a.jpg',
    ]);
  });

  it('handles an array of strings', () => {
    expect(img({ image: ['https://x/a.jpg', 'https://x/b.jpg'] })).toEqual([
      'https://x/a.jpg',
      'https://x/b.jpg',
    ]);
  });

  it('handles an array of ImageObjects, preserves order, dedupes', () => {
    expect(
      img({
        image: [
          { url: 'https://x/a.jpg' },
          { url: 'https://x/b.jpg' },
          { url: 'https://x/a.jpg' },
        ],
      }),
    ).toEqual(['https://x/a.jpg', 'https://x/b.jpg']);
  });

  it('drops falsy, non-string urls, and returns [] when nothing usable', () => {
    expect(img({})).toEqual([]);
    expect(img({ image: null })).toEqual([]);
    expect(img({ image: ['', null, { url: '' }] })).toEqual([]);
    expect(img({ image: [{ foo: 'bar' }] })).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd web && npm test -- normalizeRecipe
```

Expected: images tests fail.

- [ ] **Step 3: Implement**

Add to `web/src/normalizeRecipe.ts` (above `normalizeRecipe`):

```ts
function extractImageUrl(x: unknown): string | null {
  if (typeof x === 'string') return asString(x);
  if (x && typeof x === 'object' && 'url' in x) return asString((x as Json).url);
  return null;
}

function normalizeImages(raw: unknown): string[] {
  if (raw == null) return [];
  const arr = Array.isArray(raw) ? raw : [raw];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of arr) {
    const url = extractImageUrl(item);
    if (url && !seen.has(url)) {
      seen.add(url);
      out.push(url);
    }
  }
  return out;
}
```

And change the `images` field in the returned object:

```ts
images: normalizeImages(jsonld.image),
```

- [ ] **Step 4: Run tests**

```bash
cd web && npm test -- normalizeRecipe
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/normalizeRecipe.ts web/src/normalizeRecipe.test.ts
git commit -m "Web: normalizeRecipe — images"
```

---

## Task 7: TDD `normalizeRecipe` — times (ISO-8601 duration)

- [ ] **Step 1: Add failing test**

Append to `web/src/normalizeRecipe.test.ts`:

```ts
describe('normalizeRecipe: times', () => {
  const times = (r: Record<string, unknown>) => {
    const n = normalizeRecipe(r);
    return { prep: n.prepTime, cook: n.cookTime, total: n.totalTime };
  };

  it('formats minutes', () => {
    expect(times({ totalTime: 'PT15M' }).total).toBe('15 min');
  });

  it('formats hours and minutes', () => {
    expect(times({ totalTime: 'PT1H30M' }).total).toBe('1 h 30 min');
  });

  it('formats whole hours', () => {
    expect(times({ totalTime: 'PT2H' }).total).toBe('2 h');
  });

  it('returns null on malformed durations', () => {
    expect(times({ totalTime: 'fifteen minutes' }).total).toBeNull();
    expect(times({ totalTime: '' }).total).toBeNull();
  });

  it('handles prepTime and cookTime independently', () => {
    const n = normalizeRecipe({ prepTime: 'PT5M', cookTime: 'PT10M' });
    expect(n.prepTime).toBe('5 min');
    expect(n.cookTime).toBe('10 min');
  });

  it('returns null when missing', () => {
    const n = normalizeRecipe({});
    expect(n.prepTime).toBeNull();
    expect(n.cookTime).toBeNull();
    expect(n.totalTime).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd web && npm test -- normalizeRecipe
```

Expected: times tests fail.

- [ ] **Step 3: Implement**

Add to `web/src/normalizeRecipe.ts` (above `normalizeRecipe`):

```ts
function formatDuration(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const m = raw.match(/^PT(?:(\d+)H)?(?:(\d+)M)?$/);
  if (!m) return null;
  const hours = m[1] ? parseInt(m[1], 10) : 0;
  const mins = m[2] ? parseInt(m[2], 10) : 0;
  if (hours === 0 && mins === 0) return null;
  if (hours > 0 && mins > 0) return `${hours} h ${mins} min`;
  if (hours > 0) return `${hours} h`;
  return `${mins} min`;
}
```

Update the returned object:

```ts
prepTime: formatDuration(jsonld.prepTime),
cookTime: formatDuration(jsonld.cookTime),
totalTime: formatDuration(jsonld.totalTime),
```

- [ ] **Step 4: Run tests**

```bash
cd web && npm test -- normalizeRecipe
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/normalizeRecipe.ts web/src/normalizeRecipe.test.ts
git commit -m "Web: normalizeRecipe — ISO-8601 duration formatting"
```

---

## Task 8: TDD `normalizeRecipe` — ingredients

- [ ] **Step 1: Add failing test**

Append to `web/src/normalizeRecipe.test.ts`:

```ts
describe('normalizeRecipe: ingredients', () => {
  const ing = (r: Record<string, unknown>) => normalizeRecipe(r).ingredients;

  it('uses recipeIngredient when present', () => {
    expect(ing({ recipeIngredient: ['2 oz gin', '0.5 oz lemon juice'] })).toEqual([
      '2 oz gin',
      '0.5 oz lemon juice',
    ]);
  });

  it('splits legacy `ingredients` string on newlines, dropping blanks', () => {
    expect(ing({ ingredients: '2 oz gin\n\n0.5 oz lemon juice\n' })).toEqual([
      '2 oz gin',
      '0.5 oz lemon juice',
    ]);
  });

  it('prefers recipeIngredient over legacy `ingredients`', () => {
    expect(
      ing({
        recipeIngredient: ['new'],
        ingredients: 'old',
      }),
    ).toEqual(['new']);
  });

  it('returns [] when neither is present or usable', () => {
    expect(ing({})).toEqual([]);
    expect(ing({ recipeIngredient: [] })).toEqual([]);
    expect(ing({ ingredients: '' })).toEqual([]);
    expect(ing({ recipeIngredient: 'not-an-array' })).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd web && npm test -- normalizeRecipe
```

Expected: ingredients tests fail.

- [ ] **Step 3: Implement**

Add to `web/src/normalizeRecipe.ts`:

```ts
function normalizeIngredients(jsonld: Json): string[] {
  const primary = jsonld.recipeIngredient;
  if (Array.isArray(primary)) {
    return primary.map((x) => asString(x)).filter((s): s is string => !!s);
  }
  const legacy = jsonld.ingredients;
  if (typeof legacy === 'string') {
    return legacy
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line !== '');
  }
  return [];
}
```

Update the returned object:

```ts
ingredients: normalizeIngredients(jsonld),
```

- [ ] **Step 4: Run tests**

```bash
cd web && npm test -- normalizeRecipe
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/normalizeRecipe.ts web/src/normalizeRecipe.test.ts
git commit -m "Web: normalizeRecipe — ingredients (recipeIngredient + legacy)"
```

---

## Task 9: TDD `normalizeRecipe` — instructions

- [ ] **Step 1: Add failing test**

Append to `web/src/normalizeRecipe.test.ts`:

```ts
describe('normalizeRecipe: instructions', () => {
  const ins = (r: Record<string, unknown>) => normalizeRecipe(r).instructions;

  it('handles a plain string, splitting on newlines', () => {
    expect(ins({ recipeInstructions: 'Stir.\n\nStrain.' })).toEqual([
      { kind: 'step', text: 'Stir.' },
      { kind: 'step', text: 'Strain.' },
    ]);
  });

  it('handles an array of strings', () => {
    expect(ins({ recipeInstructions: ['Stir.', 'Strain.'] })).toEqual([
      { kind: 'step', text: 'Stir.' },
      { kind: 'step', text: 'Strain.' },
    ]);
  });

  it('handles an array of HowToStep objects', () => {
    expect(
      ins({
        recipeInstructions: [
          { '@type': 'HowToStep', text: 'Stir.' },
          { '@type': 'HowToStep', text: 'Strain.' },
        ],
      }),
    ).toEqual([
      { kind: 'step', text: 'Stir.' },
      { kind: 'step', text: 'Strain.' },
    ]);
  });

  it('handles HowToSection with nested itemListElement', () => {
    expect(
      ins({
        recipeInstructions: [
          {
            '@type': 'HowToSection',
            name: 'Prep',
            itemListElement: [
              { '@type': 'HowToStep', text: 'Chill glass.' },
              { '@type': 'HowToStep', text: 'Measure.' },
            ],
          },
          {
            '@type': 'HowToSection',
            name: 'Build',
            itemListElement: ['Combine.', 'Stir.'],
          },
        ],
      }),
    ).toEqual([
      { kind: 'section', heading: 'Prep', steps: ['Chill glass.', 'Measure.'] },
      { kind: 'section', heading: 'Build', steps: ['Combine.', 'Stir.'] },
    ]);
  });

  it('skips unknown/empty entries silently', () => {
    expect(
      ins({
        recipeInstructions: [
          { '@type': 'HowToStep', text: '' },
          null,
          { foo: 'bar' },
          'Stir.',
        ],
      }),
    ).toEqual([{ kind: 'step', text: 'Stir.' }]);
  });

  it('returns [] when missing or empty', () => {
    expect(ins({})).toEqual([]);
    expect(ins({ recipeInstructions: [] })).toEqual([]);
    expect(ins({ recipeInstructions: '' })).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd web && npm test -- normalizeRecipe
```

Expected: instructions tests fail.

- [ ] **Step 3: Implement**

Add to `web/src/normalizeRecipe.ts`:

```ts
import type { InstructionStep, NormalizedRecipe } from './types';

function extractStepText(x: unknown): string | null {
  if (typeof x === 'string') return asString(x);
  if (x && typeof x === 'object' && 'text' in x) return asString((x as Json).text);
  return null;
}

function extractSectionSteps(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.map(extractStepText).filter((s): s is string => !!s);
}

function normalizeInstructions(raw: unknown): InstructionStep[] {
  if (typeof raw === 'string') {
    return raw
      .split('\n')
      .map((s) => s.trim())
      .filter((s) => s !== '')
      .map((text) => ({ kind: 'step' as const, text }));
  }
  if (!Array.isArray(raw)) return [];
  const out: InstructionStep[] = [];
  for (const entry of raw) {
    if (
      entry &&
      typeof entry === 'object' &&
      (entry as Json)['@type'] === 'HowToSection'
    ) {
      const e = entry as Json;
      const heading = asString(e.name) ?? '';
      const steps = extractSectionSteps(e.itemListElement);
      if (steps.length > 0) out.push({ kind: 'section', heading, steps });
      continue;
    }
    const text = extractStepText(entry);
    if (text) out.push({ kind: 'step', text });
  }
  return out;
}
```

(Note: the `import type` line at the top of the file needs to include `InstructionStep`. If the existing import is `import type { NormalizedRecipe } from './types';`, change it to `import type { InstructionStep, NormalizedRecipe } from './types';`.)

Update the returned object:

```ts
instructions: normalizeInstructions(jsonld.recipeInstructions),
```

- [ ] **Step 4: Run tests**

```bash
cd web && npm test -- normalizeRecipe
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/normalizeRecipe.ts web/src/normalizeRecipe.test.ts
git commit -m "Web: normalizeRecipe — instructions (string/array/HowToStep/HowToSection)"
```

---

## Task 10: Real-blob fixture test for `normalizeRecipe`

**Files:**
- Create: `web/src/test/fixtures/diffordsguide-sample.json`
- Modify: `web/src/normalizeRecipe.test.ts`

- [ ] **Step 1: Capture a real blob**

On the Mac host (where Supabase runs), grab one real `jsonld` row:

```bash
psql "postgresql://postgres:postgres@localhost:54322/postgres" -At -c \
  "select jsonld from recipes_public limit 1" > /tmp/sample.json
```

If that returns empty (extractor not yet run against real data), use the fallback fixture below instead of a live capture — the point is to exercise the full normalizer, not to bless any specific site's data.

- [ ] **Step 2: Save the fixture**

Copy to `web/src/test/fixtures/diffordsguide-sample.json`. If using the fallback (no live data), write this instead:

```json
{
  "@context": "https://schema.org/",
  "@type": "Recipe",
  "name": "Gin Martini",
  "description": "A classic.",
  "url": "https://example.com/gin-martini",
  "image": [
    { "@type": "ImageObject", "url": "https://example.com/martini.jpg" }
  ],
  "author": { "@type": "Person", "name": "Jerry Thomas" },
  "recipeYield": "1 drink",
  "prepTime": "PT2M",
  "totalTime": "PT2M",
  "recipeIngredient": ["2 oz gin", "1 oz dry vermouth", "Lemon twist"],
  "recipeInstructions": [
    { "@type": "HowToStep", "text": "Stir with ice." },
    { "@type": "HowToStep", "text": "Strain into a chilled glass." },
    { "@type": "HowToStep", "text": "Garnish with lemon twist." }
  ]
}
```

- [ ] **Step 3: Add failing test**

Append to `web/src/normalizeRecipe.test.ts`:

```ts
import sample from './test/fixtures/diffordsguide-sample.json';

describe('normalizeRecipe: real fixture', () => {
  it('normalizes an end-to-end blob without throwing', () => {
    const n = normalizeRecipe(sample as Record<string, unknown>);
    expect(n.name).toBeTruthy();
    expect(n.ingredients.length).toBeGreaterThan(0);
    expect(n.instructions.length).toBeGreaterThan(0);
    expect(Array.isArray(n.images)).toBe(true);
  });

  it('matches the expected shape snapshot', () => {
    expect(normalizeRecipe(sample as Record<string, unknown>)).toMatchSnapshot();
  });
});
```

You'll also need JSON imports configured. Edit `web/tsconfig.json` `compilerOptions`, confirm `"resolveJsonModule": true` is present (it should be from the Vite template).

- [ ] **Step 4: Run to verify first snapshot is written**

```bash
cd web && npm test -- normalizeRecipe
```

Expected: the first test passes (assertions hold); the snapshot test creates a new snapshot and passes. A `__snapshots__/` dir appears next to the test file.

- [ ] **Step 5: Commit**

```bash
git add web/src/normalizeRecipe.test.ts web/src/normalizeRecipe.ts web/src/test/fixtures/ web/src/__snapshots__/
git commit -m "Web: normalizeRecipe — end-to-end fixture + snapshot"
```

(If `__snapshots__/` landed under a different path, adjust the `git add` — the location is determined by Vitest. `git status` will show it.)

---

## Task 11: Supabase client + env wiring

**Files:**
- Create: `web/src/supabase.ts`, `web/.env.local.example`

- [ ] **Step 1: Write the client module**

`web/src/supabase.ts`:

```ts
import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  throw new Error(
    'Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY. ' +
      'Copy web/.env.local.example to web/.env.local and fill in values from `supabase status`.',
  );
}

export const supabase = createClient(url, anonKey);
```

- [ ] **Step 2: Write the example env file**

`web/.env.local.example`:

```
# Copy to .env.local and fill in the anon key from `supabase status` on the Mac host.
VITE_SUPABASE_URL=http://localhost:54321
VITE_SUPABASE_ANON_KEY=your-local-anon-key-here
```

- [ ] **Step 3: Type-check**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors. (`import.meta.env` is typed by Vite's built-in `vite/client` reference.)

- [ ] **Step 4: Commit**

```bash
git add web/src/supabase.ts web/.env.local.example
git commit -m "Web: Supabase client + env template"
```

---

## Task 12: TDD `<ErrorPage>`

**Files:**
- Create: `web/src/components/ErrorPage.tsx`, `web/src/components/ErrorPage.test.tsx`

- [ ] **Step 1: Write the failing test**

`web/src/components/ErrorPage.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ErrorPage } from './ErrorPage';

function renderAt(title: string, message: string) {
  return render(
    <MemoryRouter>
      <ErrorPage title={title} message={message} />
    </MemoryRouter>,
  );
}

describe('<ErrorPage>', () => {
  it('renders the title as a heading', () => {
    renderAt('Page not found', 'Nothing here.');
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });

  it('renders the message', () => {
    renderAt('Page not found', 'Nothing here.');
    expect(screen.getByText('Nothing here.')).toBeInTheDocument();
  });

  it('has a link back to /', () => {
    renderAt('Page not found', 'Nothing here.');
    const link = screen.getByRole('link', { name: /back to recipes/i });
    expect(link).toHaveAttribute('href', '/');
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd web && npm test -- ErrorPage
```

Expected: fails with `Cannot find module './ErrorPage'`.

- [ ] **Step 3: Implement**

`web/src/components/ErrorPage.tsx`:

```tsx
import { Link } from 'react-router-dom';

type Props = { title: string; message: string };

export function ErrorPage({ title, message }: Props) {
  return (
    <div className="error-page">
      <h1>{title}</h1>
      <p>{message}</p>
      <p>
        <Link to="/">← Back to recipes</Link>
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

```bash
cd web && npm test -- ErrorPage
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/ErrorPage.tsx web/src/components/ErrorPage.test.tsx
git commit -m "Web: ErrorPage component"
```

---

## Task 13: TDD `<Pagination>`

**Files:**
- Create: `web/src/components/Pagination.tsx`, `web/src/components/Pagination.test.tsx`

- [ ] **Step 1: Write the failing test**

`web/src/components/Pagination.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom';
import { Pagination } from './Pagination';

function Harness({ initialPath, totalPages }: { initialPath: string; totalPages: number }) {
  return (
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <Pagination totalPages={totalPages} />
              <CurrentPage />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

function CurrentPage() {
  const [params] = useSearchParams();
  return <div data-testid="current-page">{params.get('page') ?? '1'}</div>;
}

describe('<Pagination>', () => {
  it('shows "Page N of M"', () => {
    render(<Harness initialPath="/?page=3" totalPages={10} />);
    expect(screen.getByText('Page 3 of 10')).toBeInTheDocument();
  });

  it('defaults to page 1 when no ?page param', () => {
    render(<Harness initialPath="/" totalPages={5} />);
    expect(screen.getByText('Page 1 of 5')).toBeInTheDocument();
  });

  it('disables Prev on page 1', () => {
    render(<Harness initialPath="/" totalPages={5} />);
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled();
  });

  it('disables Next on the last page', () => {
    render(<Harness initialPath="/?page=5" totalPages={5} />);
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled();
  });

  it('advances page on Next click', async () => {
    render(<Harness initialPath="/?page=2" totalPages={5} />);
    await userEvent.click(screen.getByRole('button', { name: /next/i }));
    expect(screen.getByTestId('current-page').textContent).toBe('3');
  });

  it('decrements page on Prev click', async () => {
    render(<Harness initialPath="/?page=3" totalPages={5} />);
    await userEvent.click(screen.getByRole('button', { name: /prev/i }));
    expect(screen.getByTestId('current-page').textContent).toBe('2');
  });

  it('renders nothing when totalPages <= 1', () => {
    const { container } = render(<Harness initialPath="/" totalPages={1} />);
    expect(container.querySelector('.pagination')).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd web && npm test -- Pagination
```

Expected: fails with `Cannot find module './Pagination'`.

- [ ] **Step 3: Implement**

`web/src/components/Pagination.tsx`:

```tsx
import { useSearchParams } from 'react-router-dom';

type Props = { totalPages: number };

export function Pagination({ totalPages }: Props) {
  const [params, setParams] = useSearchParams();
  const page = parseInt(params.get('page') ?? '1', 10);

  if (totalPages <= 1) return null;

  const goto = (n: number) => {
    const next = new URLSearchParams(params);
    if (n === 1) next.delete('page');
    else next.set('page', String(n));
    setParams(next);
  };

  return (
    <div className="pagination">
      <button disabled={page <= 1} onClick={() => goto(page - 1)}>
        Prev
      </button>
      <span>
        Page {page} of {totalPages}
      </span>
      <button disabled={page >= totalPages} onClick={() => goto(page + 1)}>
        Next
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

```bash
cd web && npm test -- Pagination
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/Pagination.tsx web/src/components/Pagination.test.tsx
git commit -m "Web: Pagination component"
```

---

## Task 14: TDD `<RecipeList>`

**Files:**
- Create: `web/src/pages/RecipeList.tsx`, `web/src/pages/RecipeList.test.tsx`

- [ ] **Step 1: Write the failing test**

`web/src/pages/RecipeList.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// Mock the supabase module BEFORE importing the component.
vi.mock('../supabase', () => ({ supabase: { from: vi.fn() } }));
import { supabase } from '../supabase';
import { RecipeList } from './RecipeList';

type Row = { id: number; site: string; name: string | null; image_url: string | null };

function mockRangeResponse(rows: Row[], count: number, error: unknown = null) {
  const range = vi.fn().mockResolvedValue({ data: rows, count, error });
  const order = vi.fn(() => ({ range }));
  const select = vi.fn(() => ({ order }));
  (supabase.from as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ select });
  return { range, order, select };
}

function mockRejection(message: string) {
  const range = vi.fn().mockResolvedValue({ data: null, count: null, error: { message } });
  const order = vi.fn(() => ({ range }));
  const select = vi.fn(() => ({ order }));
  (supabase.from as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ select });
}

describe('<RecipeList>', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a loading state initially', () => {
    mockRangeResponse([], 0);
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('renders rows after loading', async () => {
    mockRangeResponse(
      [
        { id: 1, site: 'diffordsguide', name: 'Old Fashioned', image_url: null },
        { id: 2, site: 'diffordsguide', name: 'Martini', image_url: 'https://x/m.jpg' },
      ],
      2,
    );
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    expect(await screen.findByText('Old Fashioned')).toBeInTheDocument();
    expect(screen.getByText('Martini')).toBeInTheDocument();
  });

  it('renders an error block on fetch failure', async () => {
    mockRejection('db unreachable');
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText(/couldn't load recipes/i)).toBeInTheDocument();
      expect(screen.getByText(/db unreachable/i)).toBeInTheDocument();
    });
  });

  it('links each item to /recipes/:id', async () => {
    mockRangeResponse([{ id: 42, site: 's', name: 'A', image_url: null }], 1);
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    const link = await screen.findByRole('link', { name: /a/i });
    expect(link).toHaveAttribute('href', '/recipes/42');
  });

  it('requests the correct range for page 1 (0..49)', async () => {
    const { range } = mockRangeResponse([], 0);
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    await waitFor(() => expect(range).toHaveBeenCalledWith(0, 49));
  });

  it('requests the correct range for ?page=3 (100..149)', async () => {
    const { range } = mockRangeResponse([], 0);
    render(
      <MemoryRouter initialEntries={['/?page=3']}>
        <RecipeList />
      </MemoryRouter>,
    );
    await waitFor(() => expect(range).toHaveBeenCalledWith(100, 149));
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd web && npm test -- RecipeList
```

Expected: fails with `Cannot find module './RecipeList'`.

- [ ] **Step 3: Implement**

`web/src/pages/RecipeList.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { supabase } from '../supabase';
import { Pagination } from '../components/Pagination';
import type { RecipeListItem } from '../types';

const PAGE_SIZE = 50;

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'loaded'; rows: RecipeListItem[]; total: number };

export function RecipeList() {
  const [params] = useSearchParams();
  const page = Math.max(1, parseInt(params.get('page') ?? '1', 10) || 1);
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    const from = (page - 1) * PAGE_SIZE;
    const to = from + PAGE_SIZE - 1;

    supabase
      .from('recipes_public')
      .select('id, site, name, image_url', { count: 'exact' })
      .order('id')
      .range(from, to)
      .then(({ data, count, error }) => {
        if (cancelled) return;
        if (error) {
          setState({ status: 'error', message: error.message });
          return;
        }
        setState({
          status: 'loaded',
          rows: (data ?? []) as RecipeListItem[],
          total: count ?? 0,
        });
      });

    return () => {
      cancelled = true;
    };
  }, [page]);

  if (state.status === 'loading') return <div className="page">Loading…</div>;

  if (state.status === 'error') {
    return (
      <div className="page error-page">
        <h1>Couldn't load recipes</h1>
        <p>{state.message}</p>
      </div>
    );
  }

  const totalPages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));

  return (
    <div className="page">
      <h1>Recipes</h1>
      <ul className="recipe-list">
        {state.rows.map((r) => (
          <li key={r.id} className="recipe-list__item">
            <Link to={`/recipes/${r.id}`}>
              {r.image_url && (
                <img src={r.image_url} alt="" className="recipe-list__thumb" />
              )}
              <div className="recipe-list__meta">
                <div className="recipe-list__name">{r.name ?? 'Untitled'}</div>
                <div className="recipe-list__site">{r.site}</div>
              </div>
            </Link>
          </li>
        ))}
      </ul>
      <Pagination totalPages={totalPages} />
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

```bash
cd web && npm test -- RecipeList
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/RecipeList.tsx web/src/pages/RecipeList.test.tsx
git commit -m "Web: RecipeList page (paginated, loading/error/loaded)"
```

---

## Task 15: TDD `<RecipeDetail>`

**Files:**
- Create: `web/src/pages/RecipeDetail.tsx`, `web/src/pages/RecipeDetail.test.tsx`

- [ ] **Step 1: Write the failing test**

`web/src/pages/RecipeDetail.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('../supabase', () => ({ supabase: { from: vi.fn() } }));
import { supabase } from '../supabase';
import { RecipeDetail } from './RecipeDetail';

function mockSingleResponse(data: unknown, error: unknown = null) {
  const single = vi.fn().mockResolvedValue({ data, error });
  const eq = vi.fn(() => ({ single }));
  const select = vi.fn(() => ({ eq }));
  (supabase.from as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ select });
  return { single, eq, select };
}

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/recipes/${id}`]}>
      <Routes>
        <Route path="/recipes/:id" element={<RecipeDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('<RecipeDetail>', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows loading initially', () => {
    mockSingleResponse(null);
    renderAt('1');
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('renders the normalized recipe on success', async () => {
    mockSingleResponse({
      id: 1,
      source_url: 'https://x/y',
      site: 'diffordsguide',
      name: 'Gin Martini',
      author: 'Jerry Thomas',
      image_url: null,
      jsonld: {
        name: 'Gin Martini',
        recipeIngredient: ['2 oz gin', '1 oz vermouth'],
        recipeInstructions: [{ '@type': 'HowToStep', text: 'Stir.' }],
      },
    });
    renderAt('1');
    expect(await screen.findByRole('heading', { name: 'Gin Martini' })).toBeInTheDocument();
    expect(screen.getByText('2 oz gin')).toBeInTheDocument();
    expect(screen.getByText('Stir.')).toBeInTheDocument();
  });

  it('renders ErrorPage when the recipe is missing', async () => {
    mockSingleResponse(null, { code: 'PGRST116', message: 'no rows' });
    renderAt('999');
    expect(await screen.findByRole('heading', { name: /recipe not found/i })).toBeInTheDocument();
  });

  it('renders ErrorPage on other fetch failures', async () => {
    mockSingleResponse(null, { code: 'OTHER', message: 'boom' });
    renderAt('1');
    expect(await screen.findByRole('heading', { name: /couldn't load/i })).toBeInTheDocument();
    expect(screen.getByText(/boom/i)).toBeInTheDocument();
  });

  it('links to the source URL', async () => {
    mockSingleResponse({
      id: 1,
      source_url: 'https://example.com/x',
      site: 's',
      name: 'X',
      author: null,
      image_url: null,
      jsonld: { name: 'X' },
    });
    renderAt('1');
    const link = await screen.findByRole('link', { name: /view on example\.com/i });
    expect(link).toHaveAttribute('href', 'https://example.com/x');
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd web && npm test -- RecipeDetail
```

Expected: fails with `Cannot find module './RecipeDetail'`.

- [ ] **Step 3: Implement**

`web/src/pages/RecipeDetail.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { supabase } from '../supabase';
import { ErrorPage } from '../components/ErrorPage';
import { normalizeRecipe } from '../normalizeRecipe';
import type { RecipeRow } from '../types';

type State =
  | { status: 'loading' }
  | { status: 'notfound' }
  | { status: 'error'; message: string }
  | { status: 'loaded'; row: RecipeRow };

export function RecipeDetail() {
  const { id } = useParams();
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });

    supabase
      .from('recipes_public')
      .select('*')
      .eq('id', id)
      .single()
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) {
          if (error.code === 'PGRST116') {
            setState({ status: 'notfound' });
            return;
          }
          setState({ status: 'error', message: error.message });
          return;
        }
        if (!data) {
          setState({ status: 'notfound' });
          return;
        }
        setState({ status: 'loaded', row: data as RecipeRow });
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  if (state.status === 'loading') return <div className="page">Loading…</div>;
  if (state.status === 'notfound')
    return <ErrorPage title="Recipe not found" message="No recipe with that ID." />;
  if (state.status === 'error')
    return <ErrorPage title="Couldn't load recipe" message={state.message} />;

  let normalized;
  try {
    normalized = normalizeRecipe(state.row.jsonld);
  } catch (err) {
    return (
      <ErrorPage
        title="Couldn't display recipe"
        message={err instanceof Error ? err.message : String(err)}
      />
    );
  }

  const host = safeHost(state.row.source_url);

  return (
    <div className="page recipe-detail">
      <p>
        <a href="/">← Back to recipes</a>
      </p>
      {normalized.images[0] && (
        <img src={normalized.images[0]} alt="" className="recipe-detail__hero" />
      )}
      <h1>{normalized.name}</h1>
      {(normalized.author || state.row.site) && (
        <p className="recipe-detail__byline">
          {normalized.author && <>By {normalized.author} · </>}
          {state.row.site}
        </p>
      )}
      {normalized.description && <p>{normalized.description}</p>}
      {(normalized.yield || normalized.prepTime || normalized.cookTime || normalized.totalTime) && (
        <ul className="recipe-detail__meta">
          {normalized.yield && <li>Yield: {normalized.yield}</li>}
          {normalized.prepTime && <li>Prep: {normalized.prepTime}</li>}
          {normalized.cookTime && <li>Cook: {normalized.cookTime}</li>}
          {normalized.totalTime && <li>Total: {normalized.totalTime}</li>}
        </ul>
      )}
      {normalized.ingredients.length > 0 && (
        <>
          <h2>Ingredients</h2>
          <ul>
            {normalized.ingredients.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </>
      )}
      {normalized.instructions.length > 0 && (
        <>
          <h2>Instructions</h2>
          {normalized.instructions.map((step, i) =>
            step.kind === 'step' ? (
              <p key={i}>{step.text}</p>
            ) : (
              <section key={i}>
                {step.heading && <h3>{step.heading}</h3>}
                <ol>
                  {step.steps.map((s, j) => (
                    <li key={j}>{s}</li>
                  ))}
                </ol>
              </section>
            ),
          )}
        </>
      )}
      <p>
        <a href={state.row.source_url} target="_blank" rel="noreferrer">
          View on {host}
        </a>
      </p>
    </div>
  );
}

function safeHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return 'source';
  }
}
```

- [ ] **Step 4: Run tests**

```bash
cd web && npm test -- RecipeDetail
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/RecipeDetail.tsx web/src/pages/RecipeDetail.test.tsx
git commit -m "Web: RecipeDetail page (normalized render + error states)"
```

---

## Task 16: Router, App, catch-all 404

**Files:**
- Modify: `web/src/App.tsx`, `web/src/main.tsx`

- [ ] **Step 1: Replace `App.tsx`**

`web/src/App.tsx`:

```tsx
import { Routes, Route } from 'react-router-dom';
import { RecipeList } from './pages/RecipeList';
import { RecipeDetail } from './pages/RecipeDetail';
import { ErrorPage } from './components/ErrorPage';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<RecipeList />} />
      <Route path="/recipes/:id" element={<RecipeDetail />} />
      <Route
        path="*"
        element={<ErrorPage title="Page not found" message="That URL doesn't match any page." />}
      />
    </Routes>
  );
}
```

- [ ] **Step 2: Update `main.tsx`**

`web/src/main.tsx`:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
```

(The `./styles.css` import is for the next task — file will be created there. TypeScript does not error on CSS imports because Vite provides ambient types.)

- [ ] **Step 3: Type-check**

```bash
cd web && npx tsc --noEmit
```

Expected: may error on `./styles.css` if the file doesn't exist yet. If so, proceed to Task 17 first, then come back and re-check. Otherwise: no errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/App.tsx web/src/main.tsx
git commit -m "Web: App routes + catch-all 404"
```

---

## Task 17: Minimal CSS

**Files:**
- Create: `web/src/styles.css`

- [ ] **Step 1: Write the stylesheet**

`web/src/styles.css`:

```css
* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: system-ui, -apple-system, sans-serif;
  line-height: 1.5;
  color: #222;
  background: #fafafa;
}

a { color: #0a58ca; }

.page {
  max-width: 720px;
  margin: 0 auto;
  padding: 1.5rem 1rem 3rem;
}

.error-page h1 { margin-bottom: 0.25rem; }

.recipe-list {
  list-style: none;
  padding: 0;
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.75rem;
}

.recipe-list__item a {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  padding: 0.5rem;
  border: 1px solid #e5e5e5;
  border-radius: 6px;
  background: #fff;
  text-decoration: none;
  color: inherit;
}

.recipe-list__item a:hover { background: #f3f4f6; }

.recipe-list__thumb {
  width: 64px;
  height: 64px;
  object-fit: cover;
  border-radius: 4px;
  flex-shrink: 0;
}

.recipe-list__name { font-weight: 600; }
.recipe-list__site { font-size: 0.85rem; color: #666; }

.pagination {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  justify-content: center;
  margin-top: 1.5rem;
}

.pagination button {
  padding: 0.4rem 0.75rem;
  border: 1px solid #ccc;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
}

.pagination button:disabled { opacity: 0.4; cursor: not-allowed; }

.recipe-detail__hero {
  width: 100%;
  max-height: 360px;
  object-fit: cover;
  border-radius: 6px;
}

.recipe-detail__byline { color: #666; }

.recipe-detail__meta {
  list-style: none;
  padding: 0;
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
  color: #444;
  font-size: 0.9rem;
}

.recipe-detail__meta li {
  padding: 0.25rem 0.6rem;
  background: #eee;
  border-radius: 3px;
}
```

- [ ] **Step 2: Type-check (should now succeed)**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/styles.css
git commit -m "Web: minimal plain CSS"
```

---

## Task 18: `.gitignore` for the `web/` subtree

**Files:**
- Create: `web/.gitignore`

- [ ] **Step 1: Write the ignore file**

`web/.gitignore`:

```
node_modules/
.env.local
dist/
.vite/
```

- [ ] **Step 2: Verify nothing you don't want is staged**

```bash
cd /workspaces/spiritolo && git status --ignored web/
```

Expected: `web/node_modules/` appears under "Ignored files"; `.env.local` (if present) also ignored.

- [ ] **Step 3: Commit**

```bash
git add web/.gitignore
git commit -m "Web: .gitignore for node_modules, env, build output"
```

---

## Task 19: Document it in `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Append a "Web UI" section**

Add this section at the end of `/workspaces/spiritolo/CLAUDE.md`:

```markdown
## Web UI

A basic Vite + React + TypeScript SPA under `web/` for verifying the extracted recipes. Reads the `recipes_public` view via the anon key — no backend.

**One-time setup:**

```bash
cd web
npm install
cp .env.local.example .env.local
# edit .env.local and paste in the anon key from `supabase status` on the Mac host
```

**Running:**

```bash
cd web && npm run dev
```

Vite binds to `localhost:5173`; VS Code auto-forwards the port to the Mac host. Supabase must be running locally on the Mac host (see the JSON-LD Extractor section above).

**Tests:**

```bash
cd web && npm test
```

Every unit of logic is built red-first (Vitest + `@testing-library/react`). The main suite is `normalizeRecipe.test.ts`, which covers the messy Schema.org Recipe variants.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "Docs: document basic web UI setup and usage"
```

---

## Task 20: Manual verification

This task produces no commits — it's a checklist for the engineer to confirm the feature works end-to-end.

- [ ] **Step 1: Confirm Supabase is up on the Mac host**

On the Mac host: `supabase status`. Note the anon key.

- [ ] **Step 2: Configure the env**

In the devcontainer:

```bash
cp web/.env.local.example web/.env.local
```

Edit `web/.env.local` and paste the anon key.

- [ ] **Step 3: Start the dev server**

```bash
cd web && npm run dev
```

Expected: Vite binds to `:5173`; VS Code pops a "Ports" notification offering to open in browser.

- [ ] **Step 4: Visit the list page**

Open `http://localhost:5173/` in the Mac browser. Expected:
- Up to 50 recipes render with name, site, and (when present) thumbnail.
- Total pages match `select count(*) from recipes_public;` divided by 50 (ceiling).
- Prev is disabled on page 1. Click Next; URL becomes `?page=2`; new rows load.

- [ ] **Step 5: Visit a detail page**

Click any recipe. Expected: `/recipes/:id` renders name, ingredients, instructions, source link. No console errors.

- [ ] **Step 6: Visit 10 random recipes**

Pick 10 IDs across sites; visit each. Expected: no crashes, content is readable.

- [ ] **Step 7: 404 check**

Visit `http://localhost:5173/nope`. Expected: "Page not found" ErrorPage with a link home.

- [ ] **Step 8: Missing recipe check**

Visit `http://localhost:5173/recipes/99999999`. Expected: "Recipe not found" ErrorPage.

- [ ] **Step 9: Fetch-failure check**

In `web/.env.local`, temporarily point `VITE_SUPABASE_URL` at `http://localhost:1` (unreachable). Restart `npm run dev`. Visit `/`. Expected: "Couldn't load recipes" block renders with an error message. Restore the URL when done.

- [ ] **Step 10: Run the full test suite**

```bash
cd web && npm test
```

Expected: all tests pass.

- [ ] **Step 11: Type-check**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 12: Build**

```bash
cd web && npm run build
```

Expected: exits 0.
