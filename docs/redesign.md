# Spiritolo v2.1 Redesign — Plan

**One reviewable doc to build off of.** The target architecture plus 34 RED/GREEN
TDD workstreams sized for one agent each. This is a plan, not implemented code —
review, ratify the two decisions in §3, then execute.

Interactive one-pager (architecture + end-to-end sequence diagram):
**https://claude.ai/code/artifact/43e7ba6a-d574-4e0d-97ea-3a1a78a20868**

## Contents

1. Orientation — what we're building
2. Tracts & the one gate
3. Decisions to ratify
4. Reconciliation notes
5. Dependency backbone & what starts now
6. How to kick off an agent
7. Consolidated YAGNI — what we deliberately do not build
8. Conventions — TDD, testing, workstream template
9. Foundation — Data & Process Model
10. Foundation — UI System & Review/Edit
11. Foundation — DevOps, CD & Setup Runbook
12. Workstreams — Tract A · RecipeGF v0.4.0 (A1–A6)
13. Workstreams — Tract B core · Content Model + Pipeline (B1–B14)
14. Workstreams — Tract B platform · Queue/Worker/Audit/UI/DevOps (B20–B33)

---

## 1. Orientation — what we're building

RecipeGF becomes the **single canonical recipe representation**. One
RecipeGF-shaped document per recipe (`recipe_docs`) is the source of truth; it
starts partial at `extract` and grows field-by-field through the pipeline.
Pipeline-internal fields live in an `_x` sidecar **stripped at export**, so the
portable subset is byte-identical to the exported pin-2 bundle. Dedup, taxonomy,
and search are **pure functions and indexes over the docs**, never a parallel
model.

- **One unified pipeline of jobs**: `discover → classify → fetch → extract →
  parse → map → role/cluster → export`. Every "smart" stage is a **provider
  chain** (config, not code): `extract = [mechanical JSON-LD → LLM]`,
  `parse = [deterministic → LLM]`, `map = [alias/lexical → LLM]`. Providers:
  `deterministic | local (barbot via Tailscale) | openai | claude | deepseek`.
  Free-local is the default; **chain order/models are tunable config you rewire
  after your LLM spike** — no code change.
- **Postgres-as-queue**: a `jobs` table is the dispatch layer; the worker claims
  with `FOR UPDATE SKIP LOCKED`; the UI enqueues via a `SECURITY DEFINER` RPC and
  reads status via Realtime. No broker, no API server.
- **Three distinct process tables** (never conflated): `stage_runs` (the run
  ledger — latest-per-`(entity,stage)`, prunable), `audit_log` (append-only,
  rich: *who* changed *what* to *what*, human vs worker vs system), and
  `jobs`/`job_batches` (the queue).
- **Fully cloud, ~$30/mo**: one Supabase Postgres (Pro), one Railway worker,
  Cloudflare R2 for the 16 GiB corpus (bytes only; the lightweight `pages` row
  stays in Postgres), Vercel SPA. `fetch` uses ScraperAPI (a metered HTTP API).
- **Clean slate**: rebuild all content cold from two preserved inputs — the
  corpus (→ R2) and the `pages` table (denylist). Taxonomy + name pool
  regenerate bottom-up and are re-curated in the UI.
- **The UI (`/ops`) is the operating surface**: trigger scoped runs (one URL /
  multiselect / filter / whole queue), watch live status, browse every DB, and
  **review/edit after a batch** — edits route through an RPC that writes content
  *and* appends one `audit_log` row (actor = human).

---
## Model amendment (ratified) — RecipeGF-shaped RELATIONAL storage, generated on demand

This supersedes the "one canonical JSONB `recipe_docs` doc with an `_x` sidecar, stripped at export" model wherever it appears below (§1, §9, the sequence diagram, and workstreams B2/B3/B5/B8–B13).

**Why:** the ingredient→taxonomy resolution (e.g. "american bourbon" → "bourbon") changes often, driven by taxonomy curation, and is inherently *shared* — fix it once and every recipe follows. Baking the resolved slug into a canonical per-recipe doc loses fix-once and forces a doc rewrite on every correction. Resolution is cheap and volatile — exactly what not to freeze.

**The model:**
- **Canonical, stable, stored** — the recipe in RecipeGF shape, RELATIONALLY: `recipes` (header + raw `source` jsonld), `recipe_ingredients` (RecipeGF ingredient rows: name/amount/amount_max/unit/modifiers), `recipe_steps` (RecipeGF verb-frame steps). These parse/convert outputs don't change when the taxonomy changes.
- **Canonical, shared, corrected-often** — the taxonomy + a name-keyed `name → taxonomy` resolution (fix once, applies everywhere). Never stored per recipe-ingredient.
- **Derived, generated on demand** — each ingredient's `ref`/slug + `role`, cluster/variant keys, similarity/search indexes, and the full RecipeGF **bundle** `{recipe, verbs, meta}` assembled from the relational rows + current resolution + verb-defs. Always current w.r.t. the taxonomy.
- **Freeze on export** — a bundle published to a consumer (Barbot) is a frozen snapshot; the live representation stays current.

RecipeGF is still THE representation — the relational columns ARE RecipeGF's fields — just normalized (queryable, correctable) rather than a frozen blob, serialized on demand.

**Consequences:** no `recipe_docs`, no `_x`, no `strip_x`. The WHAT/HOW split is now at the table level (content tables = public recipe facts; `stage_runs` = HOW), so "hide `_x` from anon" no longer applies. B2 = the relational schema (this PR). B3 (strip_x) → a `generate_bundle(recipe_id)` module (rows + resolution + verbs). B5 → the relational tables are the queryable graph; add derived materializations (resolution/role/cluster) as needed. B8–B13 stages write relational rows (parse→recipe_ingredients; map→the shared resolution; role/cluster→derived; export→generate+freeze the bundle).
---

## 2. Tracts & the one gate

| Tract | Repo | Delivery | Workstreams |
|---|---|---|---|
| **A — RecipeGF v0.4.0** | `~/code-projects/RecipeGF` | self-reviewed PRs → **tag `v0.4.0`** | A1–A6 |
| **B — Pipeline rebuild** | `spiritolo` | PRs → `main` | B1–B14 (core), B20–B33 (platform) |

**The only hard gate:** Tract A's ingredient-schema shape (seams A1–A3) must be
frozen and the `v0.4.0` tag cut (A5) before Spiritolo can pin it (A6/B1) and
freeze the doc-schema (B3). **Everything else in B can start immediately** (§5).

## 3. Decisions (ratified)

1. **Ingredient `ref` is reverse-DNS — RATIFIED.** `ref` = `com.spiritolo/<slug>`;
   bare `spiritolo/...` stays verbs-only. Grammar = recipe-id minus `:vN`
   (authority ≥2 dot-labels). Spiritolo emits `com.spiritolo/<slug>`.
2. **`modifiers` is `string[]`, the SAME shape on steps and ingredients —
   RATIFIED.** A modifier value is an array of freeform, unlabeled human notes,
   never validated. Rationale: modifiers are just multiple notes; an *object*
   presumes note-categories we can't reliably assign, and an object-of-arrays is
   overkill.
   - **Consequence — A3 grows.** RecipeGF `step.modifiers` is an *object* today, so
     standardizing on array **also changes the step shape** (`{note:"x"}` →
     `["x"]`). This is a breaking change to a never-validated field — cheap
     pre-release (Spiritolo is the only consumer; v0.4.0 is being cut anyway).
     A3 now: (a) flip `step.modifiers` object→array in the schema, `models.py`,
     `types.ts`, `examples/*.yaml`, and conformance fixtures; (b) add an identical
     `ingredient.modifiers` array; (c) update Spiritolo's converter and the
     `recipegf_steps.modifiers` storage/tests to arrays. Contents-standardization
     (a note vocabulary) stays deferred.

## 4. Reconciliation notes

The two B halves were drafted independently (B1–B14 core; B20–B33 platform).
Three seams to merge — do each once, not twice:

1. **A6 ≡ B1.** "Bump the recipegf pin to v0.4.0 + retire the local unit tables"
   appears in both Tract A (A6) and Tract B core (B1). **It is one workstream** —
   the first gated Spiritolo PR. Assign it once; drop the duplicate.
2. **B6 + B20 share the `pages` migration.** B20 owns the `pages` migration + the
   corpus→R2 **loader** (write-once upload + backfill); B6 owns the corpus
   **reader** module. Land **one** `pages` migration (B20's); B6 adds only the
   reader.
3. **ID ranges are cosmetic.** B1–B14 and B20–B33 are two halves of one tract.
   Optionally renumber to `BC*`/`BP*` when opening tracking issues; §5 is the
   authoritative dependency map.

## 5. Dependency backbone & what starts now

The workstreams' internal `depends_on` lines use each author's local numbering;
**this section overrides where they differ.**

```
TRACT A (RecipeGF)          A1 ─► A2 ─► A3 ─┐
  (A1/2/3 serialize on the  A4 ────────────┼─► A5  [TAG v0.4.0]  ◄── THE GATE
   shared schema files)                     │
                                            └───────────────┐
TRACT B CORE                                                ▼
  no-gate scaffolding (start now):  B2(recipe_docs) B4(stage_runs) B6(corpus reader) B7(provider-chain)
  gated on the tag:                 A6/B1(pin) ─► B3(doc-schema) ─► B8(runner) ─► B9►B10►B11►B12►B13 ─► B14(cold-build)
                                                    (B5 projections ← B2,B3)   (stages chain extract→…→export)
TRACT B PLATFORM (mostly start now)
  B20(pages+R2 load) ─► B21(CD)         B22(jobs/RPCs) ─► B23(worker) ─► B24(batch), B25(docker/tailscale)
  B26(audit)                            B27(tokens+hooks) ─► B28(primitives) ─► B29(ops shell) ─► B30(browsers)
                                        B30 ─► B31(triggers), B32(review/edit ← B26), B33(corpus iframe ← B20)
```

**Corrected cross-tract dependencies** (overriding local-numbering slips):
`B22`(jobs)→**B2**(recipe_docs); `B23`(worker)→**B4**(stage_runs)+B22;
`B26`(audit)→**B2**; `B29`(dashboard)→**B4**+B28; `B30`/`B13`(exports)→**A5 tag**.

**Start in parallel now (before the gate), ~15 agents:**
- **Core scaffolding:** B2, B4, B6, B7, then B5 (after B2).
- **Platform:** B20, B21 (after B20), B22 (after B2), B23 (after B22+B4), B24,
  B25, B26 (after B2).
- **UI:** B27, B28 (after B27), B29 (after B28+B4), B31.

**Gated on the `v0.4.0` tag:** A6/B1 (pin) → B3 → B8 → B9–B13 → B14; and B30,
B32, B33. Tract A is short and mostly serial (A1→A2→A3 share the schema file);
A4 runs alongside. Cut A5 the moment A1–A4 are merged and green.

## 6. How to kick off an agent

Each workstream below (a `### <ID>` block in §12–14) is **one agent's complete
remit** — goal, files, the RED tests to write first, the GREEN outline, DONE
gates, and YAGNI. To launch one, ask me for **"the prompt for `<ID>`"** and I'll
assemble a ready-to-paste agent prompt from:

- the workstream block itself (§12–14),
- the **Conventions** (§8 — the RED/GREEN loop + the test stack for that surface),
- the relevant **Foundation** section(s) (§9 data model / §10 UI / §11 DevOps),
- the **ratified decisions** (§3) and any **reconciliation** (§4) that touch it.

You can ask for several at once (e.g. "prompts for the ~15 un-gated
workstreams") and I'll emit them as a batch you can fan out to parallel Claude
Code sessions. Each agent works on its own branch, RED-first, and opens a PR.

## 7. Consolidated YAGNI — what we deliberately do not build

- **No second/production environment, no k8s, no Terraform** — one Supabase Pro +
  one Railway worker, direct-CLI runbook. `main` gets migration *validation*;
  `staging` is the sole deploy target.
- **No message broker, no scheduler/cron, no worker HTTP API** — Postgres-as-queue;
  the reaper requeue is the entire retry story; every trigger is manual, scoped,
  one-shot.
- **No parallel recipe model / no stored bundles** — `recipe_docs` is the single
  truth; the bundle is generated on demand; the `recipegf_recipes/_ingredients/_steps`
  trio and the `recipes`/`recipe_ingredients` pair are dropped.
- **No `supa_audit`, no full-diff blobs** — a ~40-line custom trigger captures
  exactly `actor + source + before/after + changed_keys`.
- **No new design system / component library** — extend the taxonomy tokens,
  reuse `EditableField`/`Modal`/`Toast`, hand-roll small primitives
  (`DataTable`, `JsonView`); no ag-grid/react-json-view/react-admin.
- **No WYSIWYG or bulk editing** — one typed edit RPC per editable table, one row
  at a time via the detail pane; shallow `doc||patch`.
- **No provider/order in the DB schema; no OpenAI Batch as a core path** — the
  chain is external config; Batch is an optional accelerator for large hosted
  backfills only.
- **No re-scrape / write-back to R2** — the corpus is write-once, read-only.
- **No new sensory/stylistic taxonomy nodes, no vector layer yet** — the lean
  taxonomy stance holds; pgvector is a later additive lane.
- **No charts library, no saved views, no mobile layout** — `/ops` is a desktop
  tool: counts + status pills, URL-driven filters, `overflow-x:auto`.


---


## 8. Conventions — TDD, testing, workstream template

### Foundation: TDD, Testing & Repo Conventions

This is the contract every workstream in the v2.1 rebuild obeys. It is not a
suggestion — a workstream is not "done" until its RED tests existed and failed
first, its GREEN implementation makes them pass, and its DONE gates are green in
CI. All later workstream specs use the **Workstream Template** at the bottom
verbatim; this section defines what its fields mean and what "a test" looks like
on each surface.

#### 0. Non-negotiables (why TDD here, specifically)

The architecture makes TDD load-bearing rather than ceremonial:

- **Determinism lives at the storage layer.** Dedup/cluster keys hash the
  *stored* parse output and taxonomy **slugs**, not PKs or live LLM calls. So the
  unit under test is almost always a **pure `project(doc)` / hash / grammar
  function** over fixtures — trivially testable, and the test *is* the spec of
  the stored shape.
- **Provider chains are config-not-code.** Every smart stage is
  `[deterministic → llm]`, rewireable after the LLM spike. Tests must pin
  behavior through a **fake/deterministic provider**, never a live model, so the
  suite is hermetic and the chain can be re-ordered without rewriting tests.
- **Clean slate.** There is no data to protect behaviorally except the two
  preserved inputs (HTML corpus, `pages`). Every content table is
  TRUNCATE-and-rebuild by a pure function. That property is the single most
  important thing tests assert, and it only stays true if asserted first.

#### 1. The RED / GREEN loop (exact)

Every unit of work is one pass of this loop. A workstream is a sequence of
passes.

1. **RED — write the failing test first.**
   - Pick the smallest observable behavior from the workstream's `RED` list.
   - Write the test in the surface's stack (below). Add fixtures, not
     implementation.
   - **Run it and confirm it fails for the intended reason** (assertion/ImportError,
     not a typo or a missing fixture). A test that errors on setup is not a valid
     RED — fix the harness until it fails on the assertion.
     - `cd ingredients && uv run --extra dev pytest tests/test_X.py::test_case -q`
     - `cd web && npm test -- src/foo.test.tsx` (Vitest; `npm test` = `vitest run`)
     - RecipeGF TS: `npm test -w packages/core`; Python: `cd python && uv run pytest -q`
2. **GREEN — minimal implementation.**
   - Write the least code that makes the RED test pass. No speculative fields, no
     unused branches (see YAGNI).
   - Re-run the same command; the target test goes green.
3. **Refactor under green.**
   - Clean up with the whole file's tests green. Never refactor red.
4. **Widen.** Repeat 1–3 for the next `RED` bullet until the workstream's `DONE`
   gates are all satisfied.

**Version-gate discipline (pipeline stages).** Any change to a stage's logic
bumps its `*_VERSION` constant *in the same commit as the test that pins the new
behavior*. The queue predicate is "content qualifies AND NOT EXISTS(stage_run @
current version)", so a RED test for a version bump asserts both the new output
**and** that a prior-version row re-queues under `--reset --except-version`.

**Commit boundary.** One logical RED→GREEN→refactor slice per commit is ideal;
never commit a red suite. CI is the backstop, the loop is the practice.

#### 2. Test stacks per surface

##### 2a. Python packages (`common/`, `scraper/`, `ingredients/`, `scripts/`) — pytest over the uv workspace

Root `pyproject.toml` is a uv workspace (`members = ["common","scraper",
"ingredients","scripts"]`). Run pytest from the package dir with `uv run`.
`recipegf` is a pinned git dependency in `ingredients/pyproject.toml`
(`[tool.uv.sources] recipegf = { git=…, tag="v0.4.0", subdirectory="python" }`).

Two test tiers:

- **Pure-Python (no DB).** The default and the majority. Provider outputs,
  `project(doc)` projections, grammar/parse/hash functions, converter behavior.
  Model these on `ingredients/tests/test_recipegf_converter.py`: import the pure
  function, feed a fixture dataclass, assert on the returned structure. No
  network, no DB, no live LLM. These run everywhere with just `uv sync`.

- **DB-integration against `TEST_DB_URL`.** A *separate* Postgres DB from
  `SUPABASE_DB_URL`. The **auto-migrate conftest pattern** is the reusable
  harness — reuse `ingredients/tests/conftest.py` as-is; do **not** write a new
  bespoke one. What it gives every DB test for free (all load-bearing, keep them):
  - Session-scoped autouse `_ensure_test_db_migrated`: CREATEs the test DB if
    missing, **stubs the Supabase surface a bare Postgres lacks** (`anon` /
    `authenticated` / `service_role` roles with `service_role` BYPASSRLS, the
    `auth` schema + `auth.users` + `auth.uid()`, the `extensions` schema and the
    `search_path … , extensions` that unqualified `pg_trgm` needs), applies any
    new `supabase/migrations/*.sql` incrementally (tracked in
    `_test_db_migrations`), then TRUNCATEs all public tables. **Adding a new
    migration needs zero conftest changes** — the next run picks it up.
  - `SUPABASE_DB_URL` is clobbered to an invalid sentinel after `.env` loads, so
    any code that defaults to the dev DB fails loud instead of wiping it.
  - Safety guards refuse to run if `TEST_DB_URL` == `SUPABASE_DB_URL`, points at
    `postgres`, or lacks `test` in its name.
  - **Fail-loud, never skip.** `test_db_url` fixture `pytest.fail`s when unset —
    a silent skip that hides a coverage gap is banned. (The `scripts` upload suite
    uses `pytest.skip` because those DBs are derived/ephemeral; that is the one
    documented exception.)
  - Fixtures to compose: `db_conn` (raw psycopg for `information_schema` +
    grant/RLS assertions), `isolated_db` (wrapper, truncate-around),
    `fixture_taxonomy` / `dedup_fixture` (seed from `eval_fixture`, not from prod
    seeds, so results don't drift). New content tables (`recipe_docs`, `jobs`,
    `stage_runs`, `audit_log`, projections) add a sibling fixture in the same
    style; they do not fork the conftest.

  **The `scripts/` upload smoke conftest is a second, distinct pattern** for
  tests that need *two* DBs simulating local↔staging: it derives
  `<base>_upload_local` / `<base>_upload_staging` from `TEST_DB_URL`,
  DROP+CREATEs them per session, replays all migrations fresh with a
  `supabase_migrations.schema_migrations` ledger, and skips cleanly when
  `TEST_DB_URL` is unset. Reuse it for any new two-database flow.

- **SQL migration tests.** A migration is code; it gets RED tests too, run
  through the same auto-migrate conftest (the new `*.sql` is auto-applied):
  - **Shape:** `db_conn` queries `information_schema.columns` /
    `.table_constraints` to assert columns, types, NOT NULLs, CHECKs (e.g. the
    kebab `slug !~ '_'` CHECK on `taxonomy_proposals.proposed_slug`), unique
    constraints (`recipe_docs.source_url`), generated columns
    (`recipe_docs.site`), and GIN indexes on `doc`.
  - **Behavior:** insert rows and assert triggers/derived columns/UPSERT
    idempotency and the projection invariant ("no fact lives only in a
    projection" → TRUNCATE a projection, re-run `project()`, assert byte-equal).
  - **Boundary (grants/RLS/RPC):** assert the read-surface EXECUTE boundary the
    conftest is explicitly built to exercise — e.g. a `SECURITY DEFINER`
    `enqueue_job()` / `approve_job()` RPC is EXECUTE-grantable to
    `authenticated` but the underlying table is not directly writable by `anon`.
    Test by `SET ROLE anon` / `SET ROLE authenticated` on `db_conn` and asserting
    grant/deny.

##### 2b. Web (`web/`) — Vitest + @testing-library/react

Stack (already in `web/package.json`): `vitest`, `@testing-library/react`,
`@testing-library/user-event`, `@testing-library/jest-dom`, `jsdom`,
`MemoryRouter`. `npm test` = `vitest run`.

- **Pure normalizers/hooks** — model on `normalizeRecipe.test.ts`: table-drive
  the messy-input variants, assert exact output, and keep one
  `toMatchSnapshot()` on a real end-to-end fixture blob to catch shape drift.
- **Components** — model on `NodeCard.test.tsx`: render inside `<MemoryRouter>`,
  drive with `userEvent`, assert by **role/label/text** (accessible queries), not
  DOM internals. Mock Supabase at the module boundary
  (`vi.mock('../../supabase', …)`) and stub the fluent chain
  (`from().select().eq().order()`), including the never-resolving default so
  loading states are testable.
- **Shared UI/UX kit — test once, compose everywhere.** The QoL requirement
  ("an improvement in one view lands on all views") is enforced by tests: the
  shared kit (buttons, `EditableField`, `Toast`, table/row primitives, status
  chips, the `useEnqueueJob`/admin-RPC hooks) gets its **own** unit tests; each
  `/ops` view test then asserts it *composes the kit component* (queries the
  kit's role/label), rather than re-testing the widget's internals. Reuse the
  existing `RequireAdmin` / `useIsAdmin` / `taxonomy/rpcs.ts` SECURITY-DEFINER
  pattern; admin-edit flows are tested as "click edit → RPC called with args →
  Toast shown", mocking the RPC.

##### 2c. RecipeGF (`~/code-projects/RecipeGF`) — TS Vitest + Python pytest + the conformance-fixture contract

RecipeGF ships two implementations that must agree. Its CI (`.github/workflows/
ci.yml`) has three jobs and Tract A must keep all three green:

1. `ts` — `npm install --ignore-scripts` → `npm run build --workspaces` →
   `npm test -w packages/core`.
2. `python` — `uv sync` → `uv run pytest -q` in `python/`.
3. `spec-sync` — `npm run gen:standard-units` → `npm run sync:spec` →
   `git diff --exit-code`. This **fails on drift** between the canonical `/spec`
   and the vendored copies (`packages/core/{schema,registry}`,
   `python/src/recipegf/_spec/{schema,registry}`).

Two contracts a Tract-A workstream must honor when it touches the interface:

- **Cross-language conformance fixtures.** `spec/conformance/manifest.yaml` lists
  cases `{file, valid: bool, overlay?}`. Both `packages/core/src/
  conformance.test.ts` and `python/tests/test_conformance.py` parametrize over
  the *same* manifest and assert **only the boolean `valid`** (error messages are
  implementation-specific, intentionally not asserted). RED for a new interface
  rule = add a `valid`/`invalid` fixture (and an `overlays/spiritolo/…` verb-def
  if namespaced) to the manifest; it fails in *both* languages until both
  implement it. This is the mechanism that keeps TS and Python from drifting.
- **Schema↔code parity.** `RECIPE_ID_PATTERN` is asserted equal to the vendored
  schema's `id.pattern` (`test_recipe_id.py::test_pattern_matches_schema`, mirror
  in `recipe-id.test.ts`). The new `python/src/recipegf/ingredient_ref.py` gets
  the **same parity test**: its `INGREDIENT_REF_PATTERN` (portable
  `<authority>/<slug>` grammar = recipe-id minus `:vN`) asserted equal to the
  schema's `ingredient.ref.pattern`, in both languages. Validator code-tier rules
  (`amount_max >= amount`) get their own conformance fixtures too.
- **Unit registry migration.** Moving Spiritolo's ~66-unit vocabulary into
  `spec/registry/units/{bar,count,standard}` makes RecipeGF the sole unit
  authority. Keep it generated where generated (`gen-standard-units.mjs`,
  guarded by `standard-units.test.ts`) and let `spec-sync` prove no vendored copy
  drifted. Spiritolo then bumps the pin and deletes `_UNIT_TRANSLATE` /
  `_OZ_PER_UNIT` / `UNIT_ALIASES` — with its converter tests (e.g.
  `test_tbsp_unit_translated_to_recipegf_valid`, which expects `Tbs`) still
  green against the pinned tag.

#### 3. Provider-chain & cost testing (applies to every smart stage)

- **Never call a live model in a test.** The chain is `[deterministic → llm]`;
  tests inject a **fake provider** (returns canned structured output or raises)
  through the same config seam the owner uses to rewire providers. Assert: chain
  order is honored, deterministic tier short-circuits when it resolves, llm tier
  is only reached on abstain, and the *stored* output (what dedup hashes) is
  what the test pins.
- **Packing:** assert N-item requests pack/unpack correctly against the fake
  provider (map inputs→outputs by id, partial-failure parks the right items) —
  mirror the existing chunked-batch "park unresolved at `pending_llm_tried`"
  discipline.
- **Confirm-before-cost / hard cap:** metered work (hosted LLM, ScraperAPI) is
  tested without spending: assert `enqueue_job` records a `cost_estimate_cents`
  for the scoped set, `approve_job` is required when `requires_approval`, and the
  worker **refuses/aborts past `max_cost_cents`**. The fake provider reports a
  per-call cost so the cap logic is exercised deterministically.
- **Queue mechanics:** `SELECT … FOR UPDATE SKIP LOCKED` claim, idempotent UPSERT
  writes, and the reaper requeueing a stale-heartbeat job are DB-integration
  tests on the `jobs` table via `db_conn` (two connections to prove SKIP LOCKED).

#### 4. Branch / PR conventions

- **Spiritolo workstreams.** Work on the `claude/<topic>-<short-id>` branch named
  in the session task; never push elsewhere. `gh pr create` against **`main`**
  (occasionally `development`). Optional one-paragraph description, up to 8
  bullets, **no sections, no test plan**. After merge: check out `main`, pull,
  delete the branch. The relevant CI gate runs on the PR:
  `ingredients-ci.yml` (Postgres 16 service, `TEST_DB_URL=…/spiritolo_test`,
  `uv run --extra dev pytest`) for `ingredients/**` · `common/**` ·
  `supabase/migrations/**` · `pyproject.toml` · `uv.lock`; the web/Vitest gate
  for `web/**` (add to CI as part of Tract B if not already wired).
- **Migrations → staging.** Schema reaches staging only via
  `deploy-migrations.yml` on push to `staging`; promotion is a PR **base
  `staging`, head `main`** merged with a **merge commit, never squash**.
- **RecipeGF (Tract A).** Lands via **self-reviewed PRs** on `~/code-projects/
  RecipeGF`, each keeping the three CI jobs green, then a **tag `v0.4.0`**. All
  changes are optional-additive; `schema` const stays `recipegf/cocktail/v1`.
  Spiritolo consumes it by bumping the `tag` in `ingredients/pyproject.toml`
  `[tool.uv.sources]` — a deliberate, separate Spiritolo PR. **Tract A gates
  Tract B's doc-schema**: B cannot freeze `recipe_docs` doc-schema until A's
  ingredient shape (`amount_max`, `modifiers`, `ref`) is tagged.

#### 5. The Workstream Template (every workstream in the plan uses this verbatim)

Each field, with allowed values and rules:

| Field | Meaning / allowed values |
|---|---|
| **id** | `WS-<tract><n>` — `A` = RecipeGF, `B` = Spiritolo pipeline (e.g. `WS-A1`, `WS-B3`). Stable; referenced by `depends_on`. |
| **title** | Imperative one-liner ("Add `ingredient.ref` grammar + parity test"). |
| **repo** | `recipegf` or `spiritolo`. Determines branch/PR + CI rules (§4). |
| **goal** | 1–2 sentences: the observable capability delivered. No implementation. |
| **depends_on** | List of workstream ids that must merge (and, for A→B, **tag**) first. `[]` if none. Cross-tract deps name the tag (e.g. "WS-A* tagged v0.4.0"). |
| **parallelism** | One of: `parallel-safe` (disjoint files, no dep) · `serialize-after WS-x` (shares files/schema with x) · `blocks WS-y`. State *why* (which files/tables overlap). |
| **files-touched** | Concrete repo-relative paths created/edited, incl. the test files. Migrations get the next `supabase/migrations/NNNN_*.sql`. This is the overlap map that makes `parallelism` checkable. |
| **RED** | The **specific failing tests to write first**, listed one per behavior, each naming the file and the assertion. Not "add tests" — the actual cases. This is the heart of the workstream. |
| **GREEN** | Implementation outline: the minimal modules/functions/columns/RPCs that turn RED green. Bulleted, no code unless a signature is load-bearing. |
| **DONE** | Acceptance + CI gates: which suites go green, which CI job must pass on the PR, any version-constant bump, and the projection/parity invariant re-asserted. Merge criteria. |
| **YAGNI** | What a tempted builder would add here and we deliberately do **not** build. At least one bullet; empty is a smell. |

##### Worked example A (RecipeGF, shows conformance + parity):

```
id: WS-A1
title: Add ingredient.ref portable-grammar + amount_max + modifiers seams
repo: recipegf
goal: RecipeGF gains three optional-additive ingredient seams (quantity.amount_max,
      ingredient.modifiers, ingredient.ref) so Spiritolo docs carry a portable
      cross-recipe ingredient identifier. schema const unchanged.
depends_on: []
parallelism: serialize-after none; blocks all of Tract B (doc-schema freeze).
files-touched:
  spec/schema/recipegf-cocktail-v1.json          (add ref/amount_max/modifiers)
  spec/conformance/manifest.yaml                 (+ 4 fixtures)
  spec/conformance/{valid,invalid}/ingredient-ref-*.yaml, amount-max-*.yaml
  python/src/recipegf/ingredient_ref.py          (new: parse/validate)
  python/src/recipegf/models.py                  (amount_max on Quantity; ref/modifiers on Ingredient)
  python/tests/test_ingredient_ref.py            (new; parity test)
  packages/core/src/ingredient-ref.ts + .test.ts (mirror)
RED (write these first, watch them fail):
  - test_ingredient_ref.py::test_pattern_matches_schema — INGREDIENT_REF_PATTERN
    == schema ingredient.ref.pattern (recipe-id grammar minus :vN). Fails: no module.
  - test_ingredient_ref.py::test_accepts/rejects — com.spiritolo/gin valid;
    spiritolo/gin (single-label authority) and com.spiritolo/gin:v1 (has :vN) invalid.
  - conformance: valid/ingredient-ref-portable.yaml -> valid;
    invalid/ingredient-ref-versioned.yaml -> invalid;
    invalid/amount-max-less-than-amount.yaml -> invalid (code-tier rule);
    valid/amount-max.yaml -> valid. Fails in BOTH ts+python until implemented.
  - recipe-id.test.ts mirror of the parity + accept/reject cases.
GREEN:
  - ingredient_ref.py: INGREDIENT_REF_PATTERN, is_valid/parse (mirror recipe_id.py).
  - models.py: optional amount_max: float|None on Quantity; ref/modifiers on Ingredient.
  - validator code tier: reject amount_max < amount.
  - schema: add the three properties + ref.pattern; run sync:spec so vendored copies update.
  - TS: ingredient-ref.ts mirror.
DONE:
  - ci.yml all three jobs green (ts, python, spec-sync git-diff clean).
  - conformance manifest agrees in both languages.
  - self-reviewed PR merged; tag v0.4.0 cut (rolls in the unit-registry WS too).
YAGNI:
  - No ROLE / taxonomy vocabulary in the interface — ref grammar only; role/meaning
    stay Spiritolo-internal (_x). No ingredient-ref *resolution*/lookup in RecipeGF.
  - No new schema-version const; no non-additive changes.
```

##### Worked example B (Spiritolo, shows DB migration + RPC + projection):

```
id: WS-B4
title: jobs queue table + enqueue/approve RPCs + claim/reap
repo: spiritolo
goal: A Postgres-as-queue: UI enqueues scoped jobs via SECURITY-DEFINER RPC,
      approves metered ones, worker claims via SKIP LOCKED, reaper requeues stale.
depends_on: [WS-B1 (recipe_docs base schema)]
parallelism: parallel-safe with web/taxonomy; serialize-after WS-B1 (shares migrations dir ordering).
files-touched:
  supabase/migrations/00NN_jobs.sql
  ingredients/src/ingredients/queue/{claim.py,reaper.py}
  ingredients/tests/test_jobs_queue.py
RED:
  - test_jobs_queue.py::test_schema_shape — information_schema asserts columns
    (stage,state,requires_approval,approved,cost_estimate_cents,max_cost_cents,
    progress jsonb,error_code,batch_id,last_heartbeat,…). Fails: no migration.
  - ::test_enqueue_job_rpc — SET ROLE authenticated; enqueue_job(scope) inserts a
    row with cost_estimate_cents; SET ROLE anon can NOT insert directly (grant boundary).
  - ::test_approve_job_gates_metered — a requires_approval job is unclaimable until approve_job().
  - ::test_claim_skip_locked — two db_conn connections; each claims a distinct job,
    neither blocks (FOR UPDATE SKIP LOCKED).
  - ::test_reaper_requeues_stale_heartbeat — stale last_heartbeat → back to queued; idempotent.
  - ::test_worker_aborts_past_max_cost — fake provider reports cost; job halts at max_cost_cents.
GREEN:
  - migration: jobs table + job_batches; enqueue_job/approve_job SECURITY DEFINER
    RPCs granted EXECUTE to authenticated only; RLS on jobs.
  - claim.py: SELECT … FOR UPDATE SKIP LOCKED + heartbeat.
  - reaper.py: requeue where last_heartbeat < now()-interval; UPSERT-idempotent.
DONE:
  - ingredients-ci.yml green (Postgres service picks up new migration automatically).
  - grant boundary + SKIP LOCKED + cap all asserted.
YAGNI:
  - No message broker, no cron/scheduler (all UI-triggered), no worker HTTP API,
    no priority lanes, no retry backoff curves — reaper requeue is the whole retry story.
```

#### 6. YAGNI for this foundation itself

- No new test framework, runner, or plugin (no tox, nox, Playwright, Cypress,
  hypothesis, factory_boy). pytest + Vitest as they already exist.
- No new/forked conftest — reuse the two that exist (`ingredients`,
  `scripts`); new tables add fixtures, not harnesses.
- No coverage-percentage gate, no mutation testing, no flaky-retry wrapper.
  RED-first discipline + the existing CI green bar is the gate.
- No mocking of Postgres (no sqlite-in-memory, no pgmock) — DB tests hit real
  Postgres via `TEST_DB_URL`; that's what the auto-migrate conftest is for.
- No live-LLM tests, no VCR/cassette recording of model calls — fake providers
  only.
- No shared "test-utils mega-package" up front; extract a helper only on the
  third duplication.
```


## YAGNI cuts
- No new test framework/runner/plugin (no tox, nox, Playwright, Cypress, hypothesis, factory_boy) — pytest + Vitest as they already exist.
- No new or forked conftest — reuse the two existing harnesses (ingredients auto-migrate, scripts two-DB); new tables add fixtures, not harnesses.
- No coverage-percentage gate, no mutation testing, no flaky-test retry wrapper — RED-first + existing CI green bar is the gate.
- No mocking of Postgres (no sqlite-in-memory, no pgmock) — DB tests hit real Postgres via TEST_DB_URL.
- No live-LLM tests and no VCR/cassette recording of model calls — deterministic fake providers only.
- No shared test-utils mega-package up front — extract a helper only on the third duplication.
- No RecipeGF schema-version bump and no non-additive interface changes — v0.4.0 is optional-additive, schema const stays recipegf/cocktail/v1.
- No ROLE/taxonomy vocabulary pushed into the RecipeGF interface — grammar only; role/meaning stay in Spiritolo _x sidecar.
- Workstream Template carries no fields beyond the eleven specified (no estimates, no owner/assignee, no priority score) — parallelism + depends_on + files-touched already encode scheduling.

## Key decisions
- DB-integration test harness for all new tables (recipe_docs, jobs, stage_runs, audit_log, projections) → Reuse ingredients/tests/conftest.py's auto-migrate pattern verbatim (auto-CREATE test DB, stub Supabase role/auth/extensions surface, incremental migration apply tracked in _test_db_migrations, truncate). New tables add sibling fixtures in the db_conn/isolated_db/fixture_taxonomy style; never fork the conftest.
- DB tests skip vs fail when TEST_DB_URL unset → Fail-loud (pytest.fail) as ingredients conftest does — silent skips hide coverage gaps. The scripts upload suite's pytest.skip is the one documented exception (derived ephemeral DBs).
- How smart stages (provider chains) are tested given config-not-code providers → Inject a deterministic/fake provider through the same config seam the owner rewires; never call a live model. Tests pin the STORED output (what dedup hashes) and assert chain order/short-circuit/packing, not model behavior.
- Cross-language RecipeGF drift prevention → Add fixtures to spec/conformance/manifest.yaml (boolean-outcome contract, both languages parametrize it) plus a schema-pattern parity test mirroring test_recipe_id.py::test_pattern_matches_schema, plus the spec-sync git-diff guard. New ingredient_ref.py gets its own parity test in both TS and Python.
- RecipeGF release + Spiritolo consumption flow → RecipeGF lands via self-reviewed PRs keeping all 3 CI jobs green, then tag v0.4.0 (optional-additive only, schema const frozen). Spiritolo bumps the tag pin in ingredients/pyproject.toml [tool.uv.sources] in a separate PR. Tract A tag gates Tract B's doc-schema freeze.
- Workstream Template fields → id, title, repo, goal, depends_on, parallelism, files-touched, RED (specific failing tests listed one per behavior with file+assertion), GREEN (minimal impl outline), DONE (acceptance/CI gates + version bump + invariant), YAGNI (>=1 bullet, empty is a smell). files-touched doubles as the overlap map that makes parallelism checkable.
- Version-gate discipline in the loop → A stage-logic change bumps its *_VERSION constant in the same commit as the pinning test; the RED test asserts both new output AND that prior-version rows re-queue under --reset --except-version.

## Open
- Web CI: ingredients-ci.yml is the only Python PR gate today and there is no committed web/Vitest CI job. Tract B must add a web CI workflow (Vitest run on web/** PRs) — which workstream owns wiring it?
- RECIPEGF_TOKEN: ingredients-ci authenticates the recipegf git dependency via a read-only token secret assuming mrjogo/RecipeGF may be private. Confirm whether v0.4.0 stays reachable to CI (public, or token still provisioned) before Tract B pins it.
- The scripts upload smoke suite skips (not fails) when TEST_DB_URL is unset, diverging from the ingredients fail-loud rule. Confirm this stays the intentional exception, or align both once the queue/worker suites land.
- Provider-chain config seam: the fake-provider injection point depends on the exact stage_fn(job) dispatch + provider-chain config shape, which a Tract-B infra workstream defines. Foundation assumes a single seam; that workstream must expose it test-friendly.



## 9. Foundation — Data & Process Model

### 0. Frame: one content model, three process tables

> **Ratified amendment supersedes this section.** The source-of-truth content
> shape is now RecipeGF-shaped **relational** storage (`recipes` +
> `recipe_ingredients` + `recipe_steps`), not a single `recipe_docs` JSONB doc
> with an `_x` sidecar. Ingredient→taxonomy resolution and the export bundle are
> **generated on demand**, never frozen per recipe. See **"Model amendment
> (ratified) — RecipeGF-shaped RELATIONAL storage, generated on demand"** after
> §1. Read the `recipe_docs`/`_x`/`strip_x` descriptions below as the superseded
> prior design; the concepts (projections, the three process tables) still hold,
> re-homed onto the relational tables.

The redesign has **one source-of-truth content shape** (`recipe_docs`, a
RecipeGF-shaped JSONB doc) plus curated reference data (`taxonomy_*`,
`cocktail_aliases`). Everything else that queries drinks — search rows, cluster
identities, the public view — is a **pure projection** of the docs, never a
parallel model.

Around that content sit **three process tables that are deliberately distinct
concerns**. Conflating any two is the classic mistake; keep them apart:

| Table | Question it answers | Cardinality | Lifecycle |
|---|---|---|---|
| `stage_runs` | "What is the *current* pipeline state of this entity for this stage?" | latest-only, 1 per (entity, stage) | prunable / `--reset` re-queues |
| `audit_log` | "*Who* changed this content, *when*, from *what to what*?" | append-only, 1 per mutation | permanent history |
| `jobs` / `job_batches` | "What work did an operator ask for, and who is running it?" | 1 per operator intent | ephemeral, terminal states retained for ops UI |

They never substitute for one another: `stage_runs` is a *cache of derived
state* (drop it, re-run, identical result); `audit_log` is the *only* durable
record of manual edits (dropping it loses information); `jobs` is *dispatch
intent* (a queue, not a ledger).

The load-bearing invariant across all of this:

> **No fact lives only in a projection or only in a process table.** Durable
> content facts live in `recipe_docs.doc` (+ curated reference tables). Every
> other content table is `TRUNCATE`-and-rebuild by a pure `project(doc)`. Every
> `*_source` / `*_version` / `*_at` / `status` column that used to sit on
> `recipes` / `recipe_ingredients` moves **out** of content into `stage_runs`
> (pipeline state) or `audit_log` (who/when).

---

### 1. Content tables

#### 1.1 `recipe_docs` — the source of truth

One RecipeGF-shaped document per recipe. Starts partial at `extract` and grows
field-by-field through the pipeline. Pipeline-internal fields live in an `_x`
sidecar that is **stripped at export**, so the portable subset is byte-identical
to the exported pin-2 bundle.

```sql
create table recipe_docs (
  id          bigserial primary key,
  source_url  text not null unique,
  doc         jsonb not null,
  doc_schema  text not null default 'spiritolo/recipe-doc/v1',

  -- pipeline cursor: how far this doc has progressed. Advisory/denormalized
  -- for cheap queue gating; the authoritative per-stage truth is stage_runs.
  state       text not null default 'extracted'
              check (state in ('extracted','parsed','mapped','clustered','exported')),

  -- Generated columns projected straight out of the doc so indexes/joins are
  -- cheap and the doc stays the single writer. These are the ONLY structured
  -- columns; adding one is free, removing one loses nothing (it's in the doc).
  site           text generated always as (doc #>> '{_x,site}') stored,
  canonical_name text generated always as (doc #>> '{_x,canonical_name}') stored,
  cluster_key    text generated always as (doc #>> '{_x,cluster_key}') stored,
  variant_key    text generated always as (doc #>> '{_x,variant_key}') stored,
  title          text generated always as (doc ->> 'title') stored,

  updated_at  timestamptz not null default now()
);

create index recipe_docs_doc_gin   on recipe_docs using gin (doc jsonb_path_ops);
create index recipe_docs_site_idx  on recipe_docs (site);
create index recipe_docs_state_idx on recipe_docs (state);
create index recipe_docs_cluster_idx on recipe_docs (cluster_key) where cluster_key is not null;

alter table recipe_docs enable row level security;  -- deny-all; RPC + view only
```

Notes:
- **`jsonb_path_ops` GIN** (not default `jsonb_ops`) — we containment-query the
  doc (`doc @> '{"ingredients":[{"ref":"spiritolo/gin"}]}'`), which
  `jsonb_path_ops` indexes at a fraction of the size. Add a
  `gin (title gin_trgm_ops)` and `gin (canonical_name gin_trgm_ops)` for the
  substring search the current `recipes_search_trgm` migration provides today.
- `state` is a **denormalized convenience cursor**, not authority. The real
  "has stage X run at version V" test is `stage_runs` (§2). `state` exists so the
  queue's cheap first filter (`state = 'mapped'`) doesn't scan `stage_runs` for
  every candidate.

#### 1.2 Doc schema `spiritolo/recipe-doc/v1`

An **internal superset** of `recipegf/cocktail/v1`. Three layers:

**(a) Envelope** — verbatim RecipeGF `cocktail/v1` fields. `schema` const stays
`recipegf/cocktail/v1` (Tract A keeps it constant); the Spiritolo doc-schema
name lives in the DB column `doc_schema`, *not* inside the doc, precisely so the
exported subset is byte-identical.

```jsonc
{
  "schema": "recipegf/cocktail/v1",
  "id": "com.spiritolo/negroni:v1",          // reverse-DNS recipe id
  "title": "Negroni",
  "ingredients": [ /* RecipeGF ingredient objects, see (b) */ ],
  "steps":       [ /* RecipeGF verb-frame steps */ ],
  "equipment":   ["mixing-glass", "barspoon"],
  "_x": { /* sidecar, see (c) — STRIPPED at export */ }
}
```

**(b) RecipeGF ingredient object** — the shape frozen by Tract A (v0.4.0). The
doc uses it directly; no Spiritolo-local ingredient shape:

```jsonc
{
  "name": "Campari",
  "quantity": { "amount": 1, "amount_max": null, "unit": "oz" },  // amount_max ≥ amount (validator rule)
  "ref": "spiritolo/campari",   // portable <authority>/<slug>; grammar owned by RecipeGF, vocabulary by us
  "modifiers": ["chilled"]      // optional, mirrors step.modifiers
}
```

ROLE and taxonomy *meaning* are **not** in the RecipeGF interface — they live in
`_x`. `ref` carries only the portable identifier grammar.

**(c) `_x` sidecar** — everything pipeline-internal, stripped at export:

```jsonc
"_x": {
  "site": "punch",
  "canonical_name": "Negroni",
  "cluster_key": "sha256:…",         // hash of (canonical_name, taxonomy-slug antichain)
  "variant_key": "sha256:…",         // adds amounts + brand call-outs
  "source": {
    "jsonld": { /* raw Schema.org Recipe, verbatim when present;              */
                /* LLM-synthesized when the page had none. Public UI renders  */
                /* these original words in our formatting.                    */ },
    "jsonld_origin": "verbatim" | "synthesized"
  },
  "ingredients_x": [                 // parallel to envelope ingredients[]
    { "position": 0,
      "taxonomy_slug": "campari",    // resolved node SLUG (stable), never PK
      "taxonomy_node_id": 412,       // convenience mirror; slug is authoritative
      "mapper_method": "alias",      // alias|lexical|llm|abstain
      "role": "modifier" }           // substance role for cluster rollup
  ]
}
```

**Export = `doc − doc._x`.** The pin-2 bundle is `{recipe: strip_x(doc),
verbs:[…spiritolo/ defs used…], meta:{slug, source, imported_at}}`, generated on
demand — never stored as a blob.

#### 1.3 Rebuildable projections (the `project(doc)` family)

Each is `TRUNCATE`-and-rebuild from `recipe_docs.doc`. None holds a fact absent
from the doc. Each has a pure builder function with an eval/unit test.

**`recipe_doc_ingredients`** — the flat search/cluster surface (replaces the old
`recipe_ingredients` table):

```sql
create table recipe_doc_ingredients (
  recipe_doc_id bigint not null references recipe_docs(id) on delete cascade,
  position      int    not null,
  name          text   not null,
  amount        numeric,
  amount_max    numeric,
  unit          text,
  taxonomy_slug text,          -- from _x.ingredients_x
  role          text,          -- from _x.ingredients_x
  primary key (recipe_doc_id, position)
);
create index rdi_slug_idx on recipe_doc_ingredients (taxonomy_slug) where taxonomy_slug is not null;
create index rdi_name_trgm on recipe_doc_ingredients using gin (name gin_trgm_ops);
```

**`recipe_clusters`** — the materialization of cluster identity. **PK is the
`cluster_key` (a hash of taxonomy SLUGS), not a serial** — this is the whole
point of hashing slugs: the key is stable across rebuilds and never depends on a
DB PK.

```sql
create table recipe_clusters (
  cluster_key    text primary key,              -- hash(canonical_name, slug antichain)
  canonical_name text not null,
  ingredient_set jsonb not null,                -- rolled-up antichain slugs
  recipe_count   int  not null default 0,
  source_count   int  not null default 0,       -- distinct sites
  dedup_version  text not null,
  rebuilt_at     timestamptz not null default now()
);
create index recipe_clusters_canonical_idx on recipe_clusters (canonical_name);
```

Rebuild = `insert … select` grouping `recipe_docs` by generated `cluster_key`.
Variants are a **view**, not a table (matches today's `recipe_variants`; only
materialize if aggregation proves hot):

```sql
create view recipe_variants as
  select cluster_key, variant_key,
         min(id) as representative_doc_id,
         count(*) as recipe_count,
         count(distinct site) as source_count
  from recipe_docs
  where cluster_key is not null and variant_key is not null
  group by cluster_key, variant_key;
```

**`recipes_public`** — public read surface, `security_invoker`, public fields
only (reuses today's pattern from `recipes_public_security_invoker` +
`dedup_clusters`):

```sql
create view recipes_public with (security_invoker = true) as
  select id, source_url, site, title, canonical_name,
         cluster_key, variant_key,
         doc #> '{_x,source,jsonld}' as jsonld   -- original words, our formatting
  from recipe_docs;
grant select on recipes_public to anon, authenticated;
```

#### 1.4 `pages` — discover/fetch state (Postgres, R2-keyed)

The scraper `pages` table (today SQLite, §`scraper/db.py`) moves into the one
Postgres. It holds **only** the lightweight per-URL row; the HTML **bytes** live
read-only in Cloudflare R2 keyed `sha256(url)`. `pages` + the R2 corpus are the
two preserved inputs the clean-slate rebuild starts from.

```sql
create table pages (
  id              bigserial primary key,
  url             text not null unique,
  site            text not null,
  r2_key          text,                    -- sha256(url); null until fetched
  content_type    text,                    -- classify output label
  denylist        boolean not null default false,
  denylist_reason text,
  fetch_status    text check (fetch_status in ('ok','blocked','failed')),
  fetch_meta      jsonb,                    -- {http_status, rendered, scraperapi_cost_cents, bytes}
  discovered_at   timestamptz not null default now(),
  fetched_at      timestamptz
);
create index pages_site_idx    on pages (site);
create index pages_content_idx on pages (content_type);
create index pages_denylist_idx on pages (denylist) where denylist;
```

The old per-`pages`-field snapshot columns (`pages_status_before`, etc.) and the
scraper's `attempts`/`fetch_error` bookkeeping are **gone** — that history now
lives in `stage_runs.payload` / `audit_log`.

#### 1.5 Taxonomy reference (kept as-is)

`taxonomy_nodes` / `taxonomy_edges` / `taxonomy_aliases` and `cocktail_aliases`
are **curated reference data** the docs point at *by slug*. Carried forward
unchanged from the current migrations (multi-parent DAG, `slug !~ '_'` kebab
CHECK, `node_kind` / `default_role` / `is_cluster_node` / `is_defining_garnish`,
the five SECURITY DEFINER curation RPCs). Docs reference `ref: "spiritolo/<slug>"`
and `_x.ingredients_x[].taxonomy_slug` — **slugs, so a node PK renumber never
touches a doc or a cluster key.**

#### 1.6 Proposal tables (kept, typed)

`taxonomy_proposals` (kebab `proposed_slug` CHECK, form-node review queue) and
`recipegf_proposals` (converter parked-Uncertain queue) are kept as **typed
tables with text+CHECK status** — they are human-review inboxes, not pipeline
state, so they do *not* fold into `stage_runs`. Their `decided_by` / `decided_at`
columns stay (a proposal decision is itself an audited manual action).

#### 1.7 Dropped (clean slate)

- `recipes` + `recipe_ingredients` — superseded by `recipe_docs` +
  `recipe_doc_ingredients`.
- `recipegf_recipes` / `recipegf_ingredients` / `recipegf_steps` — the export
  bundle is generated on demand from `strip_x(doc)`; no relational trio.
- All `*_source` / `*_version` / `*_at` / `status` columns on content — moved to
  `stage_runs` / `audit_log`.

---

### 2. The RUN LEDGER — `stage_runs`

One unified ledger for **all** stages (Zone-1 and Zone-2 merged). Generalizes the
current per-stage `*_runs` SQLite tables (`classify_url_runs`,
`validate_html_runs`, `classify_drink_runs`, `extract_runs`) into a single
polymorphic table. **Latest-only: exactly one row per (entity, stage).**

```sql
create table stage_runs (
  id          bigserial primary key,
  entity_type text   not null check (entity_type in ('page','recipe_doc')),
  entity_id   bigint not null,
  stage       text   not null,   -- discover|classify|fetch|extract|parse|map|role|cluster|export
  version     text   not null,   -- the stage's version constant at run time

  outcome     text not null check (outcome in
                ('resolved','abstain','pending','failed','proposes_new')),
  method      text not null check (method in ('deterministic','llm','manual')),
  confidence  real,
  model_id    text,              -- e.g. 'qwen3:14b', 'gpt-5-mini', null for deterministic
  cost_cents  numeric,           -- metered spend attributable to this entity's run
  error_code  text,
  batch_id    bigint references job_batches(id) on delete set null,
  job_id      bigint references jobs(id)        on delete set null,
  payload     jsonb,             -- stage-specific detail (raw response, snapshot, score breakdown)

  started_at  timestamptz not null default now(),
  finished_at timestamptz,

  unique (entity_type, entity_id, stage)   -- latest-only; re-run UPSERTs
);
create index stage_runs_queue_idx on stage_runs (stage, version, entity_type);
create index stage_runs_job_idx   on stage_runs (job_id) where job_id is not null;

alter table stage_runs enable row level security;  -- admin read only
```

**Write** = UPSERT on the unique key (mirrors every `record_*` UPSERT in
`scraper/db.py`):

```sql
insert into stage_runs (entity_type, entity_id, stage, version, outcome, method, …)
values ('recipe_doc', $id, 'parse', $ver, …)
on conflict (entity_type, entity_id, stage)
do update set version=excluded.version, outcome=excluded.outcome,
              method=excluded.method, /* … */ finished_at=excluded.finished_at;
```

**Work-queue predicate** (`qualifies AND NOT EXISTS a run at the current
version`) — the direct generalization of `get_unextracted` /
`get_pending_validate_html`:

```sql
-- parse queue at version $V: docs that have been extracted but not parsed@$V
select d.id, d.source_url, d.doc
from recipe_docs d
where d.state = 'extracted'                       -- cheap denorm prefilter
  and not exists (
    select 1 from stage_runs r
    where r.entity_type = 'recipe_doc'
      and r.entity_id   = d.id
      and r.stage       = 'parse'
      and r.version     = $V);
```

Because the unique constraint guarantees ≤1 row per (entity, stage), a row left
at an *older* version automatically re-queues — no history rows to filter.

**`--reset` semantics** (generalizes `clear_eval_rows`): drop the stage's rows,
optionally filtered by `--except-version` / `--site` / `--older-than`; deleting a
row puts the entity back on that stage's queue.

```sql
delete from stage_runs
where stage = $S
  and ($except is null or version <> $except)
  and ($site   is null or entity_id in (select id from pages where site=$site))  -- or recipe_docs.site
  and ($older  is null or finished_at < $older);
```

A stage whose queue *also* gates on a denormalized column (as classify gated on
`pages.content_type IS NULL`) resets that column in the **same transaction** —
exactly the `reset_classify_url` pattern (delete run row + null the cursor
atomically, so a crash can't strand an entity out of both queue and ledger).

`stage_runs` is **prunable derived state**: `TRUNCATE stage_runs` + re-run
reproduces it. It carries *no* who/when-for-manual-edits — that is `audit_log`.

---

### 3. The QUEUE — `jobs` + `job_batches`

Postgres-as-queue: no broker, no API server. The Railway worker claims via
`FOR UPDATE SKIP LOCKED`; the UI enqueues/approves via SECURITY DEFINER RPCs.

#### 3.1 `jobs`

```sql
create type job_state as enum
  ('queued','awaiting_approval','claimed','running','succeeded','failed','cancelled');

create table jobs (
  id                  bigserial primary key,
  stage               text not null,
  version             text not null,
  kind                text not null default 'run'
                      check (kind in ('run','reset','reconcile')),
  payload             jsonb not null default '{}',   -- {scope:{url|ids[]|site|limit|all:true}, providers:[…]}

  state               job_state not null default 'queued',

  -- confirm-before-cost: only METERED work (hosted LLM / ScraperAPI) sets these.
  requires_approval   boolean not null default false,
  approved            boolean not null default false,
  approved_by         uuid,
  approved_at         timestamptz,
  cost_estimate_cents numeric,          -- estimate over the scoped set, shown at confirm
  cost_actual_cents   numeric,          -- rolled up from stage_runs.cost_cents
  max_cost_cents      numeric,          -- HARD cap the worker enforces mid-run

  progress            jsonb not null default '{}',   -- {done,total,proposed,failed}
  error_code          text,
  batch_id            bigint references job_batches(id) on delete set null,

  worker_id           text,
  last_heartbeat      timestamptz,

  created_by          uuid,
  created_at          timestamptz not null default now(),
  started_at          timestamptz,
  finished_at         timestamptz
);

-- Partial index: the claim query only ever scans genuinely-claimable rows.
create index jobs_claimable_idx on jobs (created_at)
  where state = 'queued' and (not requires_approval or approved);

alter table jobs enable row level security;   -- admin read (ops console); write via RPC only
```

**Claim** (atomic, contention-safe):

```sql
update jobs
set state='claimed', worker_id=$w, last_heartbeat=now(), started_at=now()
where id = (
  select id from jobs
  where state='queued'
    and (not requires_approval or approved)
    and (max_cost_cents is null or coalesce(cost_estimate_cents,0) <= max_cost_cents)
  order by created_at
  for update skip locked
  limit 1)
returning *;
```

**Heartbeat / reaper.** The worker `update jobs set last_heartbeat=now() where
id=$j` on a timer while running. A reaper (a periodic job, or the worker on boot)
requeues stalled work:

```sql
update jobs
set state='queued', worker_id=null
where state in ('claimed','running')
  and last_heartbeat < now() - interval '2 minutes';
```

Safe to requeue because every stage write is an **idempotent UPSERT** into
`stage_runs` — re-processing an entity overwrites its latest row, never
duplicates. `cost_actual_cents` is derived from `stage_runs.cost_cents` so a
partial-then-requeued job never double-counts spend.

**Enqueue / approve RPCs** (reuse the `taxonomy_curation_rpcs` SECURITY DEFINER +
`is_admin()` pattern):

```sql
create function public.enqueue_job(
  p_stage text, p_version text, p_kind text, p_payload jsonb,
  p_requires_approval boolean, p_cost_estimate_cents numeric, p_max_cost_cents numeric
) returns bigint language plpgsql security definer set search_path='' as $$
declare v_id bigint;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode='42501';
  end if;
  insert into public.jobs (stage,version,kind,payload,requires_approval,
                           state,cost_estimate_cents,max_cost_cents,created_by)
  values (p_stage,p_version,p_kind,p_payload,p_requires_approval,
          case when p_requires_approval then 'awaiting_approval' else 'queued' end,
          p_cost_estimate_cents,p_max_cost_cents,auth.uid())
  returning id into v_id;
  return v_id;
end $$;

create function public.approve_job(p_id bigint) returns void
language plpgsql security definer set search_path='' as $$
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode='42501';
  end if;
  update public.jobs
  set approved=true, approved_by=auth.uid(), approved_at=now(),
      state='queued'
  where id=p_id and state='awaiting_approval';
end $$;
```

Live status: **Supabase Realtime** on `jobs`; aggregate counts via react-query
polling of `stage_runs`/queue counts.

#### 3.2 `job_batches`

Durable OpenAI async-Batch state — **replaces the `data/batches/*.json`
sidecars**. The Batch API survives only as an optional accelerator for large
hosted backfills, not a core path.

```sql
create table job_batches (
  id                bigserial primary key,
  provider          text not null default 'openai',
  provider_batch_id text unique,               -- OpenAI batch id
  stage             text not null,
  version           text not null,
  state             text not null check (state in
                      ('submitted','in_progress','completed','failed','ingested')),
  request_count     int,
  input_file_id     text,
  output_file_id    text,
  custom_id_map     jsonb,                      -- {custom_id -> entity_id} for ingest
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index job_batches_open_idx on job_batches (state)
  where state in ('submitted','in_progress');
```

Worker **reconciles open batches on boot**: `select … where state in
('submitted','in_progress')`, polls OpenAI, ingests completed ones (writing
`stage_runs` rows keyed via `custom_id_map`), flips `state='ingested'`.

---

### 4. The AUDIT LOG — `audit_log`

#### 4.1 Decision: small custom generic trigger, **not** `supa_audit`

**Recommendation: a ~40-line custom trigger writing one generic `audit_log`
table.** Reject the `supa_audit` extension.

Why not `supa_audit`: its fixed `audit.record_version` schema stores
`(record, old_record, op, table_oid, record_id, ts)` but has **no notion of our
actor model** — the human-vs-worker-vs-system distinction and the
manual-UI-edit-vs-automated-write distinction are the entire point of *our* audit
log, and supa_audit can't express them without a bolted-on side channel. Adopting
it means an extension dependency *plus* a parallel actor table anyway. The custom
trigger captures exactly `actor + source + diff + time` and nothing more — the
smallest thing that answers "did *I* change this, or did the pipeline?".

#### 4.2 Shape

```sql
create schema if not exists audit;

create table audit.log (
  id           bigserial primary key,
  ts           timestamptz not null default now(),
  table_name   text  not null,
  pk           text  not null,          -- to_jsonb(row)->>'id'
  op           char(1) not null check (op in ('I','U','D')),

  actor_kind   text  not null check (actor_kind in ('human','worker','system')),
  actor_id     text,                    -- auth.uid()::text | job id | null(system)
  source       text  not null,          -- 'manual-ui-edit' | 'job:<stage>' | 'migration' | 'reaper'

  before       jsonb,                   -- null on INSERT
  after        jsonb,                   -- null on DELETE
  changed_keys text[]                   -- UPDATE only: keys whose value changed
);
create index audit_log_table_pk_idx on audit.log (table_name, pk, ts desc);
create index audit_log_actor_idx    on audit.log (actor_kind, ts desc);

alter table audit.log enable row level security;   -- admin read only; append via trigger
```

We store `before` + `after` + `changed_keys` rather than a full jsonb `diff`
blob: `changed_keys` answers "what did this edit touch" in one array without a
per-write diff computation, and the full before→after diff is derivable on read
for the rare deep inspection. (YAGNI: no stored full-diff jsonb.)

#### 4.3 Actor derivation — how manual vs automated is distinguished

The writer sets Postgres GUCs with `SET LOCAL` (transaction-scoped); the trigger
reads them plus `auth.uid()`:

```sql
create or replace function audit.log_change() returns trigger
language plpgsql security definer set search_path='' as $$
declare
  v_uid   text := (select auth.uid())::text;
  v_job   text := nullif(current_setting('app.job_id', true), '');
  v_src   text := coalesce(nullif(current_setting('app.source', true), ''), 'unknown');
  v_kind  text;
  v_actor text;
  v_before jsonb := case when tg_op <> 'INSERT' then to_jsonb(old) end;
  v_after  jsonb := case when tg_op <> 'DELETE' then to_jsonb(new) end;
begin
  if v_uid is not null then                 -- ran under a user JWT → admin RPC
    v_kind := 'human'; v_actor := v_uid;
  elsif v_job is not null then              -- worker set app.job_id
    v_kind := 'worker'; v_actor := v_job;
  else                                      -- migration / reaper / seed
    v_kind := 'system'; v_actor := null;
  end if;

  insert into audit.log (table_name, pk, op, actor_kind, actor_id, source,
                         before, after, changed_keys)
  values (tg_table_name,
          coalesce(v_after->>'id', v_before->>'id'),
          left(tg_op,1), v_kind, v_actor, v_src,
          v_before, v_after,
          case when tg_op='UPDATE' then (
            select array_agg(key) from jsonb_each(v_after)
            where v_after->key is distinct from v_before->key) end);
  return null;                              -- AFTER trigger
end $$;
```

**The distinction falls out cleanly:**

- **Manual UI edit** → routed through an admin RPC that runs under the user's
  JWT, so `auth.uid()` is non-null → `actor_kind='human'`, `actor_id=<uid>`. The
  RPC also does `perform set_config('app.source','manual-ui-edit',true)`.
- **Automated pipeline write** → the worker connects with the service role
  (`auth.uid()` null) and does `perform set_config('app.job_id', $job::text,
  true); set_config('app.source','job:parse',true)` at the top of each job txn →
  `actor_kind='worker'`, `actor_id=<job_id>`. This ties the mutation back to the
  `jobs` row and (via that) the `stage_runs` row that caused it.
- **System** (migrations, reaper, seed) → no JWT, no job GUC → `actor_kind='system'`.

Attach the trigger only to content tables with a scalar `id` PK — `recipe_docs`,
`taxonomy_nodes`, `taxonomy_proposals`, `recipegf_proposals`:

```sql
create trigger audit_recipe_docs
  after insert or update or delete on recipe_docs
  for each row execute function audit.log_change();
-- …one per audited table.
```

Composite-PK reference tables (`taxonomy_edges`, `taxonomy_aliases`,
`cocktail_aliases`) are **not** row-audited — their curation RPCs already
replace-all edge/alias sets under an audited `taxonomy_nodes` action, so the node
audit row is the meaningful record. (Open question §7 if per-edge granularity is
later wanted.)

#### 4.4 The post-batch review/edit loop

After a batch finishes, the /ops review UI edits a doc → an admin RPC (e.g.
`update_recipe_doc(id, patch)`) that (1) sets `app.source='manual-ui-edit'`,
(2) writes the content, and (3) the trigger appends the `audit_log` row with
`actor_kind='human'`. No separate audit write in the RPC — the trigger is the
single audit writer, so *every* path (RPC, worker, hand-SQL) is captured
uniformly.

---

### 5. RLS / access summary

- **Content + process tables**: RLS enabled, deny-all; the only write paths are
  the service-role worker (bypasses RLS) and SECURITY DEFINER RPCs.
- **Public read**: `recipes_public` (`security_invoker`) → anon/authenticated.
  Taxonomy stays admin-gated per current policy tiers.
- **/ops read** (jobs, stage_runs, audit.log, proposals): `authenticated` +
  `is_admin()` policies, reusing `RequireAdmin`/`useIsAdmin`/`is_admin()`.
- **Realtime** publication on `jobs` for live status.

---

### 6. TDD framing (per plan requirement — RED first)

- **Migrations**: each table/trigger lands with a failing pgTAP-or-integration
  test against `TEST_DB_URL` first (e.g. "claim skips locked rows", "reaper
  requeues stale job", "audit row records actor_kind=worker when app.job_id set",
  "stage_runs UPSERT is latest-only", "recipe_docs generated col tracks doc
  edit").
- **Projections**: `project(doc)` builders are pure Python with an eval-set test
  (mirrors the existing `eval_set.py` discipline) — RED case per new shape.
- **Doc schema**: a parity test that `strip_x(doc)` validates against
  `recipegf/cocktail/v1` (gated on Tract A's frozen ingredient shape).

---

### 7. Open questions

Listed in the structured `open_questions` field.


### YAGNI cuts
- No separate serving vs pipeline database — one Supabase Postgres for everything (architecture explicitly rejects the split).
- No message broker / queue service / API server — Postgres-as-queue with FOR UPDATE SKIP LOCKED is the whole mechanism.
- No supa_audit extension — a small custom trigger captures exactly actor+source+diff+time.
- No per-stage bespoke *_runs tables — one unified polymorphic stage_runs.
- No history rows in stage_runs — latest-only (UNIQUE per entity,stage); durable history is audit_log's job.
- No stored export bundle blob and no recipegf_recipes/_ingredients/_steps relational trio — bundles are generated on demand from strip_x(doc).
- No legacy recipes / recipe_ingredients pair — clean slate into recipe_docs / recipe_doc_ingredients.
- No stored full-jsonb diff on audit rows — before + after + changed_keys only.
- No recipe_variants materialized table — a view until proven hot.
- No cron / automated scheduling — every job is UI-triggered and scoped.
- No job priority lanes, retry-backoff scheduler, or dead-letter queue — a single created_at FIFO claim + a stale-heartbeat reaper.
- No confirm-before-cost on free work — approval/max_cost_cents apply only to metered stages (hosted LLM + ScraperAPI).
- No storing which providers/order per stage in schema — the provider chain is external config the owner rewires, not a DB-modeled pipeline.
- No per-edge audit of taxonomy_edges/aliases — node-level audit is the meaningful unit.
- No soft-delete/tombstone columns on content — deletes are audited via the DELETE trigger row.

### Key decisions
- How to key the unified run ledger across merged Zone-1/Zone-2 stages → One polymorphic stage_runs table with (entity_type,entity_id) + UNIQUE(entity_type,entity_id,stage) for latest-only, rather than per-stage tables or url-keyed. Generalizes the existing *_runs UPSERT pattern; work queue is the same NOT EXISTS predicate.
- Where the RecipeGF doc-schema name lives → In the DB column recipe_docs.doc_schema, NOT inside the doc. The doc's schema const stays recipegf/cocktail/v1 so strip_x(doc) is byte-identical to the exported pin-2 bundle.
- Cluster identity key type → recipe_clusters PK is the cluster_key (hash of taxonomy SLUGS), not a bigserial. Slugs are stable across PK renumbering, so cluster keys never depend on DB PKs — the architecture's load-bearing rule.
- supa_audit extension vs custom trigger → Custom ~40-line generic trigger into one audit.log table. supa_audit's fixed schema can't express our actor (human/worker/system) or manual-vs-automated distinction, which is the entire purpose of the log; adopting it means an extra dependency plus a bolted-on actor side channel anyway.
- How manual-UI-edit is distinguished from automated writes → auth.uid() (set by the user JWT under admin RPCs) => human; worker's SET LOCAL app.job_id => worker; neither => system. Single trigger is the only audit writer, so RPC, worker, and hand-SQL paths are all captured uniformly.
- before/after/diff storage → Store before + after jsonb + changed_keys text[] (UPDATE only). changed_keys answers 'what did this edit touch' cheaply; full diff is derivable on read. No stored full-diff blob.
- Export bundle storage → Generate the pin-2 bundle on demand from strip_x(doc); drop the recipegf_recipes/_ingredients/_steps relational trio. The doc is the single source of truth.
- Variant materialization → recipe_variants stays a VIEW (as today); materialize only if aggregation proves hot. recipe_clusters is materialized because cluster_key indexes joins.
- pages relocation → pages moves from scraper SQLite into the one Supabase Postgres, holding only the lightweight row (url, site, r2_key=sha256(url), content_type, denylist, fetch_meta). HTML bytes stay read-only in R2. pages + corpus are the two preserved clean-slate inputs.

### Open
- stage_runs entity polymorphism: is (entity_type,entity_id) with no FK the right call, or should there be two nullable FK columns (page_id, recipe_doc_id) for referential integrity? Polymorphic loses FK enforcement; the two-FK shape adds a CHECK that exactly one is set.
- audit.log retention/compaction: append-only grows unbounded. Do we need a retention policy or partition-by-month from day one, or defer until volume warrants (YAGNI leans defer)?
- Should the audit trigger cover composite-PK reference tables (taxonomy_edges, taxonomy_aliases, cocktail_aliases) for per-edge granularity, or is the parent taxonomy_nodes audit row sufficient? Current spec says node-level only.
- cluster_key hash algorithm + input canonicalization must be versioned (NORMALIZER_VERSION/DEDUP_VERSION) — where is the canonical hashing spec pinned so a hash-function change is a deliberate, re-runnable bump rather than silent drift?
- How is cost_estimate_cents computed per stage/provider at enqueue time (needs a per-provider unit-cost table or config), and does the worker's max_cost_cents enforcement abort mid-batch or mid-item?
- Does recipe_docs.state (denormalized cursor) risk drifting from stage_runs authority? Options: a rebuild job that recomputes state from stage_runs, or drop state entirely and always gate on stage_runs (costs an extra index scan per queue query).
- site is a generated column reading doc #>> '{_x,site}'; but pages already knows site authoritatively. Should site be copied into _x at extract (current spec) or should recipe_docs FK to pages and read site from there?



## 10. Foundation — UI System & Review/Edit

### UI SYSTEM + REVIEW/EDIT — foundation

Scope: the `/ops` admin console for the v2.1 rebuild — a Vercel SPA that reads the
one Supabase Postgres directly (PostgREST select + `rpc()` + Realtime), with **no
API server**. It composes a **shared kit** (primitives + hooks) so a QoL fix in one
place lands everywhere, and it delivers the **review/edit-after-batch** loop that
routes every human correction through a SECURITY-DEFINER RPC that mutates content
**and** appends an `audit_log` row (`actor = auth.uid()`).

The load-bearing constraint: **reuse the taxonomy-curation stack exactly**, don't
invent a second one. That stack already gives us: `RequireAdmin`/`useIsAdmin`
(react-query over `profiles.is_admin`), the `rpcs.ts` `unwrap`/`RpcError` pattern
over `supabase.rpc`, `EditableField` (text/dropdown/toggle inline edit with
optimistic apply + rollback), `AliasChipEditor`, `Toast` (info/error/progress),
`ModalShell` (backdrop + Esc), `Pagination` (URL-driven), a react-hook-form + zod
modal pattern (`CreateChildModal`/`DeleteNodeModal`), and a fully-tokenized form kit
(`--tx-form-*`, `.tx-btn/.tx-input/.tx-select/.tx-toggle/.tx-field`). react-query is
already provider-wrapped app-wide (`main.tsx`).

---

#### 0. TDD posture (applies to every item below)

RED first, then GREEN. Layers and harnesses:

- **Hooks/components** — Vitest + `@testing-library/react` with a mocked `supabase`
  client, exactly as `RecipeList.test.tsx` / `useIsAdmin.test.tsx` already do
  (wrap in `QueryClientProvider`). Each new hook/component ships its `*.test.tsx`
  first.
- **RPC + schema** — migration + integration test against `TEST_DB_URL` (pattern
  from `ingredients/tests/test_db.py`): a migration adds the function/table, a
  pytest asserts behavior (admin-gated, writes content, appends audit row). RED =
  test referencing the not-yet-created function.
- **No net-new e2e harness.**

---

#### 1. Shared component kit (`web/src/ui/`)

New directory `web/src/ui/` is the single home for cross-view primitives. **First
move is CSS, not TSX:** extract the form-kit *tokens* so the existing `.tx-*`
classes resolve outside `.taxonomy-page`.

##### 1.1 Design tokens & CSS approach

The taxonomy page is a deliberately ornate walnut/gold deco canvas. `/ops` is the
opposite by intent: **plain, high-legibility, directly mapped to the data** —
system-ui, white cards, thin borders, one accent, semantic status colors. We do
**not** re-skin taxonomy and we do **not** start a new design system. Two token
tiers:

`web/src/ui/tokens.css` (imported once at app root):

```css
/* Form-kit tokens — LIFTED verbatim from the .taxonomy-page block to :root so
   .tx-btn/.tx-input/.tx-select/.tx-toggle/EditableField/ModalShell render
   identically inside and outside the taxonomy canvas. Taxonomy keeps its own
   deco tokens (walnut gradient, Cinzel, gold) scoped as-is. */
:root {
  --tx-form-h: 36px; --tx-form-radius: 3px;
  --tx-form-border: #c4c4c4; --tx-form-border-focus: #6b7cff;
  --tx-form-bg: #fff; --tx-form-bg-hover: #fafafa;
  --tx-focus-ring: 0 0 0 2px rgba(107,124,255,0.28);
  --tx-danger: #b23b2e; --tx-brown-ink: #222; /* … */
}
/* Ops workbench surface + semantic status palette */
.ops {
  --ops-bg: #f6f7f9; --ops-surface: #fff; --ops-border: #e3e5e9;
  --ops-ink: #1c1e21; --ops-muted: #6a6f76; --ops-accent: #4959e0;
  --st-resolved:#2e7d54; --st-abstain:#b8860b; --st-pending:#6a6f76;
  --st-failed:#b23b2e; --st-proposes-new:#7a4fd0;      /* stage_run outcomes */
  --job-queued:#6a6f76; --job-running:#4959e0; --job-done:#2e7d54; --job-error:#b23b2e;
  font-family: system-ui, -apple-system, sans-serif; color: var(--ops-ink);
}
```

RED/GREEN: a Vitest that renders `<EditableField>` **outside** `.taxonomy-page` and
asserts the resolved border token is non-empty (guards the extraction). This is the
single change that unlocks reuse — without it `EditableField`'s `var(--tx-form-*)`
resolve to nothing off the taxonomy page.

##### 1.2 Primitives

| Primitive | Source | Composition notes |
|---|---|---|
| `EditableField` | **reuse** `taxonomy/EditableField` (move to `ui/`, import path updated in taxonomy) | text/dropdown/toggle; optimistic + rollback already built. The atom of all field-level edits. |
| `Toast` | **reuse** `taxonomy/Toast` | info/error/progress; `persist` for long jobs. |
| `Pagination` | **reuse** `components/Pagination` | URL `?page=`; already generic. |
| `Modal` | **reuse** `ModalShell` (lift out of `CreateChildModal.tsx` into `ui/Modal.tsx`) | backdrop-click + Esc. `CostConfirmModal` & `DeleteNodeModal` compose it. |
| `StatusPill` | new (~30 lines) | `<StatusPill kind="resolved"|"abstain"|…|jobstate>`; maps to the `--st-*`/`--job-*` tokens. Styling mirrors existing `.site-header__admin-chip` chip. |
| `CostBadge` | new (~25 lines) | renders `cents` → `$0.42`; `metered` variant adds a coin glyph + amber tint; shows `est`/`actual`. Used in jobs table + confirm modal. |
| `JsonView` | new (~60 lines, **no external lib**) | collapsible pretty-print of `doc`/`jsonld`/bundle. Read-only. Recursion + a monospace `<pre>` fallback. |
| `FilterBar` | new; **reuses** `taxonomy/FilterChips` | emits a single `{filters: PostgrestFilter[], scope: ScopeDescriptor}` — the SAME object feeds `usePagedQuery` (what you see) and `enqueue_job` (what you act on). site `<select>` + free-text + outcome/confidence/state chips. |
| `DataTable<T>` | new (~120 lines) | `columns: {key,header,render?,width?}[]`, `rows`, `selectable?`, `onRowClick`, `selectedIds`, `onSelectionChange`. Sticky header; wrapped in `overflow-x:auto`. Cells render `StatusPill`/`CostBadge` via `render`. Selection returns ids for scoped triggers. Composes over `usePagedQuery`. |
| `SplitView` / `DetailPane` | new (~50 lines) | master list left, detail right; selected id in the URL (`?sel=`), reusing the `useTaxonomyUrlState` idea. Every DB browser is `<SplitView list={<DataTable/>} detail={<DetailPane/>}/>`. |

Everything above is composed by *every* `/ops` view; nothing view-specific lives in
`ui/`. No `ag-grid`, no `react-json-view`, no `react-admin`.

##### 1.3 Shared hooks (`web/src/ui/hooks/`)

```ts
// usePagedQuery — the DRY replacement for the hand-rolled useEffect fetch in
// RecipeList/RecipeDetail. react-query (placeholderData: keepPreviousData) gives
// the no-flash "pending overlay" behavior for free.
function usePagedQuery<T>(opts: {
  table: string; select: string;
  filters?: PostgrestFilter[]; order?: {col: string; asc?: boolean};
  page: number; pageSize: number; realtime?: boolean;
}): { rows: T[]; total: number; status: 'loading'|'error'|'loaded'; pending: boolean };

// useRpc — react-query useMutation around supabase.rpc, wrapping the EXACT
// unwrap()/RpcError logic from taxonomy/rpcs.ts; on success invalidates keys +
// (optional) fires a Toast. Every mutating action (enqueue/approve/edit) goes here.
function useRpc<A, R>(fn: string, opts?: { invalidate?: QueryKey[] }): UseMutationResult<R, RpcError, A>;

// useRealtimeJobs — Supabase Realtime postgres_changes on `jobs` (+ progress),
// merged into the react-query cache so dashboard/jobs views update live.
// Falls back to react-query polling (refetchInterval) for aggregate counts.
function useRealtimeJobs(filter?: { stage?: string; state?: JobState }): { jobs: Job[]; connected: boolean };

// useAdminGate — thin alias of the existing useIsAdmin; /ops routes still nest
// under the existing <RequireAdmin> guard. No new auth surface.
const useAdminGate = useIsAdmin;
```

RED/GREEN per hook with a mocked `supabase`: `usePagedQuery` asserts
`.range(from,to)` + `count:'exact'` + prev-rows retained while `pending`; `useRpc`
asserts `unwrap` success and `RpcError` on `{error}`; `useRealtimeJobs` asserts a
mocked channel payload lands in cache and the poll fallback fires when the channel
is absent.

---

#### 2. `/ops` views

Route tree (all under the existing guards — `RequireAuth` → `RequireAdmin`):

```
/ops                     Landing().  <OpsLayout> shell: left nav + <Outlet/>
  /ops                   Dashboard   per-stage StageCards, live
  /ops/jobs              Jobs ledger (live) → job detail (progress/cost/batch/error)
  /ops/pages             Corpus browser (pages + signed-R2 HTML iframe)
  /ops/docs              recipe_docs browser (pipeline drilldown + JsonView)
  /ops/runs              stage_runs ledger
  /ops/audit             audit_log browser
  /ops/clusters          recipe_clusters browser
  /ops/exports           bundle preview (generate-on-demand) + download
  /ops/review            review/edit-after-batch (see §3)
```

Add to `App.tsx` (lazy, like Taxonomy) a single nested `<Route path="/ops"
element={<RequireAdmin/>}>` wrapping `<OpsLayout/>`.

##### 2.1 Status dashboard (`/ops`)

A grid of `StageCard`s, one per pipeline stage (discover → classify → fetch →
extract → parse → map → role/cluster → export). Each card shows, live:

- **Queue depth** — count of `content qualifies AND NOT EXISTS(stage_run @ current
  version)`. Sourced from a `stage_queue_counts` **view** (one row per stage) so the
  UI never re-derives queue logic; polled via react-query.
- **In-flight** — `useRealtimeJobs({stage})` count of `running`/`claimed` jobs.
- **Last-run outcome mix** — small `StatusPill` row (resolved/abstain/pending/
  failed/proposes_new) from `stage_runs` aggregated by outcome.
- **A `<TriggerBar scope={{kind:'whole_queue', stage}}/>`** — the "run the queue"
  affordance (see §2.9).

No charts library — counts + pills only. RED/GREEN: mock the counts view + a
realtime payload, assert a card renders depth and a pill breakdown.

##### 2.2 Jobs ledger (`/ops/jobs`)

`<SplitView>`: left `DataTable` over `jobs` (stage, kind, state `StatusPill`,
`CostBadge` est/actual, created_by, heartbeat age), live via `useRealtimeJobs`;
right `DetailPane` shows `progress` jsonb, `error_code`, `batch_id` (link to
`job_batches`), `worker_id`, and — for completed batch jobs — a **"Review results"**
button that deep-links to `/ops/review?job=<id>`.

##### 2.3 Corpus / pages browser (`/ops/pages`)

`DataTable` over `pages` (url, site, denylist, fetch meta). Detail pane renders the
stored HTML from R2 in a **sandboxed `<iframe>`** whose `src` is a **short-lived
signed URL**. The SPA has no server, so signing is an **open item** — foundation
assumes a tiny Supabase **Edge Function `sign-corpus-url(r2_key)`** (the one place we
add server code) called via `supabase.functions.invoke`. The iframe is
`sandbox="allow-same-origin"` only (no scripts) — we render captured HTML, never
execute it.

##### 2.4 recipe_docs browser (`/ops/docs`)

The centerpiece read surface. `<SplitView>`: left `DataTable` over `recipe_docs`
(name from `doc`, `site` generated col, `state` cursor as a pipeline breadcrumb
`scrape ▸ classify ▸ … ▸ export` with the current cursor bolded); right `DetailPane`
with (a) `JsonView` of `doc` (the `_x` sidecar shown dimmed, flagged "stripped at
export"), (b) the per-entity `stage_runs` timeline (method/confidence/model/cost),
(c) an **Edit** entry that opens the field-level editor (§3). Filterable to a single
`batch_id`, which is exactly the review entry point.

##### 2.5 stage_runs ledger (`/ops/runs`)

`DataTable` over `stage_runs` filtered by stage/outcome/version/method — the raw run
history. Read-only. Confirms the queue invariant visually (find rows below current
version → the `--reset` candidates).

##### 2.6 audit_log browser (`/ops/audit`)

`DataTable` over `audit_log`: actor (human `auth.uid` vs worker `job_id` vs system),
source (`stage/job` vs `manual-ui-edit`), table, pk, timestamp; detail pane shows the
before/after diff via `JsonView`. This is where "I edited this" is legible.

##### 2.7 clusters browser (`/ops/clusters`)

`DataTable` over `recipe_clusters` (canonical_name, variant/source counts); detail
lists member recipes (reuses the `recipes(...)` join style already in `NodeCard`).

##### 2.8 exports / bundle preview (`/ops/exports`)

Per cluster, `JsonView` of the **generated-on-demand** pin-2 bundle (`{recipe,
verbs, meta}`) from the relational rows — never a stored blob — plus a Download
button (`Blob` → `a[download]`, no server). A parity note in the UI: the bundle ==
`doc` minus the `_x` sidecar.

##### 2.9 Trigger controls (shared `<TriggerBar>`)

One component, four scopes, present on the dashboard and every browser:

```ts
type ScopeDescriptor =
  | { kind: 'item'; stage: string; entity_id: string }
  | { kind: 'multiselect'; stage: string; entity_ids: string[] } // from DataTable selection
  | { kind: 'filter'; stage: string; site?: string; limit?: number; where?: PostgrestFilter[] } // from FilterBar
  | { kind: 'whole_queue'; stage: string };
```

Flow: pick scope → if the stage is **metered** (hosted LLM or ScraperAPI), open
`CostConfirmModal` (composes `Modal`) showing item count + `CostBadge` estimate + a
`max_cost_cents` input; on confirm call `enqueue_job` then `approve_job`. For
**free** stages (deterministic/local), enqueue directly — no modal. "Metered" is
read from a small `stage_config` table/const the UI consults, not hardcoded in the
component (the provider chain is owner-rewired config). A persistent `progress`
`Toast` tracks the enqueued job via `useRealtimeJobs`.

---

#### 3. Review / edit-after-batch flow

The whole point: after a batch finishes, make it trivial to find what the machine
punted on and fix it, with a durable human-attributed audit trail.

**Entry & filter.** `/ops/review?job=<id>` (or `?batch=<id>`) opens a
`recipe_docs`/`stage_runs` `DataTable` scoped to that batch, with `FilterBar`
preset to `outcome = 'abstain' OR confidence < :threshold`. This is just the
`/ops/docs` browser with a canned filter — **not a new screen** (DRY).

**Inspect & edit.** Row → `DetailPane` shows raw input (e.g. the
`recipeIngredient` string / `source.jsonld`), the machine's output, and the current
`doc` field. The operator corrects it with the **reused `EditableField`** (or a
zod-validated modal for structured edits, mirroring `CreateChildModal`).

**Commit — the RPC contract (mirrors `update_taxonomy_node` exactly).** A typed
SECURITY-DEFINER RPC per editable content table (not a generic framework):

```sql
create or replace function edit_recipe_doc(
  p_doc_id bigint, p_patch jsonb, p_reason text default null
) returns void language plpgsql security definer as $$
declare v_actor uuid := auth.uid(); v_before jsonb;
begin
  if not exists (select 1 from profiles where id = v_actor and is_admin) then
    raise exception 'not authorized';                 -- same gate as taxonomy RPCs
  end if;
  select doc into v_before from recipe_docs where id = p_doc_id for update;
  update recipe_docs set doc = doc || p_patch, updated_at = now() where id = p_doc_id;
  insert into audit_log(actor, source, "table", pk, before, after, reason, at)
  values (v_actor::text, 'manual-ui-edit', 'recipe_docs', p_doc_id::text,
          v_before, v_before || p_patch, p_reason, now());
  -- optional: upsert a stage_run (method='manual', outcome='resolved') so the
  -- edited field is treated as settled and not re-queued.
end $$;
```

Client side, `useRpc('edit_recipe_doc', {invalidate:[docKey]})` gives the identical
optimistic-apply → rollback-on-throw → `Toast` behavior taxonomy already ships
(`handleEditField` in `Taxonomy.tsx`). Taxonomy edits keep using
`update_taxonomy_node` unchanged; each content table gets its own typed edit RPC as
it becomes editable. **Actor attribution:** the RPC writes `audit_log.actor =
auth.uid()`, `source = 'manual-ui-edit'` — cleanly distinguishing human edits from
worker (`actor = job_id`, source = `stage/job`) and system writes.

**Queue RPCs** (same SECURITY-DEFINER + admin-gate shape, tested against
`TEST_DB_URL`):

```
enqueue_job(p_stage text, p_version text, p_kind text, p_scope jsonb,
            p_max_cost_cents int) returns bigint   -- created_by := auth.uid();
                                                    -- requires_approval from stage_config
approve_job(p_job_id bigint) returns void          -- sets approved/approved_by;
                                                    -- rejects if already claimed
```

RED/GREEN for the RPCs: pytest against `TEST_DB_URL` — (1) non-admin call raises;
(2) `edit_recipe_doc` mutates `doc` **and** inserts exactly one `audit_log` row with
`actor = <uid>`, `source='manual-ui-edit'`, correct before/after; (3) `enqueue_job`
stamps `created_by`; (4) `approve_job` flips approval and refuses a claimed job.
Component RED/GREEN: `CostConfirmModal` Confirm disabled until acknowledged (mirror
`DeleteNodeModal.test`); review row edit calls the mocked RPC and optimistically
updates.

---

#### 4. Build order (each RED→GREEN)

1. Extract form-kit tokens to `:root` (§1.1) + guard test — unlocks reuse.
2. `useRpc`, `usePagedQuery`, `useAdminGate` (hooks) + tests.
3. Move `EditableField`/`ModalShell`/`Toast` to `ui/`; `StatusPill`/`CostBadge`/
   `JsonView`/`DataTable`/`SplitView`/`FilterBar` + tests.
4. RPCs: `enqueue_job`, `approve_job`, `edit_recipe_doc` (migration + `TEST_DB_URL`
   tests). `stage_queue_counts` view.
5. `useRealtimeJobs` + Realtime publication on `jobs`.
6. `OpsLayout` + routes; then views in order: docs → jobs → dashboard → runs → audit
   → pages → clusters → exports → review. (`/ops/docs` first because review reuses
   it.)
7. `sign-corpus-url` Edge Function (only when the pages iframe is built).


### YAGNI cuts
- No generic admin/CRUD framework (react-admin et al). One typed SECURITY-DEFINER edit RPC per content table, mirroring update_taxonomy_node.
- No new design system or component library — extend the existing form-kit tokens and reuse EditableField/ModalShell/Toast/Pagination.
- No external table/grid/json-viewer libraries (ag-grid, react-json-view). DataTable is a table + usePagedQuery; JsonView is ~60 hand-rolled lines.
- No charts/graphs library on the dashboard — queue depth counts + StatusPill outcome breakdowns only.
- No WYSIWYG or free-form doc editing — field-level EditableField + shallow jsonb patch through the RPC; nested edits deferred until a real case demands jsonb_set.
- No role hierarchy or per-view permissions — the single is_admin gate via the existing RequireAdmin; useAdminGate is just an alias of useIsAdmin.
- No saved views, dashboard customization, or user preferences.
- No custom realtime/websocket infrastructure — Supabase Realtime + react-query polling fallback only.
- No scheduling/cron UI — every job is manually triggered per the trigger model.
- No client-side cost simulation engine beyond a simple item_count × per_item estimate.
- No bulk inline-edit grid — review edits are one row at a time through the DetailPane.
- Do not re-theme or refactor the taxonomy page beyond lifting the shared form-kit tokens out of its scope.
- No mobile/responsive layout work for /ops beyond overflow-x:auto scroll containers — it is a desktop admin tool.
- No script execution in the corpus iframe — sandboxed, same-origin render of captured HTML only, never executed.

### Key decisions
- Reuse the taxonomy-curation stack rather than build a second UI system → Move EditableField/ModalShell/Toast/Pagination into web/src/ui/ and compose them everywhere; edits use the existing unwrap/RpcError + optimistic-rollback + Toast pattern verbatim. No new framework.
- Make the form kit reusable off the taxonomy page → Lift the --tx-form-* tokens from the .taxonomy-page scope to :root so .tx-btn/.tx-input/EditableField/ModalShell render identically inside /ops; keep deco-only tokens (walnut, gold, Cinzel) scoped. This single CSS change is what unlocks reuse.
- Two visual tiers, not one theme → Taxonomy stays ornate deco; /ops is a deliberately plain system-ui workbench (white cards, thin borders, one accent, semantic status palette) mapped directly to the data. Same primitives, different surface tokens.
- Content edits go through a typed SECURITY-DEFINER RPC per table, mirroring update_taxonomy_node → edit_recipe_doc(p_doc_id,p_patch,p_reason) admin-gates, patches recipe_docs.doc, and inserts one audit_log row with actor=auth.uid(), source='manual-ui-edit'. No generic content-edit framework.
- One FilterBar object drives both what-you-see and what-you-act-on → FilterBar emits {filters, scope}; filters feed usePagedQuery, scope feeds enqueue_job — so a filtered view and a filtered trigger can never drift.
- Trigger scoping is one <TriggerBar> with four scope kinds → item | multiselect (DataTable selection) | filter (FilterBar) | whole_queue. CostConfirmModal (composes Modal) appears only for metered stages, which are read from stage_config, not hardcoded — the provider chain is owner-rewired config.
- Live status via Supabase Realtime + react-query, no server → useRealtimeJobs subscribes to postgres_changes on jobs and merges into the react-query cache; aggregate queue depth comes from a stage_queue_counts view polled by react-query. Fallback to polling if the channel drops.
- Data fetching consolidates on usePagedQuery → react-query with keepPreviousData replaces the hand-rolled useState/useEffect/range fetch in RecipeList/RecipeDetail, giving the no-flash pending overlay for free and one place to improve.
- Bundle preview is generated on demand, never stored → /ops/exports renders {recipe,verbs,meta} from the relational rows via JsonView + client-side Blob download; UI states the parity invariant bundle == doc minus _x sidecar.

### Open
- Signed-R2 URL minting for the corpus iframe: the SPA has no server. Assume a single Supabase Edge Function sign-corpus-url(r2_key) invoked via supabase.functions.invoke — is that acceptable, or is there a worker endpoint preferred? This is the one place server code enters the UI tract.
- Cost estimate source for the confirm modal: client-side heuristic (item_count * per_item_cents) vs a worker-provided estimate_job_cost(scope) RPC vs a dedicated dry-run job. Who owns the per-stage/per-provider cost table?
- Audit mechanism: explicit INSERT inside each edit RPC (assumed here for manual edits) vs supa_audit / a generic trigger + SET LOCAL app.actor for worker writes. Foundation assumes RPC-explicit for the human path; confirm the worker path so the two don't double-log.
- recipe_docs edit granularity: shallow jsonb `doc || p_patch` merge (assumed) vs a JSON-path patch vs whole-doc replace validated against doc_schema. Deep-field edits (nested ingredients/steps) may need jsonb_set paths.
- Realtime scale/RLS: subscribe to the whole jobs table vs per-job channels; jobs/audit_log must be in the realtime publication and RLS must let admins read but not write directly (writes only via RPC).
- Is /ops/review a distinct route or purely a canned-filter preset of /ops/docs? Spec treats it as the latter (DRY) — confirm no batch-specific affordances force a separate screen.
- stage_config source of truth for 'is this stage metered' + 'requires_approval': a table the UI reads vs a shared TS const vs derived from the provider chain config. Needs to exist before TriggerBar can decide whether to show CostConfirmModal.
- Which entity keys join stage_runs/audit_log to recipe_docs (bigint id vs source_url vs a composite) — the DataTable drilldowns and the edit RPC's audit pk both depend on a single canonical entity identifier.



## 11. Foundation — DevOps, CD & Setup Runbook

### DevOps / CD + Setup Runbook — v2.1 fully-cloud topology

Foundation spec for standing up and continuously deploying the v2.1 architecture. Target is a single-environment (`staging`, which doubles as live), fully-cloud, ~$30/mo topology. No k8s, no Terraform, no second environment beyond what exists today.

#### 0. Target topology at a glance

| Concern | Service | Deploy trigger | Cost tier |
|---|---|---|---|
| Relational DB (pipeline + serving) | **Supabase Pro** (one project) | `supabase db push` via GH Action on push to `staging` | Pro $25/mo |
| Corpus bytes (16 GiB HTML, read-only) | **Cloudflare R2** (one bucket, versioned + object-lock) | one-time upload; never re-scraped | R2 ~free at this size |
| Pipeline worker (Python, `stage_fn(job)`) | **Railway** (one service) | Railway native deploy-on-push, or `railway up` GH Action | ~$5/mo |
| Web SPA + `/ops` console | **Vercel** (existing `spiritolo-staging`) | native, push to `staging` = prod, PR = preview | free |
| Recipe grammar library | **RecipeGF** (`mrjogo/RecipeGF`) | git tag `v0.4.0`; Spiritolo pins the tag | n/a |

Two facts the worker reaches out to that are NOT hosted by us: **barbot's local LLM** (over Tailscale, the free default provider) and metered APIs (**ScraperAPI**, OpenAI/Claude/DeepSeek).

The worker has **no host affinity** and **no inbound ports** — it polls the `jobs` table (`SELECT … FOR UPDATE SKIP LOCKED`). There is no API server and no message broker; Postgres is the queue. This keeps Railway config to a single long-running process with no HTTP healthcheck surface required.

---

#### 1. Supabase Pro — migrations CD

**Provisioning.** One project, `spiritolo-staging` (ref `atvlzbgrquiseczzeczn`, `https://atvlzbgrquiseczzeczn.supabase.co`). Upgrade the existing free project to **Pro** in the dashboard (Settings → Billing) — do *not* create a new project (avoids re-pointing every secret + Vercel env). Pro removes the 7-day pause (the `keepalive.yml` Action becomes redundant — leave it, it's a cheap no-op) and lifts the egress ceiling that motivated the local-restore-then-upload dance.

**Consequence for v2.1's "write in place" stance.** v2.1 explicitly rejects the pipeline/serving DB split and runs pipelines *directly against the one Pro DB* (metered work gated by `jobs.approved` + `max_cost_cents`, not by the upload firewall). The `docs/upload.md` local-restore-then-upload flow and `upload_to_staging` remain valid for *bulk offline backfills a human wants to stage and throw away*, but are **no longer the default path** — the worker writes to Supabase directly. Keep `backup-supabase.sh` purely as the disaster-recovery + R2-archived snapshot mechanism.

**Migrations CD — extend `deploy-migrations.yml`.** Today it fires on push to `staging` (paths `supabase/migrations/**`) and runs `supabase db push --db-url "$SUPABASE_STAGING_DB_URL" --include-all`. That mechanism is correct and stays. Two additions for v2.1:

1. **PR-to-`main` dry-run gate** (the "on merge to … main" half — there is only one DB, so `main` gets a *validation* gate, not a second deploy target; this is the YAGNI-correct reading). Add a job on `pull_request: [main]` that spins up a throwaway Postgres service (mirror `ingredients-ci.yml`'s `services.postgres`) and runs `supabase db lint` + a forward-apply of `supabase/migrations/*.sql` to catch a migration that won't apply *before* it reaches `staging`.
2. **Post-apply projection rebuild.** v2.1's projections (`recipe_doc_ingredients`, `recipes_public`, `recipe_clusters` materialization) are `TRUNCATE`-and-rebuild pure functions of `recipe_docs`. Schema changes that alter a projection's shape need a rebuild. Model each rebuild as a SQL function (`public.rebuild_projections()`) invoked by the deploy job after `db push`, idempotent by construction.

```yaml
# .github/workflows/deploy-migrations.yml  (staging deploy job, extended tail)
      - name: Push migrations to staging
        env:
          STAGING_DB_URL: ${{ secrets.SUPABASE_STAGING_DB_URL }}
        run: |
          set -euo pipefail
          [ -n "$STAGING_DB_URL" ] || { echo "SUPABASE_STAGING_DB_URL unset" >&2; exit 1; }
          supabase db push --db-url "$STAGING_DB_URL" --include-all
          psql "$STAGING_DB_URL" -v ON_ERROR_STOP=1 -c "select public.rebuild_projections();"
```

```yaml
# new job, same file — the main-PR validation gate
  validate:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_USER: postgres, POSTGRES_PASSWORD: postgres, POSTGRES_DB: postgres }
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U postgres" --health-interval 5s
          --health-timeout 5s --health-retries 20
    steps:
      - uses: actions/checkout@v6
      - uses: supabase/setup-cli@v2
        with: { version: latest }
      - name: Forward-apply migrations to throwaway PG
        env: { DB: "postgresql://postgres:postgres@localhost:5432/postgres" }
        run: |
          set -euo pipefail
          for f in supabase/migrations/*.sql; do
            psql "$DB" -v ON_ERROR_STOP=1 -f "$f"
          done
```

Trigger block becomes:
```yaml
on:
  push:
    branches: [staging]
    paths: ['supabase/migrations/**']
  pull_request:
    branches: [main]
    paths: ['supabase/migrations/**']
  workflow_dispatch:
```

**Secrets (repo → Settings → Secrets and variables → Actions).** `SUPABASE_STAGING_DB_URL` must be the **Supavisor session pooler** (`postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres`) — the direct `db.<ref>.supabase.co` endpoint is IPv6-only and the transaction pooler (6543) breaks `pg_dump`/session DDL. Already documented in `backup-supabase.sh`.

**Promotion model** stays as CLAUDE.md's hosting section describes: `staging` is PR-only (ruleset-locked), promote by `gh pr create --base staging --head main` and **merge with a merge commit, never squash**. (`docs/deployment.md`'s `--ff-only` snippet is stale — flag for correction to match CLAUDE.md.)

**RLS / role boundary.** The worker connects as a **service role** (bypasses RLS) via `SUPABASE_DB_URL`. The web SPA reads `recipes_public` via the **publishable key** (`sb_publishable_…`) and mutates only through **SECURITY-DEFINER RPCs** (`enqueue_job`, `approve_job`, admin content edits) gated by `is_admin`. No table is anon-writable.

---

#### 2. Railway — the Python worker

**What runs.** One always-on service executing a poll loop: claim a job (`FOR UPDATE SKIP LOCKED`), dispatch to `stage_fn(job)`, heartbeat, UPSERT results idempotently, on boot reconcile open `job_batches`. No web server, no exposed port. Railway keeps it alive and restarts on crash; the reaper RPC requeues jobs whose heartbeat went stale, so a Railway restart is safe.

**Dockerfile** (repo root, `worker.Dockerfile`) — builds the uv workspace, installs the `spiritolo-ingredients` package (the merged Zone-1+Zone-2 worker entrypoint lives there), and bakes Tailscale in for userspace networking:

```dockerfile
# worker.Dockerfile
FROM python:3.11-slim AS base

# uv (pinned via installer); git needed for the recipegf git dependency.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates curl iptables \
 && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Tailscale static binaries (userspace mode → no NET_ADMIN/TUN needed).
COPY --from=docker.io/tailscale/tailscale:stable /usr/local/bin/tailscaled /usr/local/bin/tailscaled
COPY --from=docker.io/tailscale/tailscale:stable /usr/local/bin/tailscale  /usr/local/bin/tailscale

WORKDIR /app
# Copy the whole workspace so uv resolves the path/workspace members + lockfile.
COPY pyproject.toml uv.lock ./
COPY common/ common/
COPY ingredients/ ingredients/
COPY scraper/ scraper/
COPY scripts/ scripts/
# recipegf is a private git dep; pass a build-time token so `uv sync` can clone.
ARG RECIPEGF_TOKEN=
RUN if [ -n "$RECIPEGF_TOKEN" ]; then \
      git config --global url."https://x-access-token:${RECIPEGF_TOKEN}@github.com/".insteadOf "https://github.com/"; \
    fi \
 && uv sync --frozen --package spiritolo-ingredients

COPY scripts/worker-entrypoint.sh /usr/local/bin/worker-entrypoint.sh
RUN chmod +x /usr/local/bin/worker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/worker-entrypoint.sh"]
```

**Tailscale-in-container userspace pattern** (`scripts/worker-entrypoint.sh`). Railway containers run **unprivileged** — no `/dev/net/tun`, no `NET_ADMIN`. Tailscale's `--tun=userspace-networking` mode plus a local SOCKS5/HTTP proxy is exactly this case. The worker's LLM client points at the proxy to reach barbot's Tailnet IP; ScraperAPI + hosted-LLM traffic goes out the normal default route.

```bash
#!/usr/bin/env bash
# scripts/worker-entrypoint.sh
set -euo pipefail

# 1. Bring up tailscaled in userspace mode with a local proxy on :1055.
/usr/local/bin/tailscaled \
  --tun=userspace-networking \
  --socks5-server=localhost:1055 \
  --outbound-http-proxy-listen=localhost:1055 \
  --state=mem: &                       # ephemeral state; re-auth each boot

# 2. Join the tailnet. Ephemeral + preauthorized key → node self-cleans on exit.
/usr/local/bin/tailscale up \
  --authkey="${TAILSCALE_AUTHKEY:?TAILSCALE_AUTHKEY required}" \
  --hostname="spiritolo-worker" \
  --accept-routes

# 3. Route the LOCAL-provider LLM client through the tailnet proxy.
#    Only barbot traffic needs this; the client reads ALL_PROXY. Hosted APIs
#    (OpenAI/Claude/ScraperAPI) should bypass — configure the local provider's
#    client to use ALL_PROXY explicitly rather than exporting it globally.
export ALL_PROXY="socks5://localhost:1055"
export TS_LOCAL_PROXY="socks5://localhost:1055"   # worker reads this for barbot only

exec uv run --package spiritolo-ingredients python -m ingredients.worker
```

Design note: do **not** export `HTTPS_PROXY` globally or every hosted-API call also tunnels through barbot's uplink. The `local` provider's HTTP client reads `TS_LOCAL_PROXY`; all other providers use the direct route. `OLLAMA_BASE_URL` becomes barbot's Tailnet name, e.g. `http://barbot:11434`.

**Railway service config** (`railway.json` at repo root, so `railway up` is declarative):

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "worker.Dockerfile"
  },
  "deploy": {
    "startCommand": null,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10,
    "numReplicas": 1
  }
}
```

Single replica is deliberate: `SKIP LOCKED` makes N replicas *safe* but at this scale one worker suffices, and one is easier to reason about for cost caps. (Scaling to N is a config bump, not a redesign — noted, not built.)

**Deploy trigger.** Prefer **Railway native GitHub integration** (connect the repo in the Railway dashboard, watch branch `staging`) — zero extra CI. If you'd rather gate deploys behind CI, a `railway up` Action works:

```yaml
# .github/workflows/deploy-worker.yml
name: Deploy worker to Railway
on:
  push:
    branches: [staging]
    paths: ['ingredients/**','common/**','scraper/**','worker.Dockerfile','scripts/worker-entrypoint.sh','railway.json','uv.lock']
  workflow_dispatch:
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - name: Deploy
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}     # project token
        run: |
          set -euo pipefail
          npm i -g @railway/cli
          railway up --service spiritolo-worker --ci
```

Pass `RECIPEGF_TOKEN` as a Railway **build arg** (dashboard → service → Settings → Build → build args, or `railway variables`) so the Dockerfile clone succeeds; it isn't needed at runtime.

**Worker env / secrets** (Railway → service → Variables):

| Var | Purpose |
|---|---|
| `SUPABASE_DB_URL` | service-role session-pooler URL to the Pro DB (the queue + content) |
| `SCRAPERAPI_KEY` | fetch stage HTTP API (metered) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` | hosted LLM providers (metered; used only when a stage's provider chain selects them) |
| `TAILSCALE_AUTHKEY` | ephemeral, preauthorized tailnet key to reach barbot |
| `OLLAMA_BASE_URL` | `http://barbot:11434` (Tailnet MagicDNS name) |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | corpus reads (S3-compat) |
| `WORKER_ID` | optional stable id; else derive from Railway replica id |

Provider selection is **config-not-code**: the stage→provider-chain mapping lives in a config row/file the owner rewires after the LLM spike; the worker must read it, never hardcode order. `local` (barbot via Tailscale, free) is the default first link.

---

#### 3. Vercel — web SPA + `/ops`

Native deploys already work (push to `staging` = production, PR = preview). No CD change. The `/ops` admin console ships in the same SPA (gated by `RequireAdmin`/`useIsAdmin`/`profiles.is_admin`), so it deploys with the app — **no new build target**.

**Env (Vercel → Project → Settings → Environment Variables), Production + Preview:**

| Var | Value |
|---|---|
| `VITE_SUPABASE_URL` | `https://atvlzbgrquiseczzeczn.supabase.co` |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | `sb_publishable_…` (staging project API settings) |

`/ops` needs **no extra env** — it enqueues/approves jobs and edits content through SECURITY-DEFINER RPCs authorized by the user's JWT + `is_admin`, and watches `jobs` via Supabase Realtime, all through the same publishable key + authenticated session. The service-role key never touches the browser.

---

#### 4. Cloudflare R2 — corpus bytes

**Bucket.** One bucket, `spiritolo-corpus`. Objects are gzipped HTML keyed `sha256(url)` (content-addressed → dedupe + immutable). Enable **versioning** and **object-lock (compliance/governance retention)** so a bad job can never destroy the only copy of a scrape. Corpus is **read-only after the one-time load; never re-scraped.** Only the lightweight `pages` row (url, site, r2 key, denylist flag, fetch meta) lives in Postgres.

**Create with object-lock.** Object-lock must be enabled **at bucket creation** — it can't be turned on later. `wrangler` handles basic bucket ops but object-lock enablement goes through the S3-compatible API (`aws-cli` against the R2 endpoint):

```bash
# Object-lock requires the bucket be created with it enabled up-front.
export R2_ENDPOINT="https://<account_id>.r2.cloudflarestorage.com"
aws s3api create-bucket \
  --bucket spiritolo-corpus \
  --object-lock-enabled-for-bucket \
  --endpoint-url "$R2_ENDPOINT"

# Default retention (governance = admins with perms can override; compliance = nobody).
aws s3api put-object-lock-configuration \
  --bucket spiritolo-corpus \
  --object-lock-configuration '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"GOVERNANCE","Years":2}}}' \
  --endpoint-url "$R2_ENDPOINT"

# Versioning (belt-and-suspenders against overwrite of a sha256 key).
aws s3api put-bucket-versioning \
  --bucket spiritolo-corpus \
  --versioning-configuration '{"Status":"Enabled"}' \
  --endpoint-url "$R2_ENDPOINT"
```

Basic inspection via wrangler once created: `wrangler r2 bucket list`, `wrangler r2 object get spiritolo-corpus/<key>`.

**One-time corpus upload** (16 GiB, from the box holding the existing HTML cache). Each object: gzip the HTML, key = `sha256(url)`, content-type `text/html`, content-encoding `gzip`, metadata `url`. Sketch:

```bash
# For each cached page: derive key, gzip, upload with content metadata.
# (Real loader is a small script; this shows the exact per-object shape.)
key=$(printf '%s' "$url" | sha256sum | awk '{print $1}')
gzip -9 -c "$html_file" > /tmp/page.gz
aws s3api put-object \
  --bucket spiritolo-corpus \
  --key "$key" \
  --body /tmp/page.gz \
  --content-type "text/html" \
  --content-encoding "gzip" \
  --metadata "url=$url" \
  --endpoint-url "$R2_ENDPOINT"
```

Use `aws s3 cp --recursive` with a pre-staged, pre-gzipped, sha256-named directory for throughput; parallelism via `aws configure set s3.max_concurrent_requests`. R2 has **no egress fees**, so the worker reads freely.

**Creds.** Create an **R2 API token** (Cloudflare dashboard → R2 → Manage API Tokens) scoped to this bucket → yields Access Key ID + Secret + the account-id endpoint. Store as the four `R2_*` Railway vars above. The upload box uses the same creds in its `~/.aws/credentials` or env.

---

#### 5. RecipeGF v0.4.0 release flow

RecipeGF lives in a separate repo (`~/code-projects/RecipeGF`, GitHub `mrjogo/RecipeGF`). Spiritolo pins it as a git dependency by **tag**, currently `v0.3.0`. Tract A lands the additive v0.4.0 changes (ingredient `amount_max`/`modifiers`/`ref`, unit registry migration, validator rule) via self-reviewed PRs in that repo, then **tags v0.4.0**; Spiritolo bumps the pin.

**Release the tag (in RecipeGF repo):**
```bash
cd ~/code-projects/RecipeGF
git checkout main && git pull
# green cross-language conformance before tagging:
(cd python && uv run pytest) && (cd spec/conformance && npm test)
git tag -a v0.4.0 -m "Ingredient seams (amount_max, modifiers, ref) + unit registry as sole authority"
git push origin v0.4.0
gh release create v0.4.0 --title "v0.4.0" --notes "Optional-additive; schema const stays recipegf/cocktail/v1."
```

**Bump the pin (in Spiritolo)** — edit `ingredients/pyproject.toml`:
```toml
recipegf = { git = "https://github.com/mrjogo/RecipeGF.git", tag = "v0.4.0", subdirectory = "python" }
```
```bash
cd ~/code-projects/spiritolo
uv lock --upgrade-package recipegf
(cd ingredients && uv run --extra dev pytest)   # confirm the pinned tag resolves + suite green
```
The `RECIPEGF_TOKEN` secret (already used by `ingredients-ci.yml`) authenticates the private-repo clone in CI, in the Railway build, and in local `uv sync`. If RecipeGF is public, it's a no-op.

---

#### SETUP RUNBOOK — zero to running

Prereqs on the operator box: `gh` (authed), `supabase` CLI, Node (`npx`/`npm`), `railway` CLI (`npm i -g @railway/cli`), `wrangler` (`npm i -g wrangler`), `aws-cli`, `psql`/`pg_restore` v17+, `tailscale` account with barbot already on the tailnet.

**1. Supabase Pro.** Upgrade the existing `spiritolo-staging` project to Pro (dashboard → Billing). Capture the session-pooler URL.
```bash
supabase login
supabase link --project-ref atvlzbgrquiseczzeczn
supabase db push --db-url "$SUPABASE_STAGING_DB_URL" --include-all   # apply v2.1 migrations
psql "$SUPABASE_STAGING_DB_URL" -c "select public.rebuild_projections();"
```

**2. Repo secrets for CI.**
```bash
gh secret set SUPABASE_STAGING_DB_URL --body "postgresql://postgres.atvlzbgrquiseczzeczn:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres"
gh secret set RECIPEGF_TOKEN         --body "<read-only PAT for mrjogo/RecipeGF>"   # skip if public
gh secret set RAILWAY_TOKEN          --body "<railway project token>"               # only if using the Action, not native deploy
# keep existing SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY (keepalive)
```

**3. Cloudflare R2.**
```bash
wrangler login
# Create R2 API token in dashboard → get Access Key/Secret + account endpoint.
export R2_ENDPOINT="https://<account_id>.r2.cloudflarestorage.com"
export AWS_ACCESS_KEY_ID=<r2_key> AWS_SECRET_ACCESS_KEY=<r2_secret> AWS_DEFAULT_REGION=auto
aws s3api create-bucket --bucket spiritolo-corpus --object-lock-enabled-for-bucket --endpoint-url "$R2_ENDPOINT"
aws s3api put-bucket-versioning --bucket spiritolo-corpus --versioning-configuration '{"Status":"Enabled"}' --endpoint-url "$R2_ENDPOINT"
aws s3api put-object-lock-configuration --bucket spiritolo-corpus \
  --object-lock-configuration '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"GOVERNANCE","Years":2}}}' \
  --endpoint-url "$R2_ENDPOINT"
# then run the corpus loader (§4) once, and backfill `pages.r2_key`.
```

**4. Tailscale auth key.** Dashboard → Settings → Keys → Generate auth key → **Ephemeral + Pre-approved + Reusable**. Copy it (used as `TAILSCALE_AUTHKEY`). Confirm barbot is on the tailnet and MagicDNS resolves `barbot`.

**5. Railway worker.**
```bash
railway login
railway init --name spiritolo-worker        # or `railway link` to an existing project
railway variables --set SUPABASE_DB_URL="postgresql://postgres.atvlzbgrquiseczzeczn:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres" \
  --set SCRAPERAPI_KEY=<key> \
  --set OPENAI_API_KEY=<key> --set ANTHROPIC_API_KEY=<key> --set DEEPSEEK_API_KEY=<key> \
  --set TAILSCALE_AUTHKEY=<ts_authkey> \
  --set OLLAMA_BASE_URL="http://barbot:11434" \
  --set R2_ACCOUNT_ID=<id> --set R2_ACCESS_KEY_ID=<key> --set R2_SECRET_ACCESS_KEY=<secret> --set R2_BUCKET=spiritolo-corpus
# RECIPEGF_TOKEN as a BUILD arg (dashboard → Settings → Build), not a runtime var.
railway up --ci                              # first deploy from worker.Dockerfile / railway.json
railway logs                                 # confirm: tailscaled up, tailnet joined, poll loop started
```
Then connect the repo in the Railway dashboard and set the watched branch to `staging` for native deploy-on-push (or rely on `deploy-worker.yml`).

**6. Vercel web.** Project `spiritolo-staging` already exists.
```bash
vercel link                                   # link cwd to the project (once)
vercel env add VITE_SUPABASE_URL production            # https://atvlzbgrquiseczzeczn.supabase.co
vercel env add VITE_SUPABASE_PUBLISHABLE_KEY production # sb_publishable_…
vercel env add VITE_SUPABASE_URL preview
vercel env add VITE_SUPABASE_PUBLISHABLE_KEY preview
# deploys happen natively on push to `staging`; no manual `vercel deploy` needed.
```

**7. RecipeGF v0.4.0.** Tag in RecipeGF, bump the pin in Spiritolo (§5), open the pin-bump PR to `main`.

**8. Smoke the whole loop.** Sign into `/ops` as an admin, enqueue a **1-URL** scoped `fetch` job, approve it (metered → confirm-before-cost), and watch: Railway worker claims it, ScraperAPI fetches, bytes land in R2, the `pages`/`recipe_docs`/`stage_runs` rows appear, `/ops` shows live status via Realtime, and an `audit_log` row records the mutation.

**9. Promote.** `gh pr create --base staging --head main --title "Promote main → staging" --body "…"`; merge with a **merge commit**. Staging Vercel + migrations Action + Railway all pick it up.

---

#### CD wiring summary

| Path changed | Workflow / mechanism | Effect |
|---|---|---|
| `supabase/migrations/**` (PR → main) | `deploy-migrations.yml` validate job | forward-apply on throwaway PG; blocks a broken migration |
| `supabase/migrations/**` (push → staging) | `deploy-migrations.yml` push job | `db push` + `rebuild_projections()` on Pro DB |
| `ingredients/**`, `common/**` (PR → main) | `ingredients-ci.yml` | pytest gate (unchanged) |
| worker code / Dockerfile (push → staging) | Railway native, or `deploy-worker.yml` | `railway up`, worker redeploys |
| `web/**` (push → staging / any PR) | Vercel native | prod / preview deploy |
| RecipeGF tag `v0.4.0` | manual `git tag` + Spiritolo pin bump | grammar library upgrade |

### YAGNI cuts
- No Kubernetes, no Terraform/IaC — bucket, service, and secrets are stood up with direct CLI in the runbook; the config that IS declarative (railway.json, worker.Dockerfile, the GH workflows) lives in-repo.
- No second/production environment — staging remains the single live environment; `main` gets a migration dry-run gate, not a deploy target.
- No message broker (SQS/Rabbit/Redis) and no API server — Postgres FOR UPDATE SKIP LOCKED is the queue; the worker has no inbound port.
- No multi-replica autoscaling of the worker — numReplicas=1; SKIP LOCKED keeps N-replica safe as a future config bump, not built now.
- No automated pipeline scheduling/cron — all work is UI-triggered and scoped; confirm-before-cost only on metered work. (The Supabase keepalive cron stays but is redundant under Pro.)
- No custom domain / Resend domain verification — staging stays single-user magic-link; not a CD concern.
- No global HTTPS_PROXY export in the worker — only the local barbot provider tunnels through Tailscale; hosted APIs take the direct route to avoid needless latency and barbot-uplink dependency.
- No re-scrape path for the corpus — R2 is write-once (object-lock + versioning), read-only thereafter; the worker never re-fetches cached bytes.
- No separate build target or hosting for /ops — it ships inside the existing Vercel SPA behind RequireAdmin, deploying with the app.
- No bespoke audit framework — prefer the smallest actor+diff+time capture (custom trigger + SET LOCAL app.actor, or supa_audit) over a heavyweight event-sourcing layer.

### Key decisions
- Supabase: upgrade the existing free project in place to Pro rather than provisioning a new project → Avoids re-pointing SUPABASE_STAGING_DB_URL, Vercel env, and the keepalive secret across the stack; ref atvlzbgrquiseczzeczn stays stable. Pro removes the 7-day pause and egress ceiling that motivated the upload firewall.
- Migrations CD keeps `staging` as the sole deploy target; `main` gets a validation-only gate → There is exactly one Pro DB in v2.1 (the pipeline/serving split is explicitly rejected). 'On merge to staging/main' is honored as: staging = deploy, main-PR = forward-apply dry-run on throwaway Postgres. No second environment (YAGNI).
- Worker deploys as a single Railway service with no inbound port or healthcheck → Postgres-as-queue (SELECT ... FOR UPDATE SKIP LOCKED) means no broker and no API server; the worker only polls. Reaper + idempotent UPSERTs make Railway restarts safe. numReplicas=1 (scaling to N is a config bump, not built now).
- Tailscale runs in userspace-networking mode with a local SOCKS5/HTTP proxy on :1055 → Railway containers are unprivileged (no /dev/net/tun, no NET_ADMIN). Only the `local` (barbot) LLM provider routes through the proxy via TS_LOCAL_PROXY; hosted APIs bypass so their traffic doesn't tunnel through barbot's uplink. Ephemeral+preauth key so the node self-cleans.
- R2 bucket created with object-lock via aws-cli, not wrangler → Object-lock must be enabled at bucket-creation and wrangler exposes no flag for it; aws-cli create-bucket --object-lock-enabled-for-bucket against the R2 S3 endpoint is the exact-CLI path. Versioning + GOVERNANCE retention added on top. wrangler used only for basic list/get.
- Corpus keyed by sha256(url), gzipped, uploaded once and never re-scraped → Content-addressed keys dedupe and are immutable; R2 has no egress fee so the worker reads freely. Only the lightweight pages row (url, site, r2_key, denylist, fetch meta) lives in Postgres.
- RECIPEGF_TOKEN is a build-time arg in the Dockerfile / Railway build, not a runtime secret → The private git clone only happens during `uv sync` at image build; leaking it into the running container is unnecessary. Mirrors the existing ingredients-ci.yml token pattern.
- upload_to_staging / local-restore flow demoted from default path to disaster-recovery + offline-backfill only → v2.1 writes to the one Pro DB directly (metered work gated by jobs.approved + max_cost_cents). backup-supabase.sh survives as the R2-archived snapshot + DR mechanism.

### Open
- Exact Cloudflare R2 support for object-lock via wrangler vs aws-cli should be confirmed against the current wrangler version at build time — the spec routes object-lock through aws-cli because wrangler historically lacks the flag, but a newer wrangler may add it.
- Does barbot's Tailnet expose Ollama on a stable MagicDNS name (`barbot:11434`) or only a raw 100.x IP? MagicDNS assumed; confirm it's enabled on the tailnet.
- Whether to keep the OpenAI async Batch API path at all for the worker, given v2.1 makes packed real-time requests the core path and Batch only an optional accelerator — affects whether job_batches boot-reconciliation ships in v1 of the worker.
- Should the worker run as a truly always-on Railway service (idle cost) or be woken on-demand? Spec assumes always-on poll loop; an on-demand model would need a lightweight trigger (e.g. Railway cron or an RPC-driven wake) and is not built.
- RecipeGF repo visibility (private vs public) determines whether RECIPEGF_TOKEN is required everywhere; spec handles both but the actual state should be pinned down.
- Confirm whether Railway's build environment can reach github.com to clone the recipegf git dependency, or whether the dependency should be vendored/pre-built into a wheel to avoid a build-time network dependency.



## 12. Workstreams — Tract A · RecipeGF v0.4.0 (A1–A6)

Tract A lands RecipeGF v0.4.0 in ~/code-projects/RecipeGF as six workstreams, all optional-additive with the `schema` const frozen at `recipegf/cocktail/v1`. WS-A1/A2/A3 add the three ingredient seams (quantity.amount_max with a validator code-tier rule, ingredient.ref as portable grammar-only, ingredient.modifiers); WS-A4 migrates Spiritolo's ~66-unit vocabulary into the bar/count registries so RecipeGF is the sole unit authority; WS-A5 bumps versions to 0.4.0 and tags the release (the gate that unblocks Tract B); WS-A6 (repo spiritolo) bumps the pin and retires the local unit tables. Every workstream is RED-first: schema/model shape tests, ingredient_ref parity tests mirroring test_recipe_id.py::test_pattern_matches_schema in BOTH TS and Python, and shared conformance fixtures added to spec/conformance/manifest.yaml (boolean-outcome contract, both languages parametrize it) so TS and Python can't drift. The three RecipeGF CI jobs (ts, python, spec-sync git-diff) stay green on every self-reviewed PR.

TWO DISCREPANCIES surfaced from reading the actual code, flagged for the owner: (1) `step.modifiers` in the frozen schema is a freeform OBJECT (`additionalProperties:true`, never validated), so "ingredient.modifiers mirrors step.modifiers" means an object — NOT the `["chilled"]` array shown in the architecture doc's _x example. WS-A3 mirrors the object per the literal instruction; if an array is truly wanted that is a different, non-mirroring shape. (2) The ref grammar = recipe-id minus `:vN`, whose authority is reverse-DNS (>=2 dot labels). So per the worked example WS-A1, `spiritolo/gin` (single-label) is INVALID and `com.spiritolo/gin` is valid — yet several _x sidecar examples in the shared context write `ref: "spiritolo/campari"`. WS-A2 enforces reverse-DNS (matching recipe_id); Spiritolo must emit `com.spiritolo/<slug>`. Both are called out in the relevant workstream's yagni/red so the reviewer decides deliberately.

Structural note: A1/A2/A3 all edit the single schema JSON (spec/schema/recipegf-cocktail-v1.json), models.py, packages/core/src/types.ts, and append to spec/conformance/manifest.yaml, so they serialize on those shared files (A1 first, then A2, then A3); their new-module and fixture files are otherwise disjoint. A4's registry YAML is disjoint from the schema; it only serializes on the manifest append. A5 depends on A1-A4 merged; A6 depends on A5 tagged v0.4.0.

### WS-A1 — Add quantity.amount_max seam (schema + models + validator code-tier rule amount_max >= amount)  [recipegf]
- depends_on: []
- parallelism: First mover on the shared interface files. serialize-after none; blocks WS-A2/WS-A3 on spec/schema/recipegf-cocktail-v1.json, python/src/recipegf/models.py, packages/core/src/types.ts, and the manifest append. Overlap map: those four files are edited by A1/A2/A3, so run A1 -> A2 -> A3 to avoid conflicts; disjoint elsewhere.
- goal: A RecipeGF quantity may carry an optional amount_max expressing a range, and the validator rejects amount_max < amount. Optional-additive; schema const unchanged.
- files: spec/schema/recipegf-cocktail-v1.json (definitions.quantity.properties.amount_max), spec/conformance/manifest.yaml (+2 cases), spec/conformance/valid/amount-max-range.yaml (new), spec/conformance/invalid/amount-max-less-than-amount.yaml (new), python/src/recipegf/models.py (Quantity.amount_max), python/src/recipegf/validator.py (code-tier rule), packages/core/src/types.ts (Quantity.amount_max), packages/core/src/validator.ts (code-tier rule), python/tests/test_amount_max.py (new), packages/core/src/__tests__/amount-max.test.ts (new), vendored copies via `npm run sync:spec`: packages/core/schema/*, python/src/recipegf/_spec/schema/*
- RED tests:
    - python/tests/test_amount_max.py::test_quantity_model_accepts_amount_max — Quantity.model_validate({'amount':1,'amount_max':2,'unit':'oz'}) succeeds; asserts .amount_max==2. FAILS today: ConfigDict(extra='forbid') rejects the unknown key.
    - python/tests/test_amount_max.py::test_quantity_model_defaults_amount_max_none — Quantity.model_validate({'amount':1,'unit':'oz'}).amount_max is None (optional-additive, back-compat).
    - python/tests/test_amount_max.py::test_schema_allows_amount_max — a full doc with quantity.amount_max passes RecipeValidator().validate(...).valid is True. FAILS today: definitions.quantity has additionalProperties:false so the extra key is a schema violation.
    - python/tests/test_amount_max.py::test_schema_const_unchanged — schema.properties.recipe.properties.schema.const == 'recipegf/cocktail/v1' (guard that this additive change never touches the const).
    - Conformance valid/amount-max-range.yaml -> valid (one ingredient with quantity {amount:1, amount_max:1.5, unit:oz}); parametrized by BOTH conformance.test.ts and test_conformance.py. FAILS in both langs until schema+validator land.
    - Conformance invalid/amount-max-less-than-amount.yaml -> invalid (quantity {amount:2, amount_max:1, unit:oz}); the amount_max < amount code-tier rule. FAILS in both langs until the validator rule lands.
    - packages/core/src/__tests__/amount-max.test.ts — TS mirror: validator.validate over an in-memory doc returns valid for a well-ordered range and one error at /recipe/ingredients/0/quantity/amount_max for amount_max<amount.
- GREEN: Schema: add amount_max: {type:['number','null'], description:'Optional upper bound of an amount range'} to definitions.quantity.properties, keeping additionalProperties:false. models.py Quantity: `amount_max: float | None = None`. types.ts Quantity: `amount_max?: number | null`. validator.py + validator.ts: after the existing ingredient-unit loop, add a code-tier rule — for each ingredient with a non-null amount_max, if amount_max < amount push ValidationError at `/recipe/ingredients/{i}/quantity/amount_max` (message like `amount_max N is less than amount M`). Schema pattern/structure alone can't express the cross-field >= so it MUST be code-tier (mirrors the existing duplicate-name / unit checks). Run `npm run gen:standard-units` (no-op here) then `npm run sync:spec` to update the two vendored schema copies.
- DONE:
    - ci.yml all three jobs green: ts (npm test -w packages/core), python (uv run pytest in python/), spec-sync (gen:standard-units + sync:spec + git diff --exit-code clean).
    - Conformance manifest agrees in both languages for the two new cases.
    - schema const parity guard green; no version-const bump in this WS (0.4.0 tag is cut by WS-A5).
    - Self-reviewed PR merged to main.
- YAGNI:
    - No amount range semantics beyond the >= ordering check — no min/max unit coercion, no averaging, no rendering hints.
    - No new schema-version const; no change to required[]; amount_max stays optional and defaults null.
    - No pydantic validator on Quantity itself for the cross-field rule — the RecipeValidator is the single validation authority (models are a convenience layer), so the ordering rule lives only in the validator code tier.

### WS-A2 — Add ingredient.ref portable <authority>/<slug> grammar (ingredient_ref.py + ingredient-ref.ts + schema-parity test)  [recipegf]
- depends_on: ['WS-A1']
- parallelism: serialize-after WS-A1 (shares spec/schema/recipegf-cocktail-v1.json, models.py, types.ts, manifest.yaml). New module + fixture files are disjoint; the only true overlap is the shared schema/models/types/manifest files. blocks WS-A3 on those same files.
- goal: RecipeGF owns the GRAMMAR of a portable cross-recipe ingredient identifier (recipe-id minus :vN) via a new ingredient_ref module in both languages, with a schema<->code parity test mirroring recipe_id. Grammar only — no vocabulary, no resolution. schema const unchanged.
- files: python/src/recipegf/ingredient_ref.py (new), python/src/recipegf/__init__.py (export INGREDIENT_REF_PATTERN, is_valid_ingredient_ref, parse_ingredient_ref, format_ingredient_ref, IngredientRef), python/tests/test_ingredient_ref.py (new), packages/core/src/ingredient-ref.ts (new), packages/core/src/index.ts (export), packages/core/src/__tests__/ingredient-ref.test.ts (new), spec/schema/recipegf-cocktail-v1.json (definitions.ingredient.properties.ref with pattern), python/src/recipegf/models.py (Ingredient.ref), packages/core/src/types.ts (Ingredient.ref), spec/conformance/manifest.yaml (+3 cases), spec/conformance/valid/ingredient-ref-portable.yaml (new), spec/conformance/invalid/ingredient-ref-versioned.yaml (new), spec/conformance/invalid/ingredient-ref-single-label.yaml (new), vendored copies via `npm run sync:spec`
- RED tests:
    - python/tests/test_ingredient_ref.py::test_pattern_matches_schema — INGREDIENT_REF_PATTERN == schema['definitions']['ingredient']['properties']['ref']['pattern']. FAILS: neither the module nor the schema property exists. This is the exact analogue of test_recipe_id.py::test_pattern_matches_schema.
    - python/tests/test_ingredient_ref.py::test_accepts_valid — parametrized: 'com.spiritolo/campari', 'com.example.recipegf/lime-juice', 'io.github.some-org/gin' all is_valid_ingredient_ref -> True.
    - python/tests/test_ingredient_ref.py::test_rejects_invalid — parametrized: 'spiritolo/gin' (single-label authority, not reverse-DNS), 'com.spiritolo/gin:v1' (carries :vN — that grammar is recipe-id, not ingredient-ref), 'com.spiritolo/Campari' (uppercase slug), 'com.spiritolo/' (empty slug), 'com.spiritolo//campari' (empty label), '' -> all False.
    - python/tests/test_ingredient_ref.py::test_parses_and_round_trips — parse_ingredient_ref('com.spiritolo/campari') == IngredientRef(authority='com.spiritolo', slug='campari'); format_ingredient_ref(parse(x)) == x; parse('spiritolo/gin') raises ValueError(match='Invalid ingredient ref').
    - Conformance valid/ingredient-ref-portable.yaml -> valid (an ingredient with ref: com.spiritolo/campari). FAILS in both langs today because definitions.ingredient has additionalProperties:false — the unknown 'ref' key is a schema violation until the property is added.
    - Conformance invalid/ingredient-ref-versioned.yaml -> invalid (ref: com.spiritolo/campari:v1 — rejected by the schema pattern).
    - Conformance invalid/ingredient-ref-single-label.yaml -> invalid (ref: spiritolo/gin — single-label authority rejected by the pattern). Both invalid cases parametrized in BOTH languages.
    - packages/core/src/__tests__/ingredient-ref.test.ts — TS mirror of the accept/reject/parse/round-trip cases PLUS `expect(schema.definitions.ingredient.properties.ref.pattern).toBe(INGREDIENT_REF_PATTERN)`.
- GREEN: ingredient_ref.py mirrors recipe_id.py verbatim in structure: INGREDIENT_REF_PATTERN = the recipe-id source with the ':v[1-9][0-9]*' tail removed => `^[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)+/[a-z0-9]+(?:-[a-z0-9]+)*$`; a frozen IngredientRef(authority, slug) dataclass; is_valid_ingredient_ref / parse_ingredient_ref / format_ingredient_ref. ingredient-ref.ts is the same in TS (export const string + RegExp + interface + fns), added to index.ts. Schema: add ref: {type:'string', pattern:<same source>, description:'Portable <authority>/<slug> ingredient identifier'} to definitions.ingredient.properties (optional; not in required). Because the pattern is enforced structurally by the schema, the versioned and single-label invalid cases need NO validator code-tier rule (schema short-circuit catches them) — do not add one. models.py Ingredient: `ref: str | None = None`; types.ts Ingredient: `ref?: string`. Run sync:spec. Note the reverse-DNS decision in the PR description so the owner ratifies rejecting bare 'spiritolo/...'.
- DONE:
    - ci.yml all three jobs green; conformance agrees both languages on the three new cases.
    - Both parity tests green (INGREDIENT_REF_PATTERN == schema ref.pattern in Python and TS) — the anti-drift guarantee.
    - sync:spec diff clean; schema const untouched.
    - Self-reviewed PR merged to main.
- YAGNI:
    - No ingredient-ref RESOLUTION or lookup in RecipeGF — grammar/parse/validate only. Resolution to a taxonomy node is Spiritolo-internal.
    - No ROLE or taxonomy vocabulary in the interface — ref carries only the portable identifier; role/meaning stay in Spiritolo's _x sidecar.
    - Do NOT relax the authority to single-label to match the shorthand 'spiritolo/x' in the architecture doc's examples — the grammar is recipe-id-minus-:vN (reverse-DNS), so Spiritolo emits 'com.spiritolo/<slug>'. Flag, don't silently widen.
    - No separate ingredient-ref schema file or $ref indirection — inline the pattern on definitions.ingredient.properties.ref, mirroring how id.pattern lives inline.

### WS-A3 — Standardize `modifiers` as `string[]` on steps AND ingredients  [recipegf]

> **RATIFIED UPDATE (supersedes the "freeform object" guidance in this block — see §3.2).**
> `modifiers` is an **array of freeform strings**, identical on `step` and
> `ingredient`. This means A3 also **flips the existing `step.modifiers` from
> object → array** (`{note:"x"}` → `["x"]`) across the schema, `models.py`,
> `types.ts`, `examples/*.yaml`, and conformance fixtures — a breaking change to a
> never-validated field, acceptable pre-release — plus adds the identical
> `ingredient.modifiers` array and updates Spiritolo's converter +
> `recipegf_steps.modifiers` to arrays (that Spiritolo change moves to A6/B1's
> pin-bump PR). RED tests assert both shapes are `string[]` and that an old
> object-form `modifiers` now fails validation. The block below is the original
> object-mirroring draft, kept for context only.

- depends_on: ['WS-A1', 'WS-A2']
- parallelism: serialize-after WS-A2 (shares spec/schema/recipegf-cocktail-v1.json, models.py, types.ts, manifest.yaml). Smallest of the three seams; purely declarative, no validator behavior.
- goal: An ingredient may carry an optional freeform modifiers object for human nuance, mirroring step.modifiers exactly (additionalProperties:true, never validated). Optional-additive; schema const unchanged.
- files: spec/schema/recipegf-cocktail-v1.json (definitions.ingredient.properties.modifiers), python/src/recipegf/models.py (Ingredient.modifiers), packages/core/src/types.ts (Ingredient.modifiers), spec/conformance/manifest.yaml (+1 case), spec/conformance/valid/ingredient-modifiers.yaml (new), python/tests/test_ingredient_modifiers.py (new), vendored copies via `npm run sync:spec`
- RED tests:
    - python/tests/test_ingredient_modifiers.py::test_schema_allows_modifiers_object — a doc whose ingredient has modifiers: {chilled: true, note: 'muddled'} validates .valid True. FAILS today: definitions.ingredient additionalProperties:false rejects the key.
    - python/tests/test_ingredient_modifiers.py::test_ingredient_model_modifiers — Ingredient.model_validate({'name':'campari','quantity':{'amount':1,'unit':'oz'},'modifiers':{'chilled':True}}).modifiers == {'chilled': True}; and Ingredient without modifiers -> .modifiers is None.
    - python/tests/test_ingredient_modifiers.py::test_modifiers_freeform_never_validated — arbitrary nested keys (e.g. {'x': {'y': [1,2]}}) still validate, proving additionalProperties:true parity with step.modifiers (which the schema documents as 'never validated').
    - Conformance valid/ingredient-modifiers.yaml -> valid (an ingredient carrying a modifiers object); parametrized in BOTH languages. FAILS in both until the property is added.
- GREEN: Schema: add modifiers: {type:'object', additionalProperties:true, description:'Optional freeform key-value pairs for human nuance (never validated)'} to definitions.ingredient.properties — copied verbatim from definitions.step.properties.modifiers so the two are literally the same shape. models.py Ingredient: `modifiers: dict[str, Any] | None = None` (matches Step.modifiers typing). types.ts Ingredient: `modifiers?: Record<string, unknown>` (matches Step). No validator code — like step.modifiers it is never validated. Run sync:spec.
- DONE:
    - ci.yml all three jobs green; conformance agrees both languages on the new case.
    - sync:spec diff clean; schema const untouched; no version bump here.
    - Self-reviewed PR merged to main.
- YAGNI:
    - Mirror step.modifiers as a freeform OBJECT — do NOT implement the ['chilled'] ARRAY shape from the architecture doc's _x example; that is not what step.modifiers is. Flag the inconsistency in the PR so the owner picks deliberately.
    - No fixed modifier vocabulary, no enum, no validation rule — 'never validated' is the whole point.
    - No cross-linking modifiers to steps or units.

### WS-A4 — Migrate Spiritolo's ~66-unit vocabulary into spec/registry/units (RecipeGF becomes sole unit authority)  [recipegf]
- depends_on: ['WS-A3']
- parallelism: parallel-safe with A1/A2/A3 on the registry YAML (disjoint from schema); serialize-after WS-A3 only for the spec/conformance/manifest.yaml append ordering. Overlap map: touches spec/registry/units/{bar,count}-units.yaml (new to this WS) + manifest.yaml (shared append).
- goal: RecipeGF's bar/count registries absorb Spiritolo's full unit vocabulary (surface aliases + canonical names + advisory approx_ml) so RecipeGF is the single unit authority. convert-units-backed standard tier stays generated and parity-green.
- files: spec/registry/units/bar-units.yaml (add imprecise bartending + volume/weight alias units), spec/registry/units/count-units.yaml (add form/shape count nouns), spec/conformance/manifest.yaml (+2 cases), spec/conformance/valid/units-bar.yaml (new), spec/conformance/valid/units-count.yaml (new), python/tests/test_units_migration.py (new), packages/core/src/__tests__/units-migration.test.ts (new), vendored copies via `npm run sync:spec`: packages/core/registry/units/*, python/src/recipegf/_spec/registry/units/*
- RED tests:
    - python/tests/test_units_migration.py::test_bar_units_valid — UnitValidator().is_valid(u) is True for each migrated imprecise unit: part, jigger, pony, shot, squeeze, grind, sprinkle, handful, knob, dropper, packet, package, swath, bottle, can, bag, bunch. FAILS until bar-units.yaml grows.
    - python/tests/test_units_migration.py::test_count_units_valid — is_valid True for: leaf, stick, clove, pod, bean, scoop, strip, stalk, sheet, disc, coin, quarter, chunk, ring, segment, spear, half, zest, peel, seed. FAILS until count-units.yaml grows.
    - python/tests/test_units_migration.py::test_surface_aliases_normalize — normalize('oz.')=='oz', normalize('ounce')=='oz', normalize('milliliter')=='ml', normalize('teaspoon')=='tsp' etc. — Spiritolo's surface spellings resolve, so the parser can delegate canonicalization (WS-A6).
    - python/tests/test_units_migration.py::test_translate_reproduced_via_normalize — normalize('tbsp')=='Tbs', normalize('pint')=='pnt', normalize('quart')=='qt', normalize('gallon')=='gal'. This reproduces Spiritolo's _UNIT_TRANSLATE inside RecipeGF so WS-A6 can delete that table and keep test_tbsp_unit_translated_to_recipegf_valid (expects 'Tbs') green.
    - python/tests/test_units_migration.py::test_approx_ml_exposed_for_dedup — get_approx_ml(u) is not None for oz, ml, cl, tsp, tbsp, dash, drop, splash — the set Spiritolo's dedup _OZ_PER_UNIT covers, so WS-A6 can retire it in favor of RecipeGF.
    - Conformance valid/units-bar.yaml -> valid and valid/units-count.yaml -> valid (recipes exercising a spread of migrated units), parametrized in BOTH languages. Because bar/count YAML is read by both UnitValidators, they go green together the moment the YAML lands + sync:spec runs.
    - packages/core/src/standard-units.test.ts stays green — a regression guard that this WS did NOT hand-edit the generated standard-units.yaml (both 'lists only convert-units-valid' and 'covers every convert-units abbr' must still pass).
    - packages/core/src/__tests__/units-migration.test.ts — TS mirror asserting new UnitValidator().isValid(u) for the same bar+count units and normalize('tbsp')==='Tbs'.
- GREEN: Edit spec/registry/units/bar-units.yaml: append imprecise bartending measures (part, jigger, pony, shot, squeeze, grind, sprinkle, handful, knob, dropper[aliases: dropperful], packet, package, swath, bottle, can, bag, bunch) each with name + Spiritolo plural/surface aliases + optional approx_ml where meaningful; and append volume/weight alias-carrier entries whose canonical name matches convert-units so normalize() reproduces the old translate map: name: Tbs {aliases:[tbsp, tablespoon, tbs, ...], approx_ml:15}, name: pnt {aliases:[pint, pints, pt]}, name: qt {aliases:[quart, quarts]}, name: gal {aliases:[gallon, gallons]}, plus registry entries carrying approx_ml for oz/ml/cl/tsp so get_approx_ml serves dedup (cl is not a convert-units abbr, so it must be a registry unit here). Edit count-units.yaml: append the form/shape nouns (leaf, stick, clove, pod, bean, scoop, strip, stalk, sheet, disc[aliases: disk], coin, quarter, chunk, ring, segment, spear, half[aliases: halves], zest, peel, seed) with surface aliases. Do NOT touch standard-units.yaml — it is generated from convert-units; the oz/ml/cup/tsp core spellings already validate via the standard tier. Run `npm run sync:spec` to vendor the updated registry into packages/core/registry and python/src/recipegf/_spec/registry. Reference docs/recipegf-export.md 'Unit coverage' worklist for the authoritative category mapping.
- DONE:
    - ci.yml all three jobs green: ts + python conformance agree on units-bar/units-count; standard-units.test.ts still green (generated snapshot untouched); spec-sync git-diff clean after sync:spec vendored the registry.
    - All ~66 Spiritolo parser-canonical units + their surface aliases are is_valid in both languages; the four translate-only spellings normalize to their convert-units canonical.
    - RecipeGF is now the sole unit authority (rolled into the v0.4.0 tag by WS-A5).
    - Self-reviewed PR merged to main.
- YAGNI:
    - Do NOT hand-edit the generated standard-units.yaml — convert-units remains the backing for standard metric/imperial units; only bar/count are hand-authored.
    - approx_ml is advisory (imprecise-measure heuristics only) — no unit-conversion engine, no exact ml math, no density modeling.
    - No sensory/stylistic/relative pseudo-units beyond what Spiritolo already had (e.g. 'part' migrates as a bar unit but no ratio-resolution logic ships).
    - No removal of convert-units as the standard-tier source; RecipeGF stays a superset, not a replacement, of convert-units.

### WS-A5 — Bump versions to 0.4.0, tag v0.4.0 release, reposition packages/parser as doc-only reference  [recipegf]
- depends_on: ['WS-A1', 'WS-A2', 'WS-A3', 'WS-A4']
- parallelism: serialize-after all of A1-A4 (must be merged to main first). Touches version files + docs only; no interface change.
- goal: Cut the RecipeGF v0.4.0 release rolling in A1-A4 (all optional-additive, schema const frozen), and demote the LLM parser package to a non-authoritative reference in docs. This tag is the gate that unblocks Tract B's doc-schema freeze.
- files: package.json (root, version 0.4.0), packages/core/package.json (version 0.4.0), python/pyproject.toml (version 0.4.0), python/tests/test_release_version.py (new — version parity guard), packages/parser/README.md (reposition note), README.md and/or docs/ (note parser is non-authoritative, low priority)
- RED tests:
    - python/tests/test_release_version.py::test_versions_agree_at_0_4_0 — reads root package.json, packages/core/package.json, python/pyproject.toml and asserts all three 'version' fields equal '0.4.0'. FAILS at 0.3.0; goes green only when all three are bumped in lockstep (guards against a partial bump).
    - python/tests/test_conformance.py (whole existing suite) — full regression gate: every prior fixture PLUS the A1-A4 additions must still be valid/invalid as declared, confirming the release is purely additive.
    - python/tests/test_recipe_id.py::test_pattern_matches_schema and test_ingredient_ref.py::test_pattern_matches_schema — both parity guards green at release, confirming no schema drift slipped in during the release commit.
- GREEN: Set version to 0.4.0 in the three manifests. Add packages/parser reposition prose (README + a line in docs) marking it a non-authoritative reference implementation, low priority — NO code change to the parser. After the release PR merges to main and CI is green, cut the tag per the runbook: from ~/code-projects/RecipeGF on main, run the cross-language green check `(cd python && uv run pytest) && npm test -w packages/core`, then `git tag -a v0.4.0 -m 'Ingredient seams (amount_max, modifiers, ref) + unit registry as sole authority'`, `git push origin v0.4.0`, `gh release create v0.4.0 --title v0.4.0 --notes 'Optional-additive; schema const stays recipegf/cocktail/v1.'`.
- DONE:
    - ci.yml all three jobs green on the release PR (ts, python, spec-sync).
    - test_release_version.py green (0.4.0 across all three manifests).
    - Tag v0.4.0 pushed and GitHub release created; schema const still recipegf/cocktail/v1 (no schema-version bump).
    - This tag existing is the explicit precondition Tract B's doc-schema workstream depends_on.
- YAGNI:
    - No rewrite, extraction, or deletion of packages/parser — repositioning is doc-only (a note, not a refactor).
    - No new schema-version const and no non-additive change — v0.4.0 is strictly additive over v0.3.0.
    - No changelog automation, no release-please, no semantic-release tooling — a single manual git tag + gh release per the runbook.
    - No pre-release/rc tags — cut v0.4.0 directly once CI is green.

### WS-A6 — Spiritolo: bump recipegf pin to v0.4.0 and retire local unit tables (_UNIT_TRANSLATE, _OZ_PER_UNIT, UNIT_ALIASES)  [spiritolo]
- depends_on: ['WS-A5 tagged v0.4.0']
- parallelism: serialize-after WS-A5 (needs the tag resolvable). Within Spiritolo, touches ingredients/src/ingredients/{recipegf/converter.py, dedup/role_classifier.py, units.py, parser.py} — serialize internally since units.py feeds parser.py; converter and role_classifier retirements are independently reviewable and can fan out to 2 agents (converter+_UNIT_TRANSLATE, dedup+_OZ_PER_UNIT) with the parser/UNIT_ALIASES change last.
- goal: Spiritolo consumes RecipeGF v0.4.0 as the sole unit authority: the converter, dedup role-classifier, and parser delegate unit knowledge to RecipeGF's UnitValidator and the three local unit tables are deleted, with existing converter/eval behavior held green.
- files: ingredients/pyproject.toml (recipegf tag v0.3.0 -> v0.4.0), uv.lock (uv lock --upgrade-package recipegf), ingredients/src/ingredients/recipegf/converter.py (delete _UNIT_TRANSLATE; _recipegf_unit uses _UNITS.normalize), ingredients/src/ingredients/dedup/role_classifier.py (delete _OZ_PER_UNIT; _to_oz uses UnitValidator.get_approx_ml), ingredients/src/ingredients/units.py (retire UNIT_ALIASES; canonicalize_unit delegates to RecipeGF), ingredients/src/ingredients/parser.py (bump PARSER_VERSION), ingredients/tests/test_recipegf_converter.py, ingredients/tests/test_units.py, ingredients/tests/test_rule_qty_unit.py, ingredients/tests/test_dedup_cluster.py (role oz-heuristic cases)
- RED tests:
    - ingredients/tests/test_recipegf_converter.py::test_tbsp_unit_translated_to_recipegf_valid — UNCHANGED assertion (units['rich-syrup'] == 'Tbs') but now satisfied via RecipeGF normalize after _UNIT_TRANSLATE is deleted. RED first: delete the local table and watch it fail until _recipegf_unit calls _UNITS.normalize.
    - ingredients/tests/test_recipegf_converter.py::test_previously_abstained_units_now_convert — units that used to route to Uncertain/unknown_unit (e.g. part, jigger, leaf, scoop, dropper) now produce a valid RecipeGF unit (no REASON_UNKNOWN_UNIT). FAILS against the v0.3.0 pin; passes only once the v0.4.0 registry (WS-A4) resolves them.
    - ingredients/tests/test_units.py::test_no_local_unit_tables — assert the module no longer defines _UNIT_TRANSLATE / _OZ_PER_UNIT / UNIT_ALIASES (import + getattr guard), so the retirement can't silently regress.
    - ingredients/tests/test_units.py::test_canonicalize_delegates_to_recipegf — canonicalize_unit('oz.')=='oz', canonicalize_unit('teaspoon')=='tsp' etc. now flow through RecipeGF's normalize, matching the pre-retirement outputs on a table-driven set of surface forms.
    - ingredients/tests/test_dedup_cluster.py::test_to_oz_uses_recipegf_approx_ml — _to_oz(2,'ml') and _to_oz(1,'dash') return the same oz values the role heuristics relied on, now sourced from UnitValidator.get_approx_ml. FAILS until _OZ_PER_UNIT is replaced.
    - ingredients/tests/test_rule_qty_unit.py (existing parser eval cases) — the full parser unit eval set stays green after UNIT_ALIASES is delegated to RecipeGF; per version-gate discipline the PARSER_VERSION bump commit also asserts a prior-version row re-queues under `--reset --except-version <old>` (test_reset re-queue case).
    - ingredients/tests/test_recipegf_converter.py — full converter eval/regression suite green against the v0.4.0 pin (no new abstains, no changed CONVERTER_VERSION output shape).
- GREEN: Edit ingredients/pyproject.toml [tool.uv.sources] recipegf tag 'v0.3.0' -> 'v0.4.0'; run `uv lock --upgrade-package recipegf`. converter.py: delete _UNIT_TRANSLATE; rewrite _recipegf_unit to return _UNITS.normalize(unit) if _UNITS.is_valid(unit) else None (RecipeGF now accepts the full vocab and normalize reproduces the tbsp->Tbs mapping). role_classifier.py: delete _OZ_PER_UNIT; rewrite _to_oz to derive oz from UnitValidator().get_approx_ml(unit) (ml -> oz via /29.5735), returning None when RecipeGF has no approx_ml (matching the old behavior for unhandled units). units.py: retire UNIT_ALIASES; canonicalize_unit / is_unit_alias delegate to a module-level UnitValidator().normalize/is_valid; keep the parser's COUNT_NOUN/INGREDIENT_COUNTABLES/BARE_INGREDIENT tables (those are ingredient-identity vocab, NOT units — out of scope). Because editing the parser's unit vocabulary is a parser-logic change, bump PARSER_VERSION in parser.py in the SAME commit as the pinning test. Confirm the pinned tag resolves and the suite is green: `cd ingredients && uv run --extra dev pytest`.
- DONE:
    - ingredients-ci.yml green on the PR (Postgres 16 service; TEST_DB_URL; uv run --extra dev pytest over ingredients/** + common/** + supabase/migrations/**).
    - The three local tables are gone (test_no_local_unit_tables green); converter/dedup/parser all source unit knowledge from RecipeGF.
    - test_tbsp_unit_translated_to_recipegf_valid still expects 'Tbs' and passes via normalize; previously-abstained units now convert.
    - PARSER_VERSION bumped; the --reset --except-version re-queue behavior asserted.
    - Separate Spiritolo PR to main (per CLAUDE.md workflow); recipegf pin now v0.4.0.
- YAGNI:
    - Do NOT migrate the parser's ingredient-identity tables (COUNT_NOUN_ALIASES, INGREDIENT_COUNTABLES, BARE_INGREDIENT_ALIASES) into RecipeGF — those are Spiritolo taxonomy/parse vocabulary, not units; only the three UNIT tables retire.
    - No new abstract unit-service layer in Spiritolo — call RecipeGF's UnitValidator directly at the two seams (converter, dedup) and the parser canonicalizer.
    - No re-parse/backfill of stored rows in this WS beyond the PARSER_VERSION re-queue mechanism — bulk re-runs follow the normal local-restore/upload flow, not this code PR.
    - Do not attempt exact volumetric conversion for relative units (part) — dedup keeps returning None there, exactly as _OZ_PER_UNIT did.




## 13. Workstreams — Tract B core · Content Model + Pipeline (B1–B14)

Fourteen RED-first workstreams covering the v2.1 content model + pipeline half of Tract B: the RecipeGF v0.4.0 pin bump that unblocks the doc-schema, the recipe_docs source-of-truth table, the spiritolo/recipe-doc/v1 doc-schema module (strip_x + parity), the unified stage_runs run-ledger with its NOT-EXISTS work queue and --reset, the TRUNCATE-and-rebuild projection family, the pages/R2 preserved-input surface, the config-not-code provider-chain library with request-packing and metered/free cost accounting, a generic stage-runner harness, the five smart stages (extract/parse/map/role-cluster/export) each a versioned stage_fn over a provider chain, and the clean-slate cold-build orchestration from {corpus, pages}. IDs B1–B14. Cross-half dependencies (the jobs/job_batches queue table + enqueue/approve RPCs, the audit_log trigger, and the /ops UI) are owned by the Infra-half and UI-half workstreams and are named as external deps where the pipeline touches them (WS-BX-jobs, WS-BX-audit); the stage-runner is deliberately designed to take a ScopeDescriptor so the smart stages are testable without the queue table. Every workstream reuses ingredients/tests/conftest.py's auto-migrate harness verbatim, injects deterministic fake providers (never a live model), and bumps the relevant *_VERSION constant in the same commit as the test that pins the new behavior.

### B1 — Bump RecipeGF pin to v0.4.0 and retire local unit tables  [spiritolo]
- depends_on: ['WS-A* tagged v0.4.0 (RecipeGF, external tract)']
- parallelism: 1 agent. Blocks B3/B8/B9/B13 (anything that imports the frozen ingredient shape or emits RecipeGF ingredient objects). Touches ingredients/pyproject.toml + uv.lock + the converter/parser unit sites — serialize any other pyproject edit after this.
- goal: Spiritolo consumes RecipeGF v0.4.0 (frozen ingredient shape: quantity.amount_max, ingredient.modifiers, ingredient.ref) and deletes its own unit-translation tables, so RecipeGF is the sole unit authority and the doc-schema can be frozen against the tagged interface.
- files: ingredients/pyproject.toml, uv.lock, ingredients/src/ingredients/recipegf/converter.py, ingredients/src/ingredients/parser.py, ingredients/tests/test_units.py, ingredients/tests/test_recipegf_converter.py
- RED tests:
    - test_units.py::test_local_unit_tables_removed — asserts ingredients.parser has no _UNIT_TRANSLATE / _OZ_PER_UNIT / UNIT_ALIASES attributes (getattr → AttributeError); fails while they still exist.
    - test_units.py::test_unit_resolution_uses_recipegf_registry — a table of ~10 representative units (oz, tbsp→'Tbs', dash, barspoon, count) resolves via recipegf's unit registry API and returns the pinned-tag canonical unit; fails on the old tag / local table.
    - test_recipegf_converter.py::test_tbsp_unit_translated_to_recipegf_valid — existing case still green post-bump (expects 'Tbs'); guards no regression.
    - test_recipegf_converter.py::test_ingredient_carries_amount_max_and_ref — converter emits an ingredient object with amount_max and a portable ref field per the v0.4.0 shape; fails on v0.3.0 models.
- GREEN: Edit [tool.uv.sources] recipegf tag v0.3.0 → v0.4.0; uv lock --upgrade-package recipegf. Replace every _UNIT_TRANSLATE/_OZ_PER_UNIT/UNIT_ALIASES lookup with the recipegf unit-registry lookup; delete the three module-level tables. Point converter ingredient emission at Quantity(amount_max=…) and Ingredient(ref=…, modifiers=…).
- DONE:
    - ingredients-ci.yml green with the new pin (RECIPEGF_TOKEN resolves the tag).
    - Full ingredients suite green against v0.4.0; no _UNIT_* symbols remain (grep clean).
    - PR to main; one-paragraph body noting the pin bump + unit-table retirement.
- YAGNI:
    - No re-authoring of the ~66-unit vocabulary in Spiritolo — it now lives in RecipeGF's registry; Spiritolo only consumes it.
    - No compatibility shim keeping the old tables importable for a deprecation window — clean slate, delete outright.

### B2 — recipe_docs base table + generated columns + GIN indexes + RLS + recipes_public view  [spiritolo]
- depends_on: []
- parallelism: 1 agent. serialize-after nothing (first new migration); B4/B5/B6 add later-timestamped migrations and read this table, so they serialize-after B2 for migrations-dir ordering. Web/taxonomy work is parallel-safe (disjoint files).
- goal: The source-of-truth content table recipe_docs (one RecipeGF-shaped JSONB doc per recipe) exists with its generated projection columns, containment/trgm indexes, deny-all RLS, and the public security_invoker view — the schema every later stage writes into.
- files: supabase/migrations/20260712_010000_recipe_docs.sql, ingredients/tests/test_recipe_docs_schema.py
- RED tests:
    - test_recipe_docs_schema.py::test_columns_and_types — information_schema.columns asserts id bigserial PK, source_url text NOT NULL, doc jsonb NOT NULL, doc_schema default 'spiritolo/recipe-doc/v1', state CHECK in (extracted,parsed,mapped,clustered,exported), updated_at. Fails: no migration.
    - test_recipe_docs_schema.py::test_source_url_unique — second INSERT with a duplicate source_url raises unique_violation.
    - test_recipe_docs_schema.py::test_generated_columns_track_doc — INSERT a doc with _x.site/_x.canonical_name/_x.cluster_key/_x.variant_key and title; assert the generated site/canonical_name/cluster_key/variant_key/title columns equal the doc paths; UPDATE the doc and assert the generated cols follow.
    - test_recipe_docs_schema.py::test_gin_and_trgm_indexes_exist — pg_indexes shows a gin(doc jsonb_path_ops) index plus trgm indexes on title/canonical_name; a @> containment query planner-uses the GIN (EXPLAIN contains the index name).
    - test_recipe_docs_schema.py::test_rls_denies_anon_direct_write — SET ROLE anon; INSERT raises insufficient_privilege; recipes_public SELECT as anon returns rows (view is security_invoker, granted select).
- GREEN: Migration: create table recipe_docs exactly per the foundation §1.1 (generated stored cols reading doc #>> paths, jsonb_path_ops GIN, gin_trgm_ops on title/canonical_name, state CHECK). enable row level security (deny-all, no policies). create view recipes_public with (security_invoker=true) selecting public-only fields incl. doc #> '{_x,source,jsonld}' as jsonld; grant select to anon, authenticated. Auto-picked up by the conftest migration applier.
- DONE:
    - ingredients-ci.yml Postgres service applies the migration; all shape/behavior/boundary tests green.
    - Projection invariant seeded: recipes_public exposes no _x internal field beyond the whitelisted jsonld path.
- YAGNI:
    - No content rows seeded — clean slate; the table starts empty and is filled by the extract stage.
    - No FK from recipe_docs to pages yet (open question deferred) — site is read from _x, not joined.
    - No recipe_variants materialized table — that stays a view in B5.

### B3 — spiritolo/recipe-doc/v1 doc-schema module: build_doc, strip_x, and RecipeGF parity  [spiritolo]
- depends_on: ['B1']
- parallelism: 1 agent. parallel-safe with B2/B4 (new module dir, no migration). Blocks B8–B13 (every stage merges into a doc via these helpers).
- goal: A pure Python module defining the internal doc superset — construct/merge helpers, the strip_x export projection, and a parity test proving strip_x(doc) validates against recipegf/cocktail/v1 — so the exported subset is byte-identical to the pin-2 recipe payload.
- files: ingredients/src/ingredients/docs/__init__.py, ingredients/src/ingredients/docs/schema.py, ingredients/src/ingredients/docs/strip_x.py, ingredients/tests/test_doc_schema.py, ingredients/tests/fixtures/docs/negroni_full.json
- RED tests:
    - test_doc_schema.py::test_strip_x_removes_only_sidecar — strip_x(doc) equals doc minus the top-level _x key, deep-equal on everything else; a doc with no _x round-trips unchanged.
    - test_doc_schema.py::test_strip_x_validates_against_recipegf — strip_x(negroni_full) passes recipegf's cocktail/v1 validator (imported from the pinned lib); a doc missing required RecipeGF fields fails the validator. Fails: no strip_x / no validation wiring.
    - test_doc_schema.py::test_doc_schema_name_not_in_doc — build_doc output has no 'doc_schema' key inside the doc (the name lives only in the DB column), so strip_x stays byte-identical to the export payload.
    - test_doc_schema.py::test_build_doc_partial_at_extract — build_doc(title, source_url, jsonld, origin) yields a valid partial doc with _x.source.jsonld + jsonld_origin and empty ingredients/steps, state-appropriate.
    - test_doc_schema.py::test_merge_stage_output_is_shallow_and_idempotent — merging a parse patch twice yields the same doc (idempotent UPSERT semantics), and _x sub-keys accrete without clobbering sibling _x keys.
- GREEN: schema.py: DOC_SCHEMA='spiritolo/recipe-doc/v1'; build_doc()/merge_x() helpers producing the three-layer shape (RecipeGF envelope + ref/modifiers/amount_max ingredient objects + _x sidecar). strip_x.py: strip_x(doc)=dict without '_x'; validate_exportable(doc) calls recipegf.validate on strip_x(doc). Pure functions, no DB.
- DONE:
    - Pure-Python tests green everywhere (uv sync only).
    - Parity invariant asserted: strip_x(doc) ⊨ recipegf/cocktail/v1 against the v0.4.0 pin.
    - ingredients-ci.yml green.
- YAGNI:
    - No jsonschema for the internal superset — RecipeGF validates the portable subset; _x is validated structurally only where a stage reads it.
    - No deep/path-based doc patching — shallow merge_x is enough until a nested-edit case appears.

### B4 — stage_runs run-ledger: schema, NOT-EXISTS work queue, latest-only UPSERT, --reset  [spiritolo]
- depends_on: ['B2']
- parallelism: 1 agent. serialize-after B2 (later migration + references pages/recipe_docs entity ids). parallel-safe with B3/B6. Blocks B8 (stage-runner reads/writes the ledger).
- goal: One polymorphic latest-only ledger (entity_type, entity_id, stage) generalizing every *_runs table, with the queue predicate 'qualifies AND NOT EXISTS run @ current version', an idempotent UPSERT writer, and --reset (with atomic cursor-column reset) that re-queues entities.
- files: supabase/migrations/20260712_020000_stage_runs.sql, ingredients/src/ingredients/pipeline/ledger.py, ingredients/tests/test_stage_runs.py
- RED tests:
    - test_stage_runs.py::test_schema_shape — information_schema asserts entity_type CHECK(page,recipe_doc), entity_id, stage, version, outcome CHECK(resolved,abstain,pending,failed,proposes_new), method CHECK(deterministic,llm,manual), confidence, model_id, cost_cents, error_code, batch_id, job_id, payload jsonb, started/finished_at; UNIQUE(entity_type,entity_id,stage). Fails: no migration.
    - test_stage_runs.py::test_upsert_is_latest_only — two record_run() calls for the same (recipe_doc, id, parse) leave exactly one row; the second's version/outcome win (ON CONFLICT DO UPDATE).
    - test_stage_runs.py::test_work_queue_not_exists_predicate — seed 3 recipe_docs, record parse@v1 on one; the queue query (state='extracted' AND NOT EXISTS parse@v1) returns exactly the two without a v1 run; a doc with parse@v0 re-appears.
    - test_stage_runs.py::test_reset_requeues_below_version — record parse@v1 and parse@v2 rows; reset(stage='parse', except_version='v2') deletes the v1-era row and re-queues its entity; the v2 row survives.
    - test_stage_runs.py::test_reset_nulls_gating_cursor_atomically — for a stage gated on a denorm cursor (classify→pages.content_type), reset deletes the run row AND nulls the cursor in one transaction; a mid-transaction failure leaves neither stranded.
- GREEN: Migration: stage_runs table per foundation §2 (unique key, queue index on (stage,version,entity_type), RLS admin-read). ledger.py: record_run() building the ON CONFLICT UPSERT; work_queue(stage, version, entity_type) returning the NOT-EXISTS SELECT; reset(stage, except_version, site, older_than) issuing the DELETE (+ cursor-null in the same tx where the stage declares a gating column).
- DONE:
    - ingredients-ci.yml green; latest-only, NOT-EXISTS, and reset invariants all asserted against TEST_DB_URL.
    - Ledger is prunable-derived: TRUNCATE stage_runs + re-run reproduces it (asserted by a truncate-then-requeue test).
- YAGNI:
    - No history rows — latest-only per (entity,stage); durable history is audit_log's job (external WS-BX-audit).
    - No FK-per-entity (page_id/recipe_doc_id) split — polymorphic (entity_type,entity_id) as decided; the two-FK alternative is a noted open question, not built.
    - No per-stage bespoke tables — one polymorphic ledger.

### B5 — Rebuildable projections + rebuild_projections(): recipe_doc_ingredients, recipe_clusters, recipe_variants view, project(doc) builders  [spiritolo]
- depends_on: ['B2', 'B3']
- parallelism: 1 agent. serialize-after B2 (later migration, references recipe_docs). parallel-safe with B4/B6. The cluster projection is populated by B12; here it is only the table + the pure builder + the rebuild fn skeleton.
- goal: The TRUNCATE-and-rebuild projection family — a flat ingredient search surface, the slug-keyed cluster materialization, the variant view, and one SQL rebuild_projections() entrypoint — each a pure project(doc) with no fact absent from the doc.
- files: supabase/migrations/20260712_030000_projections.sql, ingredients/src/ingredients/pipeline/projections.py, ingredients/tests/test_projections.py
- RED tests:
    - test_projections.py::test_recipe_doc_ingredients_shape — information_schema asserts (recipe_doc_id, position) PK, name/amount/amount_max/unit/taxonomy_slug/role cols, rdi_slug_idx + rdi_name_trgm. Fails: no migration.
    - test_projections.py::test_project_doc_ingredients_pure — project_ingredients(doc) yields one row per envelope ingredient with amount/unit from the ingredient object and taxonomy_slug/role from the parallel _x.ingredients_x[position]; a doc with no _x maps slug/role to NULL.
    - test_projections.py::test_recipe_clusters_pk_is_cluster_key — recipe_clusters PK is cluster_key text (not a serial); information_schema confirms the PK column type is text.
    - test_projections.py::test_rebuild_is_truncate_and_idempotent — populate recipe_doc_ingredients, mutate a doc, call rebuild_projections(); assert the projection now matches project(doc) for every doc and a second rebuild is byte-identical (no fact lives only in the projection).
    - test_projections.py::test_recipe_variants_is_view — recipe_variants appears in information_schema.views (not tables) and groups by (cluster_key, variant_key) with source_count = count(distinct site).
- GREEN: Migration: recipe_doc_ingredients + recipe_clusters (cluster_key text PK) tables, recipe_variants view, and public.rebuild_projections() SQL fn that TRUNCATEs each projection and re-INSERTs from recipe_docs via SQL mirroring the Python builders (idempotent by construction). projections.py: pure project_ingredients(doc) / project_cluster_rows(docs) used by tests and by the worker's post-stage rebuild.
- DONE:
    - ingredients-ci.yml green; the TRUNCATE-and-rebuild invariant asserted.
    - rebuild_projections() is the single deploy-time entrypoint the migrations CD job calls (per DevOps foundation §1).
- YAGNI:
    - No recipe_variants materialized table — a view until aggregation proves hot.
    - No search-ranking / tsvector column beyond trgm — substring search only, matching today's surface.
    - No incremental/dirty-flag projection maintenance — full TRUNCATE-and-rebuild is the whole story at this scale.

### B6 — Relocate pages into Postgres + R2 corpus reader  [spiritolo]
- depends_on: []
- parallelism: 1 agent. parallel-safe (new migration + new module; no overlap with B2–B5 files). The migration timestamp just needs to be unique. R2 reads use env creds; tests stub the S3 client.
- goal: The scraper pages table lives in the one Postgres holding only the lightweight per-URL row (url, site, r2_key=sha256(url), content_type, denylist, fetch_meta), and a corpus client reads gzipped HTML bytes from R2 by key — the two preserved clean-slate inputs.
- files: supabase/migrations/20260712_040000_pages.sql, ingredients/src/ingredients/pipeline/corpus.py, ingredients/tests/test_pages_schema.py, ingredients/tests/test_corpus_reader.py
- RED tests:
    - test_pages_schema.py::test_pages_columns — information_schema asserts url unique NOT NULL, site NOT NULL, r2_key nullable, content_type, denylist boolean default false, denylist_reason, fetch_status CHECK(ok,blocked,failed), fetch_meta jsonb, discovered_at, fetched_at; site/content/denylist indexes. Fails: no migration.
    - test_pages_schema.py::test_no_snapshot_or_attempts_columns — asserts the legacy pages_status_before / attempts / fetch_error columns do NOT exist (that history now lives in stage_runs/audit).
    - test_corpus_reader.py::test_key_is_sha256_of_url — corpus.key_for(url) == hashlib.sha256(url.encode()).hexdigest(); stable across calls.
    - test_corpus_reader.py::test_read_html_gunzips — with a stubbed S3 client returning gzipped bytes for key K, read_html(K) returns the decompressed HTML string; a missing key raises a typed CorpusMiss.
    - test_corpus_reader.py::test_reader_is_read_only — the module exposes no put/write/delete function (getattr → AttributeError); corpus is read-only after the one-time load.
- GREEN: Migration: pages table per foundation §1.4. corpus.py: key_for(url) sha256; a thin boto3/S3-compat client (endpoint+creds from R2_* env) with read_html(key) that GETs and gunzips; CorpusMiss on 404. Tests inject a fake S3 client via a constructor seam (no network).
- DONE:
    - ingredients-ci.yml green; pages shape + reader behavior asserted with a stubbed client (no live R2).
    - Reader is strictly read-only (no write surface).
- YAGNI:
    - No re-scrape / write-back path — R2 is object-locked write-once; the worker never re-fetches cached bytes.
    - No corpus loader in this WS — the one-time 16 GiB upload is an operator runbook step (DevOps foundation §4), not pipeline code.
    - No local-SQLite fallback for pages — clean slate into Postgres only.

### B7 — Config-not-code provider-chain library (deterministic|local|hosted, request-packing, metered/free, cost)  [spiritolo]
- depends_on: []
- parallelism: 1 agent. parallel-safe (new package under common/, builds on existing common/llm; no migration). Blocks B8 (the runner consumes the chain) and every smart stage. The config seam shape it defines is the single injection point the owner rewires and tests fake through.
- goal: A shared library where each smart stage is a rewireable chain of providers — deterministic/local(barbot)/openai/claude/deepseek — read from external config, that packs N items per LLM call, short-circuits when a tier resolves, reports per-item cost, and flags metered vs free, with a fake-provider seam for hermetic tests.
- files: common/src/common/providers/__init__.py, common/src/common/providers/chain.py, common/src/common/providers/config.py, common/src/common/providers/packing.py, common/src/common/providers/cost.py, common/src/common/providers/fake.py, common/tests/test_provider_chain.py, common/tests/test_request_packing.py
- RED tests:
    - test_provider_chain.py::test_chain_order_from_config — a stage config ['deterministic','local'] builds a chain that calls providers in that order; reordering the config reorders calls with no code change. Fails: no chain builder.
    - test_provider_chain.py::test_deterministic_short_circuits — when the deterministic tier resolves an item, the llm tier is never invoked (fake llm provider asserts zero calls); on abstain the next tier is reached.
    - test_provider_chain.py::test_stored_output_is_pinned — the chain returns the exact structured output the downstream stage will store/hash (what dedup keys off), independent of which tier produced it.
    - test_request_packing.py::test_packs_n_items_per_call — 25 items with pack_size=10 produce 3 fake-provider calls; outputs are re-mapped to inputs by id (order-independent).
    - test_request_packing.py::test_partial_failure_parks_right_items — a packed call where 2 of 10 items error parks exactly those 2 (pending_llm_tried-style) and resolves the other 8; re-run re-submits only the parked ones.
    - test_provider_chain.py::test_metered_flag_and_cost — a fake hosted provider reports cost_cents per call; the chain surfaces cumulative cost and marks the tier metered; deterministic/local tiers report zero cost and metered=false.
- GREEN: config.py: StageChainConfig loaded from a config file/row (stage → ordered provider ids + pack_size); providers resolved from a registry keyed by id. chain.py: run_chain(items, config, providers) iterating tiers, short-circuiting on resolve, aggregating ChainResult{resolved, parked, cost_cents, metered}. packing.py: chunk items, build one packed request per chunk, unpack by custom id, park failures. cost.py: per-provider unit-cost lookup → cost_cents. fake.py: FakeProvider(canned_map, cost_per_call, raises_for) implementing the existing LLMProvider Protocol.
- DONE:
    - Pure-Python tests green everywhere; no live model touched.
    - The config seam is the sole place provider/order/pack-size is set — asserted by the reorder-without-code-change test.
    - ingredients-ci.yml green (common/** is in the gate).
- YAGNI:
    - No provider/order stored in DB schema — the chain is external config the owner rewires.
    - No OpenAI async Batch path here — packed real-time is the core path; Batch survives only as the optional accelerator wired later, not in this library.
    - No retry-backoff curves or dead-letter queue — a failed item parks and re-queues; that's the whole retry story.
    - No live-LLM or VCR/cassette tests — fake providers only.

### B8 — Generic stage-runner harness: run_stage(scope) over a provider chain writing doc + stage_runs  [spiritolo]
- depends_on: ['B4', 'B7', 'B3']
- parallelism: 1 agent. serialize-after B4/B7 (imports ledger + chain). Blocks B9–B13 (each registers a stage_fn). Independent of the jobs table: run_stage takes a ScopeDescriptor; the infra-half worker's claim/dispatch calls it.
- goal: One reusable harness that, given a ScopeDescriptor and a stage's chain config, scans the NOT-EXISTS work queue, packs items through the provider chain, merges outputs into recipe_docs.doc, UPSERTs stage_runs idempotently, rolls up cost, and enforces a hard max_cost_cents — the spine every smart stage plugs a stage_fn into.
- files: ingredients/src/ingredients/pipeline/runner.py, ingredients/src/ingredients/pipeline/registry.py, ingredients/src/ingredients/pipeline/scope.py, ingredients/tests/test_stage_runner.py
- RED tests:
    - test_stage_runner.py::test_scope_kinds_resolve_to_entities — item/multiselect/filter(site,limit)/whole_queue ScopeDescriptors each resolve to the correct entity id set intersected with the NOT-EXISTS queue. Fails: no scope resolver.
    - test_stage_runner.py::test_runner_writes_doc_and_ledger — a fake stage_fn returning a doc patch causes run_stage to merge the patch into recipe_docs.doc AND UPSERT a stage_runs row (outcome/method/model_id/cost_cents) for each entity.
    - test_stage_runner.py::test_rerun_is_idempotent — running the same scope twice leaves one stage_run per entity and an unchanged doc (idempotent UPSERT; safe after a reaper requeue).
    - test_stage_runner.py::test_abstain_and_proposes_new_recorded — a stage_fn that abstains records outcome='abstain' and leaves the doc field unset; a proposes_new records that outcome without mutating content.
    - test_stage_runner.py::test_aborts_past_max_cost — a fake metered chain reporting cost per pack halts run_stage once cumulative cost_cents would exceed max_cost_cents; already-written entities keep their stage_runs (no double-count on requeue).
- GREEN: scope.py: ScopeDescriptor union + resolve_entities(scope, queue). registry.py: STAGE_FNS dict mapping stage name → stage_fn(entities, chain, ctx) → per-entity StageResult{doc_patch|None, outcome, method, model_id, cost_cents}. runner.py: run_stage(scope, version, chain_config, max_cost_cents) that resolves the queue, invokes the stage_fn with the built chain, merges doc patches (merge_x from B3), UPSERTs stage_runs (ledger from B4), accumulates cost, and raises/halts at the cap.
- DONE:
    - ingredients-ci.yml green; scope resolution, doc+ledger write, idempotency, and the hard cap all asserted with fake providers against TEST_DB_URL.
    - The registry is the single dispatch table the infra-half worker loop calls.
- YAGNI:
    - No job claiming / heartbeat / reaper here — that's the infra-half worker (WS-BX-jobs); run_stage takes a scope, not a job row.
    - No cross-stage scheduling/DAG execution — one stage per run_stage call; orchestration composes them (B14).
    - No confirm-before-cost UI — the harness only enforces the numeric cap it's handed.

### B9 — extract stage_fn — [mechanical JSON-LD → LLM] into partial recipe_docs  [spiritolo]
- depends_on: ['B2', 'B3', 'B4', 'B6', 'B7', 'B8']
- parallelism: 1 agent. serialize-after B8 (registers into the registry) + B6 (reads corpus). parallel-safe with B10–B13 in code (separate stage module) but functionally upstream of them. EXTRACTOR_VERSION lives here.
- goal: The extract stage turns corpus HTML into a partial recipe_doc: a deterministic Schema.org Recipe JSON-LD parse when present (stored verbatim), else an LLM extractor synthesizing the JSON-LD (origin='synthesized'); both write title/ingredients skeleton + _x.source.jsonld and advance state to 'extracted'.
- files: ingredients/src/ingredients/pipeline/stages/extract.py, ingredients/src/ingredients/pipeline/stages/version.py, ingredients/tests/test_stage_extract.py, ingredients/tests/fixtures/corpus/with_jsonld.html, ingredients/tests/fixtures/corpus/no_jsonld.html
- RED tests:
    - test_stage_extract.py::test_mechanical_jsonld_stored_verbatim — extract on with_jsonld.html parses the Recipe JSON-LD deterministically, builds a doc whose _x.source.jsonld equals the page's JSON-LD byte-for-byte and jsonld_origin='verbatim'; method='deterministic', llm tier never called.
    - test_stage_extract.py::test_llm_synthesizes_when_absent — no_jsonld.html has no Recipe JSON-LD, so the deterministic tier abstains and the fake LLM extractor returns synthesized JSON-LD; doc _x.source.jsonld_origin='synthesized', method='llm'.
    - test_stage_extract.py::test_partial_doc_shape — the produced doc validates as a partial spiritolo/recipe-doc/v1 (title + ingredient names present, quantities may be null pre-parse) and state cursor sets to 'extracted'.
    - test_stage_extract.py::test_version_bump_requeues — with EXTRACTOR_VERSION bumped, a doc carrying an extract@prior stage_run re-appears in the queue under reset --except-version; the test pins both the new output and the requeue.
    - test_stage_extract.py::test_non_recipe_page_abstains — a page whose JSON-LD is Article (not Recipe) records outcome='abstain', no recipe_doc created.
- GREEN: extract.py: deterministic tier = the existing scraper JSON-LD Recipe parser adapted to emit a doc via docs.build_doc; llm tier = an LLM extractor prompt returning Recipe-shaped JSON. Register stage_fn 'extract' in the registry; on resolve, insert recipe_docs (source_url from pages.url) with the partial doc and _x.source. version.py: EXTRACTOR_VERSION.
- DONE:
    - ingredients-ci.yml green; verbatim/synthesized split, partial-doc validity, and version-requeue asserted with fake providers + fixture HTML.
    - EXTRACTOR_VERSION bumped in the same commit as any logic change per version-gate discipline.
- YAGNI:
    - No re-fetch — extract reads only stored corpus bytes via B6.
    - No multi-recipe-per-page fan-out beyond what JSON-LD lists — one primary Recipe per page.
    - No unstructured-body-text extractor — likely_unstructured_drink_recipe stays a manual-only future path.

### B10 — parse stage_fn — [deterministic parser → LLM] fills ingredient quantities  [spiritolo]
- depends_on: ['B8', 'B9', 'B7', 'B1']
- parallelism: 1 agent. serialize-after B9 (consumes extract output) + B1 (RecipeGF unit registry). Reuses the existing parser.py rules. PARSER_VERSION lives here (moved onto the doc-writing path).
- goal: The parse stage fills each envelope ingredient's quantity (amount/amount_max/unit) and name via the deterministic parser, routing over-matches/uncertain strings to the LLM tier with strict abstain discipline; output is the stored shape dedup later hashes.
- files: ingredients/src/ingredients/pipeline/stages/parse.py, ingredients/src/ingredients/parser.py, ingredients/tests/test_stage_parse.py
- RED tests:
    - test_stage_parse.py::test_deterministic_parses_clean_ingredient — '1 1/2 oz gin' resolves via the deterministic tier to quantity{amount:1.5, unit:'oz'}, name 'gin'; llm tier not called; envelope ingredient object updated in place at its position.
    - test_stage_parse.py::test_llm_tier_on_deterministic_abstain — a messy string the deterministic parser abstains on routes to the fake LLM parser; the stored quantity is what the test pins (method='llm').
    - test_stage_parse.py::test_amount_max_range_parsed — '2 to 3 dashes' yields amount:2, amount_max:3 (amount_max ≥ amount per the RecipeGF validator rule); a single amount leaves amount_max null.
    - test_stage_parse.py::test_abstain_leaves_quantity_null_not_guessed — an untranslatable unit records outcome='abstain' and leaves quantity null rather than fabricating one; state does not advance to 'parsed' for that doc if any required item is unresolved (per stage policy).
    - test_stage_parse.py::test_parser_version_bump_requeues — bumping PARSER_VERSION re-queues prior-version docs under reset --except-version; both new output and requeue pinned.
- GREEN: parse.py: stage_fn 'parse' running build_rows_for_recipe-style deterministic parsing over doc ingredients, mapping results into the envelope ingredient quantity objects; abstains route to the LLM tier via the chain. Advance state → 'parsed'. Keep PARSER_VERSION on every stage_run. Reuse existing rule modules; unit resolution via RecipeGF registry (B1).
- DONE:
    - ingredients-ci.yml green; deterministic/LLM split, amount_max range, strict abstain, and version-requeue asserted.
    - Stored parse output is stable (the dedup input) — asserted independent of tier.
- YAGNI:
    - No new parser rules invented here — this WS ports the existing rule set onto the doc-writing path; new patterns are separate RED cases in eval_set.
    - No inference of missing units — abstain, never guess.
    - No re-parse of _x.source.jsonld raw text — parse operates on the envelope ingredient strings extract produced.

### B11 — map stage_fn — [alias/lexical → LLM] resolves ingredient taxonomy_slug + role  [spiritolo]
- depends_on: ['B8', 'B10', 'B7']
- parallelism: 1 agent. serialize-after B10 (consumes parsed ingredients). Reuses mapping/{alias_layer,lexical_layer,llm_resolver,proposals}. Needs the taxonomy_* reference tables (carried forward) + fixture_taxonomy fixture. MAPPER_VERSION lives here.
- goal: The map stage resolves each ingredient to a taxonomy node by SLUG (alias + lexical deterministically, LLM for residual), writing _x.ingredients_x[].taxonomy_slug + role, auto-creating brand/expression nodes and queueing form proposals — slugs, never PKs, so a node renumber never touches a doc.
- files: ingredients/src/ingredients/pipeline/stages/map.py, ingredients/tests/test_stage_map.py
- RED tests:
    - test_stage_map.py::test_alias_hit_writes_slug — 'Campari' resolves via the alias layer to _x.ingredients_x[i].taxonomy_slug='campari', mapper_method='alias'; llm tier not called.
    - test_stage_map.py::test_lexical_then_llm_fallthrough — a name the alias layer misses hits lexical; a name both miss routes to the fake LLM resolver (method='llm'); the stored slug is pinned.
    - test_stage_map.py::test_slug_is_authoritative_pk_is_mirror — the doc stores taxonomy_slug (stable); renumbering the fixture node's PK leaves the doc/_x unchanged and re-map produces the same slug.
    - test_stage_map.py::test_llm_proposes_form_queues_proposal — a resolver 'propose_form' outcome writes a taxonomy_proposals row (kebab proposed_slug CHECK) and records stage_run outcome='proposes_new'; no node auto-created.
    - test_stage_map.py::test_brand_auto_create_records_provenance — a 'propose_brand' with an existing parent auto-creates a brand node (is_cluster_node=false) and writes taxonomy_provenance; the doc slug points at it.
    - test_stage_map.py::test_mapper_version_bump_requeues — bumping MAPPER_VERSION re-queues prior-version docs under reset --except-version.
- GREEN: map.py: stage_fn 'map' running alias_layer → lexical_layer deterministically, residual through the LLM tier (llm_resolver) via the chain; write _x.ingredients_x parallel array (position, taxonomy_slug, taxonomy_node_id mirror, mapper_method, role from node.default_role). Auto-create brand/expression on existing-parent proposals; queue form proposals. Advance state → 'mapped'. MAPPER_VERSION on stage_runs.
- DONE:
    - ingredients-ci.yml green (needs fixture_taxonomy); alias/lexical/LLM tiers, slug-authoritative invariant, proposal queueing, and version-requeue asserted.
    - Auto-created nodes default is_cluster_node=false (antichain stays curator-controlled).
- YAGNI:
    - No new taxonomy nodes for sensory/stylistic concepts — the lean taxonomy stance holds.
    - No form-node auto-approval — form proposals are human-review only.
    - No vector-similarity layer — alias/lexical/LLM by slug only.

### B12 — role/cluster stage_fn — pure dedup hashing taxonomy slugs into cluster_key/variant_key  [spiritolo]
- depends_on: ['B8', 'B11', 'B5']
- parallelism: 1 agent. serialize-after B11 (consumes mapped slugs/roles) + B5 (writes the recipe_clusters projection). The cluster_key hashing spec is pinned here under NORMALIZER_VERSION/DEDUP_VERSION. Reuses dedup/{rollup,role_classifier,cluster,normalize}.
- goal: The role/cluster stage tags substance roles, rolls the ingredient set up to a curated antichain, and computes cluster_key = hash(canonical_name, slug antichain) and variant_key = +amounts/brand call-outs — pure functions over slugs written into _x, then materialized into recipe_clusters.
- files: ingredients/src/ingredients/pipeline/stages/role_cluster.py, ingredients/src/ingredients/dedup/version.py, ingredients/src/ingredients/dedup/cluster.py, ingredients/tests/test_stage_role_cluster.py
- RED tests:
    - test_stage_role_cluster.py::test_cluster_key_is_pure_slug_hash — cluster_key(canonical_name, slug_antichain) is deterministic and depends only on the canonical name + sorted slug set; the SAME inputs across two runs give the SAME key; changing a node PK does not change the key.
    - test_stage_role_cluster.py::test_canonicalization_is_versioned — the hash input canonicalization (sort order, casing, role filter) is fixed by DEDUP_VERSION; a documented spec test asserts a golden key for a golden input so a hash-function change is a deliberate bump, not silent drift.
    - test_stage_role_cluster.py::test_variant_key_adds_amounts_and_brands — two docs with the same cluster_key but different amounts get different variant_keys; identical recipes from two sites collapse to one variant (source_count=2).
    - test_stage_role_cluster.py::test_roles_tagged_and_rolled_to_antichain — modifier/base/etc. roles are set and ingredients roll up to the curated antichain (no is_cluster_node ancestor of an is_cluster_node node); non-included roles are excluded from the key.
    - test_stage_role_cluster.py::test_cluster_projection_materialized — after the stage, rebuild_projections()/the stage writes recipe_clusters rows keyed by cluster_key with recipe_count/source_count; a re-run is idempotent.
    - test_stage_role_cluster.py::test_dedup_version_bump_requeues — bumping DEDUP_VERSION re-queues prior-version docs under reset --except-version.
- GREEN: role_cluster.py: stage_fn 'role' (role_classifier over _x.ingredients_x) then 'cluster' compute — deterministic, no LLM tier (name normalization LLM already happened upstream/at map). cluster.py: canonical hashing with a pinned spec (sorted lowercased slug antichain + canonical_name → sha256), variant hashing (+amounts+brand refs). Write _x.cluster_key/variant_key; advance state → 'clustered'; upsert recipe_clusters. Bump NORMALIZER_VERSION/DEDUP_VERSION on rule/shape change.
- DONE:
    - ingredients-ci.yml green (fixture taxonomy); pure-slug-hash, versioned canonicalization golden, variant split, antichain rollup, and idempotent materialization asserted.
    - cluster_key stability across PK renumber asserted — the load-bearing architecture rule.
- YAGNI:
    - No automated cluster remediation — audit signals are operator-triaged, not auto-fixed.
    - No cross-cluster merge UI here — cluster identity is a pure function; curation is separate.
    - No re-hash on unrelated doc edits — only a version bump re-keys.

### B13 — export stage_fn — generate pin-2 bundle on demand, mint com.spiritolo/<slug>:v1, byte-equivalence  [spiritolo]
- depends_on: ['B3', 'B12', 'B1']
- parallelism: 1 agent. serialize-after B12 (consumes clustered docs) + B3 (strip_x). Reuses recipegf/{bundle,converter,slug,verbs,proposals,version}. CONVERTER_VERSION lives here. Drops the recipegf_recipes/_ingredients/_steps trio (clean slate).
- goal: The export stage mints the reverse-DNS recipe id com.spiritolo/<slug>:v1, generates the pin-2 bundle {recipe:strip_x(doc), verbs, meta} on demand from the doc, and proves byte-equivalence between strip_x(doc) and the bundle's recipe payload — with uncertain conversions routed to recipegf_proposals.
- files: ingredients/src/ingredients/pipeline/stages/export.py, ingredients/src/ingredients/recipegf/bundle.py, ingredients/src/ingredients/recipegf/version.py, ingredients/tests/test_stage_export.py, supabase/migrations/20260712_050000_drop_recipegf_relational_trio.sql
- RED tests:
    - test_stage_export.py::test_recipe_id_is_reverse_dns — a Negroni doc mints id 'com.spiritolo/negroni:v1'; a bare 'spiritolo/negroni' id is rejected (spiritolo namespace is verbs-only); meta.slug == parse_recipe_id(id).slug.
    - test_stage_export.py::test_bundle_is_generated_on_demand — generate_bundle(doc) returns {recipe, verbs:[spiritolo/ defs used], meta}; no bundle blob is stored; the migration test confirms recipegf_recipes/_ingredients/_steps tables no longer exist.
    - test_stage_export.py::test_bundle_recipe_is_byte_equivalent_to_strip_x — json.dumps(bundle['recipe'], sort_keys) == json.dumps(strip_x(doc), sort_keys); the exported subset is byte-identical to the internal portable subset.
    - test_stage_export.py::test_selfcontained_verbs — a doc whose steps reference spiritolo/blend carries that verb-def in bundle.verbs so a consumer validates against core ∪ spiritolo/ with no external lookup.
    - test_stage_export.py::test_uncertain_routes_to_proposal — a doc the deterministic converter can't translate (muddle/no technique) records outcome='proposes_new', writes a recipegf_proposals row, and parks at CONVERTER_VERSION (no bundle).
    - test_stage_export.py::test_converter_version_bump_requeues — bumping CONVERTER_VERSION re-queues prior-version docs under reset --except-version.
- GREEN: export.py: stage_fn 'export' — mint id via slug.mint (RECIPE_AUTHORITY 'com.spiritolo', :vN encoding), run the deterministic converter (technique scan → step template) over the doc, on success mark state → 'exported' and expose generate_bundle(doc)=strip_x(doc)+verbs+meta; on uncertainty write recipegf_proposals and record proposes_new. Migration: drop the relational trio. CONVERTER_VERSION on stage_runs.
- DONE:
    - ingredients-ci.yml green; reverse-DNS minting, generate-on-demand, byte-equivalence, self-contained verbs, proposal routing, and version-requeue asserted.
    - Relational trio dropped; bundles are never stored — asserted by the migration + on-demand tests.
- YAGNI:
    - No stored bundle blobs and no recipegf_recipes/_ingredients/_steps — generate-on-demand only.
    - No RecipeGF PR per new extension verb — verbs iterate in-repo as self-describing YAML (D2b).
    - No non-deterministic converter — anything uncertain routes to human review, never guessed.

### B14 — Clean-slate cold-build orchestration from {corpus, pages} + end-to-end integration test  [spiritolo]
- depends_on: ['B6', 'B8', 'B9', 'B10', 'B11', 'B12', 'B13']
- parallelism: 1 agent. serialize-after all stage workstreams (composes them). Cross-half: the operator triggers each stage via the infra-half jobs queue (WS-BX-jobs) + /ops UI; this WS provides the ordered stage list + a CLI/e2e harness that can run the DAG headless for the cold build and for CI.
- goal: One orchestration entrypoint that rebuilds all content cold from the two preserved inputs — driving discover→classify→fetch→extract→parse→map→role/cluster→export via the stage registry — plus a runbook and a tiny-fixture end-to-end test proving a page becomes an exportable bundle with the full stage_runs trail.
- files: ingredients/src/ingredients/pipeline/coldbuild.py, ingredients/src/ingredients/pipeline/cli.py, docs/cold-build.md, ingredients/tests/test_coldbuild_e2e.py, ingredients/tests/fixtures/corpus/e2e_negroni.html
- RED tests:
    - test_coldbuild_e2e.py::test_full_dag_one_page_to_bundle — seed one pages row + its e2e_negroni.html in the stubbed corpus; run the ordered stages (extract→parse→map→role/cluster→export) headless with deterministic tiers; assert a recipe_doc reaches state='exported', generate_bundle yields com.spiritolo/negroni:v1, and one stage_run per stage exists. Fails: no orchestrator.
    - test_coldbuild_e2e.py::test_stage_order_and_gating — running the DAG in order advances each doc through the state cursor; running a downstream stage before its upstream leaves the doc un-advanced (queue gating holds).
    - test_coldbuild_e2e.py::test_cold_build_is_reproducible — TRUNCATE recipe_docs + stage_runs + projections, re-run the DAG from {corpus,pages}; the resulting docs, cluster_keys, and bundle are byte-identical to the first build (clean-slate reproducibility).
    - test_coldbuild_e2e.py::test_reset_and_rerun_single_stage — reset one stage (e.g. map --except-version none) re-queues only that stage's docs and re-runs it without touching upstream stage_runs.
    - test_coldbuild_e2e.py::test_projections_rebuilt_after_dag — after the DAG, rebuild_projections() leaves recipe_doc_ingredients + recipe_clusters consistent with the docs (no fact only in a projection).
- GREEN: coldbuild.py: STAGE_ORDER list + run_cold_build(scope) iterating stages in order via run_stage (B8), calling rebuild_projections() at the end. cli.py: `python -m ingredients.pipeline` subcommands per stage + `cold-build` (thin wrappers over run_stage with a whole_queue scope; deterministic chain config for CI). docs/cold-build.md: the operator runbook (restore pages, point corpus at R2, run each stage from /ops or CLI, order, reset semantics).
- DONE:
    - ingredients-ci.yml green; the one-page e2e, ordering/gating, reproducibility, single-stage reset, and projection-consistency all asserted with deterministic tiers (no live model, stubbed corpus).
    - docs/cold-build.md merged as the clean-slate rebuild runbook.
    - The stage order is defined once (STAGE_ORDER) and reused by CLI + the infra-half worker dispatch.
- YAGNI:
    - No automated scheduling/cron — the cold build is operator-triggered stage-by-stage; coldbuild.py's headless runner exists for CI and for a deliberate full run, not a background job.
    - No parallel multi-stage execution engine — stages run in order; SKIP LOCKED handles intra-stage concurrency in the infra-half worker.
    - No discover/fetch re-scrape in the e2e — the cold build starts from the preserved corpus + pages; fetch/ScraperAPI is exercised only in the live 1-URL smoke (DevOps runbook §8), not this deterministic test.




## 14. Workstreams — Tract B platform · Queue/Worker/Audit/UI/DevOps (B20–B33)

Fourteen RED-first workstreams delivering everything around the content model: (1) corpus→R2 + pages fold-in [B20]; (2) DevOps CD + runbook [B21]; (3) jobs/job_batches schema + enqueue/approve/claim/reap RPCs [B22]; (4) the worker daemon claim loop + provider-chain seam [B23]; (5) OpenAI batch boot-reconciliation [B24]; (6) Tailscale-userspace Dockerfile/entrypoint + local-provider proxy client [B25]; (7) audit.log generic trigger + actor-context wiring [B26]; (8) form-kit token extraction + shared hooks [B27]; (9) shared UI primitives [B28]; (10) OpsLayout + routes + stage_queue_counts view + dashboard [B29]; (11) the seven DB browsers composed from the kit [B30]; (12) TriggerBar + CostConfirmModal + stage_config metering [B31]; (13) review/edit-after-batch edit_recipe_doc RPC→audit loop [B32]; (14) sign-corpus-url Edge Function + sandboxed corpus iframe [B33]. Every workstream: RED tests first (pytest against TEST_DB_URL for DB/RPC/worker via the reused ingredients auto-migrate conftest; Vitest + @testing-library with mocked supabase for UI), then minimal GREEN, then CI-green DONE. Cross-cutting invariants pinned by tests: SKIP-LOCKED contention safety, idempotent-UPSERT-so-reaper-is-safe, actor_kind falls out of auth.uid()/app.job_id, one FilterBar object feeds both usePagedQuery and enqueue_job, and every human edit routes RPC→content+audit(actor=human). Depends on the data-model half for recipe_docs/stage_runs schema and on Tract A tagged v0.4.0 only where the doc-schema/bundle shape is touched (B24/B30 exports). Ordering backbone: B22→B23/B24/B25 (queue before worker); B26 parallel; B27→B28→B29→B30/B31/B32→B33 (tokens→primitives→shell→views).

### WS-B20 — pages table migration + corpus→R2 loader (gzip, sha256 keys) + pages.r2_key backfill  [spiritolo]
- depends_on: []
- parallelism: parallel-safe. Owns a fresh migration file + a new scripts/corpus loader module; touches no file the data-model or UI half touches. R2 bucket creation is out-of-band CLI (runbook in WS-B21), not code, so no ordering dep on B21.
- goal: The 16 GiB HTML corpus lands read-only in a versioned, object-locked R2 bucket keyed sha256(url); the lightweight pages row (url, site, r2_key, denylist, fetch_meta) lives in the one Supabase Postgres. These are the two preserved clean-slate inputs.
- files: supabase/migrations/20260715090000_pages.sql, scripts/src/corpus_loader/__init__.py, scripts/src/corpus_loader/keys.py, scripts/src/corpus_loader/load.py, scripts/src/corpus_loader/backfill_pages.py, scripts/tests/test_corpus_keys.py, scripts/tests/test_corpus_loader.py, ingredients/tests/test_pages_migration.py
- RED tests:
    - test_corpus_keys.py::test_key_is_sha256_of_url — key('https://a/b') == hashlib.sha256(b'https://a/b').hexdigest(); 64 lowercase hex chars. Fails: no module.
    - test_corpus_keys.py::test_key_stable_across_calls — same url twice → identical key (content-addressed immutability contract).
    - test_corpus_keys.py::test_key_url_sensitive — trailing-slash / scheme differences yield different keys (no silent canonicalization; caller owns url normalization).
    - test_corpus_loader.py::test_object_body_is_gzip — load() feeds a fake S3 client (captures put_object kwargs); assert Body is valid gzip that decompresses to the original HTML bytes.
    - test_corpus_loader.py::test_object_metadata — put_object called with Key==sha256(url), ContentType='text/html', ContentEncoding='gzip', Metadata={'url': url}.
    - test_corpus_loader.py::test_skip_existing_key — fake client head_object returns 200 → load() does NOT re-put (write-once corpus, idempotent re-run).
    - test_corpus_loader.py::test_no_delete_or_overwrite_calls — the loader never calls delete_object or put with an existing differing body (object-lock respect).
    - test_pages_migration.py::test_schema_shape — information_schema asserts columns url(unique,not null), site(not null), r2_key(nullable), content_type, denylist(bool default false), denylist_reason, fetch_status CHECK in (ok,blocked,failed), fetch_meta jsonb, discovered_at, fetched_at; indexes pages_site_idx, pages_content_idx, partial pages_denylist_idx. Fails: no migration.
    - test_pages_migration.py::test_url_unique_constraint — inserting two rows with same url raises unique_violation.
    - test_pages_migration.py::test_rls_deny_all — RLS enabled; SET ROLE anon cannot select or insert (write only via service role / RPC).
    - test_corpus_loader.py::test_backfill_pages_sets_r2_key — backfill_pages over a fake DB sets pages.r2_key = key(url) for every row and leaves other columns untouched.
- GREEN: keys.py: sha256_key(url) -> hexdigest. load.py: iterate a pre-staged html cache dir, gzip -9 each file in-memory, head_object to skip existing keys, put_object with the S3-compat R2 client (boto3, endpoint from R2_* env). backfill_pages.py: UPDATE pages SET r2_key=... WHERE r2_key IS NULL. Migration: create table pages (per FOUNDATION §1.4) + indexes + enable RLS deny-all. Loader is a scripts-package module (spiritolo-scripts), run once operationally; keep it pure/injectable (S3 client + fs passed in) so tests need no network.
- DONE:
    - ingredients-ci.yml green: the new migration auto-applies in the Postgres service and test_pages_migration.py passes.
    - scripts suite green for the loader/key tests (pure, no TEST_DB_URL needed for keys/loader; backfill uses the scripts two-DB conftest or a fake DB).
    - Migration is forward-applyable (picked up by deploy-migrations validate job from WS-B21).
    - Invariant asserted: key == sha256(url), gzip round-trips, write-once (no overwrite/delete path).
- YAGNI:
    - No re-scrape / re-fetch path — corpus is write-once, read-only after the one-time load; the worker never re-writes bytes.
    - No URL canonicalization inside the key function — caller passes the exact url; a normalization layer is a separate concern if ever needed.
    - No R2 lifecycle/expiry rules, no multi-bucket sharding, no CDN in front — one bucket, no egress fee.
    - No snapshot/attempts/fetch_error bookkeeping columns on pages — that history lives in stage_runs.payload / audit_log.

### WS-B21 — DevOps CD: migrations validate-gate + Railway worker deploy + web Vitest CI + Vercel env + setup runbook doc  [spiritolo]
- depends_on: ['WS-B20 (pages migration exists to validate)']
- parallelism: parallel-safe with all code workstreams (only edits CI YAML, Dockerfile, railway.json, docs). Coordinates with WS-B25 which authors worker.Dockerfile + worker-entrypoint.sh — B21 references them but B25 owns their content; split so B21 can land the workflow before the Dockerfile is final by gating deploy-worker on their existence.
- goal: Push-to-staging deploys migrations (+ rebuild_projections) and the worker to Railway; PR-to-main forward-applies migrations on a throwaway Postgres and runs the web Vitest suite; a committed runbook takes an operator from zero to a running loop.
- files: .github/workflows/deploy-migrations.yml, .github/workflows/deploy-worker.yml, .github/workflows/web-ci.yml, railway.json, supabase/migrations/20260715091000_rebuild_projections_fn.sql, docs/devops-runbook.md, docs/deployment.md, .github/workflows/tests/test_workflow_shapes.py
- RED tests:
    - test_workflow_shapes.py::test_deploy_migrations_has_validate_job — parse deploy-migrations.yml; assert a job triggered on pull_request:[main] paths supabase/migrations/** that runs a postgres:16 service and forward-applies every supabase/migrations/*.sql with ON_ERROR_STOP. Fails: job absent.
    - test_workflow_shapes.py::test_staging_job_runs_rebuild_projections — the push:[staging] job runs `supabase db push` then `psql -c 'select public.rebuild_projections();'`.
    - test_workflow_shapes.py::test_web_ci_runs_vitest — web-ci.yml triggers on web/** PRs and runs `npm test` (vitest run) in web/. (Closes the open item: this workstream owns wiring the web CI gate.)
    - test_workflow_shapes.py::test_deploy_worker_paths — deploy-worker.yml triggers on staging pushes touching ingredients/**, common/**, worker.Dockerfile, scripts/worker-entrypoint.sh, railway.json, uv.lock and runs `railway up --ci`.
    - test_workflow_shapes.py::test_railway_json_dockerfile_builder — railway.json build.builder=='DOCKERFILE', dockerfilePath=='worker.Dockerfile', deploy.numReplicas==1, restartPolicyType=='ON_FAILURE'.
    - ingredients/tests/test_rebuild_projections.py::test_function_exists_and_idempotent — migration adds public.rebuild_projections(); calling it twice on a seeded recipe_docs leaves recipe_doc_ingredients / recipe_clusters byte-identical (TRUNCATE-and-rebuild purity). Fails: no function.
    - test_workflow_shapes.py::test_runbook_covers_all_steps — docs/devops-runbook.md contains headed sections for Supabase Pro, repo secrets, R2 bucket, Tailscale key, Railway worker, Vercel env, RecipeGF tag, smoke-loop, promote (assert the nine step markers present).
- GREEN: Extend deploy-migrations.yml: add pull_request:[main] validate job (throwaway postgres:16 service, loop psql -f over migrations) and append rebuild_projections() to the staging push job. Add web-ci.yml (node, npm ci, npm test in web/). Add deploy-worker.yml (railway up) OR document native Railway GitHub integration as the default (workflow is the gated alternative). railway.json declarative config. rebuild_projections_fn.sql: SQL function that TRUNCATEs each projection and re-inserts via project(doc) SQL (coordinate exact projection DDL with data-model half; the function body may delegate to their builder SQL). devops-runbook.md: lift the SETUP RUNBOOK verbatim with exact CLI. The workflow-shape tests parse YAML with a tiny pytest (PyYAML) so CI wiring itself is RED-tested.
- DONE:
    - web-ci.yml is the first committed web/Vitest gate — every UI workstream (B27..B33) now has a PR gate (previously an open item).
    - deploy-migrations validate job blocks a non-applying migration before staging.
    - ingredients-ci.yml green (rebuild_projections migration applies + idempotency test).
    - Runbook doc merged; docs/deployment.md --ff-only staleness corrected to the merge-commit promotion model.
    - YAGNI-correct single-environment reading honored: main gets validation only, staging is the sole deploy target.
- YAGNI:
    - No second/production environment, no k8s, no Terraform — direct CLI in the runbook; the declarative bits (railway.json, workflows) live in-repo only.
    - No worker autoscaling — numReplicas=1; SKIP LOCKED keeps N-replica a future config bump, not built.
    - No custom domain / Resend verification — staging stays single-user magic-link.
    - No coverage-percentage or deploy-approval gates beyond green CI.

### WS-B22 — jobs + job_batches migration + enqueue_job/approve_job RPCs + claim/reaper SQL  [spiritolo]
- depends_on: ['WS-B1 (recipe_docs base schema — data-model half, for the is_admin()/profiles surface + migration ordering)']
- parallelism: serialize-after WS-B1 only for migration-dir ordering (shared supabase/migrations sequence). parallel-safe with UI and audit (disjoint tables: jobs, job_batches). Blocks WS-B23/B24/B31 (they consume the queue schema + RPCs).
- goal: A Postgres-as-queue: UI enqueues scoped jobs via SECURITY-DEFINER enqueue_job, approves metered ones via approve_job, the worker claims via FOR UPDATE SKIP LOCKED, and a reaper requeues stale-heartbeat jobs — all admin-gated, no broker, no API server.
- files: supabase/migrations/20260716090000_job_batches.sql, supabase/migrations/20260716091000_jobs.sql, supabase/migrations/20260716092000_job_rpcs.sql, ingredients/src/ingredients/queue/__init__.py, ingredients/src/ingredients/queue/claim.py, ingredients/src/ingredients/queue/reaper.py, ingredients/tests/test_jobs_schema.py, ingredients/tests/test_job_rpcs.py, ingredients/tests/test_jobs_claim.py, ingredients/tests/test_jobs_reaper.py
- RED tests:
    - test_jobs_schema.py::test_jobs_shape — information_schema asserts job_state enum + columns stage,version,kind CHECK(run,reset,reconcile),payload jsonb,state,requires_approval,approved,approved_by,approved_at,cost_estimate_cents,cost_actual_cents,max_cost_cents,progress jsonb default '{}',error_code,batch_id FK,worker_id,last_heartbeat,created_by,created/started/finished_at; partial index jobs_claimable_idx on (created_at) where state='queued' and (not requires_approval or approved). Fails: no migration.
    - test_jobs_schema.py::test_job_batches_shape — provider default 'openai', provider_batch_id unique, state CHECK(submitted,in_progress,completed,failed,ingested), custom_id_map jsonb, partial job_batches_open_idx where state in (submitted,in_progress).
    - test_jobs_schema.py::test_jobs_rls_and_realtime — jobs RLS enabled (admin read policy), jobs is in the supabase_realtime publication, anon cannot select.
    - test_job_rpcs.py::test_enqueue_job_admin_only — SET ROLE authenticated with a non-admin uid → enqueue_job raises 42501; with an admin uid → returns a bigint and inserts a row stamped created_by=auth.uid().
    - test_job_rpcs.py::test_enqueue_free_vs_metered_state — requires_approval=false → state 'queued'; requires_approval=true → state 'awaiting_approval' and cost_estimate_cents recorded.
    - test_job_rpcs.py::test_enqueue_anon_cannot_insert_directly — SET ROLE anon cannot INSERT into jobs directly (grant boundary; only the SECURITY-DEFINER RPC path writes).
    - test_job_rpcs.py::test_approve_job_gates_metered — an awaiting_approval job is not claimable until approve_job flips approved=true, approved_by=auth.uid(), state='queued'; approve_job on a non-admin raises; approve_job on an already-claimed job is a no-op/rejected.
    - test_jobs_claim.py::test_claim_skip_locked — two psycopg connections each run the claim UPDATE...FOR UPDATE SKIP LOCKED against two queued jobs; each claims a distinct id, neither blocks (contention safety).
    - test_jobs_claim.py::test_claim_respects_max_cost_gate — a queued job with cost_estimate_cents > max_cost_cents is NOT claimed by the claim query.
    - test_jobs_claim.py::test_claim_ignores_awaiting_approval — an unapproved awaiting_approval job is never returned by claim.
    - test_jobs_reaper.py::test_reaper_requeues_stale — a claimed job with last_heartbeat < now()-2min → reaper sets state='queued', worker_id=null; a fresh-heartbeat job is untouched.
    - test_jobs_reaper.py::test_reaper_idempotent — running the reaper twice yields the same result (safe because stage writes are idempotent UPSERTs).
- GREEN: Migrations: job_batches first (jobs.batch_id FKs it), then jobs table + job_state enum + partial claimable index + RLS + realtime publication add, then RPCs. enqueue_job/approve_job SECURITY DEFINER set search_path='' with is_admin() gate (reuse taxonomy_curation_rpcs pattern), EXECUTE granted to authenticated only. claim.py: parameterized UPDATE...(SELECT...FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *, plus a heartbeat() UPDATE. reaper.py: requeue-where-stale UPDATE returning count. Both pure functions taking a psycopg connection so tests drive real Postgres via db_conn.
- DONE:
    - ingredients-ci.yml green (Postgres service auto-applies the three migrations).
    - Grant boundary (anon can't write, authenticated-non-admin can't enqueue), SKIP LOCKED contention, max_cost gate, and reaper idempotency all asserted.
    - jobs added to the realtime publication (unblocks useRealtimeJobs in B27).
- YAGNI:
    - No message broker, no cron/scheduler, no worker HTTP API — reaper requeue is the entire retry story.
    - No job priority lanes, no retry-backoff curves, no dead-letter queue — single created_at FIFO claim.
    - No confirm-before-cost on free stages — approval/max_cost_cents only for requires_approval jobs.
    - No history rows — jobs is dispatch intent; durable history is audit_log's job.

### WS-B23 — Worker daemon: poll/claim loop, stage_fn(job) dispatch, heartbeat, provider-chain seam, max_cost enforcement  [spiritolo]
- depends_on: ['WS-B22 (jobs/RPCs + claim/reaper)', 'WS-B2 (stage_runs table — data-model half)']
- parallelism: serialize-after WS-B22 (imports queue/claim + reaper). parallel-safe with UI/DevOps. Coordinates the stage_fn dispatch table + provider-chain config seam with the data-model half's pipeline-stage workstreams (they register stage functions); B23 owns the loop + the seam contract, they own each stage_fn body.
- goal: A single always-on Railway process that claims jobs, dispatches to stage_fn(job) over a config-not-code provider chain, heartbeats while running, writes results as idempotent stage_runs UPSERTs, rolls up cost_actual, and hard-aborts past max_cost_cents.
- files: ingredients/src/ingredients/worker/__init__.py, ingredients/src/ingredients/worker/loop.py, ingredients/src/ingredients/worker/dispatch.py, ingredients/src/ingredients/worker/providers.py, ingredients/src/ingredients/worker/cost.py, ingredients/tests/test_worker_loop.py, ingredients/tests/test_worker_dispatch.py, ingredients/tests/test_worker_provider_chain.py, ingredients/tests/test_worker_cost_cap.py
- RED tests:
    - test_worker_loop.py::test_claim_run_finish — with one queued job in a TEST_DB_URL jobs table, one loop tick claims it (state->claimed->running->succeeded), sets started/finished_at, and writes a stage_run UPSERT for the scoped entity. Fails: no worker module.
    - test_worker_loop.py::test_heartbeat_updates_during_run — a stage_fn that sleeps (injected clock) causes last_heartbeat to advance; assert heartbeat writes at least once mid-run.
    - test_worker_loop.py::test_empty_queue_no_op — no claimable job → tick returns without error and touches nothing.
    - test_worker_loop.py::test_reaper_on_boot — worker boot calls the reaper once, requeuing a pre-seeded stale-heartbeat job (Railway-restart safety).
    - test_worker_dispatch.py::test_stage_fn_lookup — dispatch maps job.stage -> stage_fn; unknown stage → job state='failed' with error_code, not a crash.
    - test_worker_dispatch.py::test_idempotent_rerun — running the same job twice UPSERTs the same stage_run (one row per entity,stage), never duplicates; cost_actual not double-counted.
    - test_worker_provider_chain.py::test_chain_order_deterministic_first — chain [deterministic, llm] with a fake deterministic provider that RESOLVES short-circuits; the fake llm provider is never called (assert call-count 0).
    - test_worker_provider_chain.py::test_chain_falls_through_on_abstain — deterministic abstains → llm provider is reached; the STORED output (what dedup hashes) equals the llm fake's canned structured result.
    - test_worker_provider_chain.py::test_chain_is_config_not_hardcoded — reordering the chain config ([llm, deterministic]) changes which provider runs first with no code change (seam honored).
    - test_worker_provider_chain.py::test_packing_maps_by_id — a packed N-item request splits results back to the right entity ids; a partial provider failure parks only the failed items (mirrors pending_llm_tried discipline), resolving the rest.
    - test_worker_cost_cap.py::test_aborts_past_max_cost — fake provider reports per-call cost; the job halts once accumulated cost_cents would exceed jobs.max_cost_cents, marks remaining items unprocessed, and records cost_actual_cents = sum of stage_runs.cost_cents (no double count on the aborted item).
    - test_worker_cost_cap.py::test_free_stage_no_cap_check — a deterministic/local-only chain never consults max_cost (free work is uncapped).
- GREEN: loop.py: boot → reconcile batches (B24 hook) + reaper; then while-true tick: claim.claim_one() → dispatch.run(job) with a heartbeat timer thread → on success/failure UPDATE job terminal state + progress. dispatch.py: STAGE_FNS registry {stage: callable(job, conn, providers)}; unknown → failed. providers.py: ProviderChain built from external config (a small dict/JSON the owner rewires, NOT schema); Provider protocol .run(items)->{id: Outcome, cost_cents}; chain iterates links, short-circuits on resolved, packs items. cost.py: accumulate per-item cost, compare to job.max_cost_cents, raise CostCapExceeded to abort. Tests inject FakeProvider(canned outputs, reported cost) and a fake clock — never a live model.
- DONE:
    - ingredients-ci.yml green (worker suite runs against TEST_DB_URL jobs + stage_runs).
    - Chain order/short-circuit/packing, idempotent UPSERT, heartbeat, boot-reaper, and hard max_cost abort all asserted with fake providers only.
    - stage_fn dispatch seam documented as the single fake-provider injection point (closes the foundation open item).
- YAGNI:
    - No live-LLM calls in tests, no VCR/cassette — fake providers only.
    - No provider/order stored in the DB schema — the chain is external config the owner rewires.
    - No priority/fairness scheduler — FIFO claim; no worker-side retry backoff (reaper is retry).
    - No multi-replica coordination logic beyond SKIP LOCKED already giving it.

### WS-B24 — job_batches boot reconciliation (OpenAI async Batch accelerator)  [spiritolo]
- depends_on: ['WS-B22 (job_batches table)', 'WS-B23 (worker loop boot hook + stage_runs write path)']
- parallelism: serialize-after WS-B23 (extends its boot sequence + reuses its stage_run UPSERT). parallel-safe with UI/DevOps. Depends on Tract A tagged v0.4.0 only insofar as ingested extract/parse output must match the frozen doc shape.
- goal: On boot the worker reconciles open job_batches: polls the provider, ingests completed batches into stage_runs keyed by custom_id_map, and flips state to ingested — replacing the data/batches/*.json sidecars with durable DB state. Batch is an optional accelerator, not a core path.
- files: ingredients/src/ingredients/worker/batches.py, ingredients/tests/test_worker_batch_reconcile.py
- RED tests:
    - test_worker_batch_reconcile.py::test_reconcile_open_only — reconcile queries job_batches where state in (submitted,in_progress); ignored/ingested/failed rows are not re-polled. Fails: no module.
    - test_worker_batch_reconcile.py::test_completed_batch_ingested — a fake provider client reports a batch completed with an output file mapping custom_id->result; reconcile writes one stage_run UPSERT per mapped entity_id (via custom_id_map) and flips job_batches.state='ingested'.
    - test_worker_batch_reconcile.py::test_in_progress_left_open — a still-in_progress batch stays state='in_progress', writes no stage_runs.
    - test_worker_batch_reconcile.py::test_ingest_idempotent — re-running reconcile on an already-ingested batch is a no-op (state guard) — safe across Railway restarts.
    - test_worker_batch_reconcile.py::test_partial_batch_parks_failures — results missing/errored for some custom_ids park those entities (no stage_run written for them) while ingesting the rest; batch still flips to a terminal state with a recorded failure count.
    - test_worker_batch_reconcile.py::test_boot_calls_reconcile_before_claim — worker boot ordering: reconcile runs before the first claim (so a completed batch's rows exist before dependent stages claim).
- GREEN: batches.py: reconcile(conn, client): select open batches → client.get_batch(provider_batch_id) → on completed, download output file, map custom_id->entity via custom_id_map, UPSERT stage_runs (reuse B23 writer), UPDATE job_batches state. Provider client is injected (FakeBatchClient in tests). Boot hook: loop.py calls batches.reconcile() before the claim loop.
- DONE:
    - ingredients-ci.yml green (batch reconcile suite, fake client).
    - Open-only polling, custom_id_map ingest, idempotency, partial-failure parking, and boot ordering asserted.
    - Sidecar files (data/batches/*.json) fully replaced by job_batches rows.
- YAGNI:
    - No batch submission UI path in v1 — packed real-time requests (B23) are the core; Batch is opt-in for big hosted backfills only.
    - No sidecar JSON fallback — job_batches is the single source of durable batch state.
    - No cross-provider batch abstraction beyond OpenAI — provider column exists but only openai is wired.

### WS-B25 — worker.Dockerfile + Tailscale-userspace entrypoint + local-provider proxy client  [spiritolo]
- depends_on: ['WS-B23 (worker entrypoint target: python -m ingredients.worker)']
- parallelism: parallel-safe. Owns Dockerfile, entrypoint shell, and the local-provider HTTP-client proxy wiring; only overlaps WS-B21 which references these filenames in deploy-worker.yml (contract, not content).
- goal: The worker image builds the uv workspace, bakes Tailscale in userspace-networking mode with a local SOCKS5 proxy, and joins the tailnet on boot so the free 'local' provider reaches barbot's Ollama — while hosted APIs (OpenAI/Claude/ScraperAPI) bypass the proxy and take the direct route.
- files: worker.Dockerfile, scripts/worker-entrypoint.sh, ingredients/src/ingredients/worker/providers_local.py, ingredients/tests/test_local_provider_proxy.py, scripts/tests/test_worker_entrypoint.py
- RED tests:
    - test_local_provider_proxy.py::test_local_client_uses_ts_proxy — the local (Ollama) provider client reads TS_LOCAL_PROXY and sets its transport proxy to socks5://localhost:1055; base URL from OLLAMA_BASE_URL (http://barbot:11434). Fails: no module.
    - test_local_provider_proxy.py::test_hosted_clients_bypass_proxy — the OpenAI/Claude/ScraperAPI clients do NOT read TS_LOCAL_PROXY and are constructed with no proxy (assert direct route; barbot uplink not tunneled).
    - test_local_provider_proxy.py::test_no_global_all_proxy_leak — constructing the hosted clients does not depend on a global ALL_PROXY/HTTPS_PROXY env (only the local client is proxied).
    - test_worker_entrypoint.py::test_entrypoint_starts_tailscaled_userspace — parse worker-entrypoint.sh; assert it launches tailscaled with --tun=userspace-networking, --socks5-server=localhost:1055, --state=mem:. Fails: script absent.
    - test_worker_entrypoint.py::test_entrypoint_joins_ephemeral_authkey — `tailscale up --authkey=${TAILSCALE_AUTHKEY...}` with a required-var guard (set -u) and hostname spiritolo-worker.
    - test_worker_entrypoint.py::test_entrypoint_execs_worker — final line execs `uv run --package spiritolo-ingredients python -m ingredients.worker` (PID 1 handoff so Railway restart semantics work).
    - test_worker_entrypoint.py::test_dockerfile_userspace_no_privileged — worker.Dockerfile copies tailscaled/tailscale static binaries and does NOT require NET_ADMIN/TUN (userspace pattern); runs uv sync --frozen --package spiritolo-ingredients; RECIPEGF_TOKEN is a build ARG not a runtime ENV.
- GREEN: worker.Dockerfile per FOUNDATION §2 (python:3.11-slim, uv installer, COPY tailscaled/tailscale from tailscale:stable, copy workspace, uv sync --frozen with build-arg RECIPEGF_TOKEN git-insteadOf). worker-entrypoint.sh: tailscaled userspace + local proxy → tailscale up ephemeral+preauth → export TS_LOCAL_PROXY=socks5://localhost:1055 → exec the worker. providers_local.py: OllamaClient(base_url=OLLAMA_BASE_URL, proxy=os.environ.get('TS_LOCAL_PROXY')); hosted-provider constructors deliberately ignore it. Tests parse the shell/Dockerfile as text and assert client construction with a fake transport.
- DONE:
    - scripts + ingredients suites green (entrypoint shape + local-vs-hosted proxy split).
    - Image builds in deploy-worker.yml (WS-B21); railway logs show tailscaled up + tailnet joined + poll loop started (runbook smoke step 8).
    - Only the local provider tunnels through Tailscale; hosted APIs verified to take the direct route.
- YAGNI:
    - No global HTTPS_PROXY export — hosted API latency and barbot-uplink dependency avoided.
    - No privileged container / TUN device — userspace networking only.
    - No persistent Tailscale state — ephemeral --state=mem: node self-cleans on exit.
    - No vendored recipegf wheel — build-time git clone via RECIPEGF_TOKEN arg (revisit only if CI can't reach github).

### WS-B26 — audit.log generic trigger + actor-context wiring (human/worker/system)  [spiritolo]
- depends_on: ['WS-B1 (recipe_docs) + existing taxonomy_nodes/proposals tables']
- parallelism: serialize-after WS-B1 for the recipe_docs trigger attachment; parallel-safe with jobs/UI (disjoint: audit schema). Coordinates with WS-B23 (worker sets app.job_id/app.source per job txn) and WS-B32 (edit RPC sets app.source='manual-ui-edit') — B26 owns the trigger + GUC contract, they set the GUCs.
- goal: A ~40-line custom trigger writes one generic audit.log row per content mutation capturing actor (human auth.uid | worker job_id | system), source, before/after, and changed_keys — with the human-vs-worker-vs-system distinction falling out of auth.uid() and SET LOCAL app.job_id/app.source. Reject supa_audit.
- files: supabase/migrations/20260717090000_audit_log.sql, supabase/migrations/20260717091000_audit_triggers.sql, ingredients/src/ingredients/worker/actor_context.py, ingredients/tests/test_audit_schema.py, ingredients/tests/test_audit_actor.py, ingredients/tests/test_audit_changed_keys.py
- RED tests:
    - test_audit_schema.py::test_audit_log_shape — information_schema over audit.log asserts columns ts, table_name, pk, op CHECK(I,U,D), actor_kind CHECK(human,worker,system), actor_id, source, before jsonb, after jsonb, changed_keys text[]; indexes on (table_name,pk,ts desc) and (actor_kind,ts desc); RLS enabled admin-read-only. Fails: no migration.
    - test_audit_actor.py::test_worker_actor_from_app_job_id — with no JWT (service role), SET LOCAL app.job_id='42', app.source='job:parse', then UPDATE recipe_docs → exactly one audit row actor_kind='worker', actor_id='42', source='job:parse'.
    - test_audit_actor.py::test_human_actor_from_auth_uid — simulate a user JWT (set request.jwt.claim.sub / auth.uid()), app.source='manual-ui-edit', UPDATE recipe_docs → actor_kind='human', actor_id=<uid>, source='manual-ui-edit'.
    - test_audit_actor.py::test_system_actor_when_no_context — no JWT, no app.job_id GUC (migration/reaper/seed) → actor_kind='system', actor_id null.
    - test_audit_actor.py::test_insert_and_delete_captured — INSERT → before null, after=row, op='I'; DELETE → before=row, after null, op='D' (no soft-delete needed; the DELETE row is the tombstone).
    - test_audit_changed_keys.py::test_changed_keys_on_update — UPDATE that touches doc but not source_url → changed_keys == ['doc','updated_at'] (only keys whose value is distinct); no stored full-diff blob.
    - test_audit_changed_keys.py::test_single_writer_all_paths — a hand-SQL UPDATE, a worker UPDATE (app.job_id set), and an RPC UPDATE (auth.uid set) each produce exactly one audit row with the correct actor_kind — the trigger is the sole audit writer (no double-log).
    - test_audit_schema.py::test_composite_pk_tables_not_audited — taxonomy_edges/aliases/cocktail_aliases have no row-audit trigger (node-level audit is the meaningful unit).
- GREEN: audit_log.sql: create schema audit + table + indexes + RLS. audit_triggers.sql: audit.log_change() SECURITY DEFINER reading auth.uid(), current_setting('app.job_id',true), current_setting('app.source',true); derive kind; INSERT before/after/changed_keys (jsonb_each is-distinct-from). Attach AFTER INSERT/UPDATE/DELETE FOR EACH ROW on recipe_docs, taxonomy_nodes, taxonomy_proposals, recipegf_proposals only. actor_context.py: helper set_job_context(conn, job_id, source) issuing SET LOCAL, called at the top of each worker job txn (B23) so worker writes attribute correctly.
- DONE:
    - ingredients-ci.yml green (audit schema + actor derivation + changed_keys + single-writer).
    - All three actor_kinds proven to fall out of auth.uid()/app.job_id with no bolted-on side channel.
    - supa_audit explicitly not adopted; worker (B23) and edit RPC (B32) both route through the one trigger.
- YAGNI:
    - No supa_audit extension — the custom trigger captures exactly actor+source+diff+time.
    - No stored full-jsonb diff — before + after + changed_keys only.
    - No per-edge audit of composite-PK reference tables — node-level is the unit.
    - No retention/partitioning from day one — defer until volume warrants (append-only is fine now).

### WS-B27 — Form-kit token extraction to :root + shared hooks (useRpc, usePagedQuery, useRealtimeJobs, useAdminGate)  [spiritolo]
- depends_on: ['WS-B21 (web-ci.yml gate)', 'WS-B22 (jobs in realtime publication, for useRealtimeJobs)']
- parallelism: parallel-safe with all DB/worker work (web/ only). Blocks WS-B28..B33 (every primitive/view composes these hooks + tokens). Internal fan-out: the four hooks are independent files → up to 4 concurrent sub-tasks after tokens.css lands.
- goal: Lift the --tx-form-* tokens out of .taxonomy-page to :root so EditableField/ModalShell/.tx-* render anywhere, add the ops surface tokens, and ship the four DRY hooks every /ops view composes — the single change that unlocks reuse plus the data/mutation/realtime plumbing.
- files: web/src/ui/tokens.css, web/src/ui/tokens.test.tsx, web/src/ui/hooks/useRpc.ts, web/src/ui/hooks/useRpc.test.tsx, web/src/ui/hooks/usePagedQuery.ts, web/src/ui/hooks/usePagedQuery.test.tsx, web/src/ui/hooks/useRealtimeJobs.ts, web/src/ui/hooks/useRealtimeJobs.test.tsx, web/src/ui/hooks/useAdminGate.ts, web/src/main.tsx, web/src/components/taxonomy/taxonomy.css
- RED tests:
    - tokens.test.tsx::test_editable_field_renders_off_taxonomy_page — render <EditableField> OUTSIDE any .taxonomy-page ancestor and assert getComputedStyle resolves --tx-form-border to a non-empty value (guards the extraction; without it the var resolves to nothing). Fails: tokens still scoped to .taxonomy-page.
    - tokens.test.tsx::test_ops_status_tokens_present — a node under .ops resolves --st-resolved / --job-running to non-empty semantic colors.
    - useRpc.test.tsx::test_success_unwraps — mock supabase.rpc resolving {data, error:null}; useRpc('fn').mutate(args) → returns data, calls the mocked rpc with args (reuses taxonomy/rpcs unwrap).
    - useRpc.test.tsx::test_error_throws_RpcError — rpc resolves {data:null, error:{message,code}} → mutation rejects with RpcError carrying code; invalidate keys fire only on success.
    - usePagedQuery.test.tsx::test_range_and_count — asserts the mocked chain calls .select(sel,{count:'exact'}).range(from,to).order(...); returns rows+total.
    - usePagedQuery.test.tsx::test_keeps_previous_data_while_pending — on page change, prior rows stay visible and pending=true until the next page resolves (no-flash overlay behavior via keepPreviousData).
    - usePagedQuery.test.tsx::test_filters_applied — a PostgrestFilter[] is applied as .eq/.in/.lt calls in order.
    - useRealtimeJobs.test.tsx::test_channel_payload_merges — a mocked postgres_changes payload for jobs lands in the react-query cache (jobs list updates without refetch).
    - useRealtimeJobs.test.tsx::test_poll_fallback_when_no_channel — when the channel is absent/disconnected, refetchInterval polling drives updates and connected=false.
    - useAdminGate.test.tsx::test_is_alias_of_useIsAdmin — useAdminGate is referentially the existing useIsAdmin (no new auth surface).
- GREEN: tokens.css: move the --tx-form-* block from .taxonomy-page to :root; add .ops surface + --st-*/--job-* palette; import once in main.tsx; remove the duplicated tokens from taxonomy.css (taxonomy keeps only its deco tokens). useRpc: react-query useMutation wrapping supabase.rpc via the taxonomy unwrap/RpcError, with optional invalidate + Toast. usePagedQuery: useQuery with placeholderData:keepPreviousData building the PostgREST select/range/order/filter chain. useRealtimeJobs: subscribe to postgres_changes on jobs, merge into cache, poll fallback. useAdminGate: `export { useIsAdmin as useAdminGate }`.
- DONE:
    - web-ci.yml green (Vitest).
    - EditableField/ModalShell/.tx-* proven to render outside taxonomy (extraction guard).
    - Taxonomy page visually unchanged (deco tokens untouched; its existing tests still green).
    - Four hooks are the single data/mutation/realtime seam for all /ops views.
- YAGNI:
    - No new design system / component library — extend existing tokens, reuse taxonomy stack.
    - No custom websocket infra — Supabase Realtime + react-query poll fallback only.
    - No generic data-layer abstraction beyond these four hooks — extract more only on the third duplication.
    - Do not re-theme or refactor taxonomy beyond lifting shared tokens.

### WS-B28 — Shared UI primitives — move EditableField/Modal/Toast/Pagination to ui/; add StatusPill/CostBadge/JsonView/DataTable/SplitView/FilterBar  [spiritolo]
- depends_on: ['WS-B27 (tokens + hooks)']
- parallelism: serialize-after WS-B27 (composes usePagedQuery + tokens). Blocks WS-B29..B33 (views compose these). Internal fan-out: the new primitives (StatusPill, CostBadge, JsonView, DataTable, SplitView, FilterBar) are independent files → parallel sub-tasks; the widget-moves (EditableField/ModalShell/Toast/Pagination import-path updates) are a separate serialized slice touching taxonomy imports.
- goal: One home (web/src/ui/) for the cross-view primitives every /ops view composes, so a QoL fix in one place lands everywhere — reusing the taxonomy widgets verbatim and adding the small new ones (no external table/json/grid libs).
- files: web/src/ui/EditableField.tsx, web/src/ui/Modal.tsx, web/src/ui/Toast.tsx, web/src/ui/StatusPill.tsx, web/src/ui/StatusPill.test.tsx, web/src/ui/CostBadge.tsx, web/src/ui/CostBadge.test.tsx, web/src/ui/JsonView.tsx, web/src/ui/JsonView.test.tsx, web/src/ui/DataTable.tsx, web/src/ui/DataTable.test.tsx, web/src/ui/SplitView.tsx, web/src/ui/SplitView.test.tsx, web/src/ui/FilterBar.tsx, web/src/ui/FilterBar.test.tsx, web/src/components/taxonomy/CreateChildModal.tsx
- RED tests:
    - StatusPill.test.tsx::test_maps_outcome_and_jobstate — <StatusPill kind='resolved'> renders the resolved label with the --st-resolved token class; kind='running' uses --job-running; an unknown kind falls back to a neutral pill without throwing.
    - CostBadge.test.tsx::test_cents_formatting — cents=42 → '$0.42'; cents=0 → '$0.00'; null → em-dash; metered variant adds the coin glyph + amber class; est vs actual labels distinguished.
    - JsonView.test.tsx::test_collapsible_and_readonly — renders nested object collapsed at depth, expands on click (userEvent), no input elements (read-only), no external lib import.
    - DataTable.test.tsx::test_renders_columns_and_custom_render — columns with a render fn (e.g. StatusPill cell) render via role/text; sticky header present; body wrapped in an overflow-x:auto container.
    - DataTable.test.tsx::test_selection_returns_ids — selectable table: clicking row checkboxes calls onSelectionChange with the selected ids (feeds scoped triggers).
    - DataTable.test.tsx::test_row_click — onRowClick fires with the row; keyboard/role-accessible.
    - SplitView.test.tsx::test_selected_id_in_url — selecting a list row sets ?sel=<id> and renders the detail pane for it (URL-driven, MemoryRouter).
    - FilterBar.test.tsx::test_emits_single_object — changing site select + a free-text + an outcome chip emits ONE {filters:PostgrestFilter[], scope:ScopeDescriptor} object; the same filters feed a mocked usePagedQuery and the same scope is what a trigger would enqueue (they can't drift).
    - web/src/ui/EditableField.test.tsx::test_moved_import_still_green — the moved EditableField passes its existing optimistic-apply + rollback tests from the new path; taxonomy imports updated and taxonomy tests still green.
    - CreateChildModal test (existing) still green after ModalShell is lifted to ui/Modal.tsx (compose, don't duplicate).
- GREEN: Move EditableField/Toast to ui/ (update taxonomy import paths); lift ModalShell out of CreateChildModal.tsx into ui/Modal.tsx (CostConfirmModal/DeleteNodeModal compose it). New: StatusPill (~30 lines, token map), CostBadge (~25), JsonView (~60, recursion + <pre> fallback, no lib), DataTable<T> (~120, columns/rows/selectable/onRowClick over usePagedQuery, overflow-x wrapper), SplitView/DetailPane (~50, ?sel= URL state), FilterBar (reuses taxonomy FilterChips, emits {filters, scope}). All accessible-query tested.
- DONE:
    - web-ci.yml green (all primitive tests + moved-widget tests + unchanged taxonomy tests).
    - FilterBar's single-object contract asserted (what-you-see == what-you-act-on).
    - No external table/json/grid library added; every primitive is composed, none view-specific.
- YAGNI:
    - No ag-grid / react-json-view / react-admin — DataTable is a table+hook, JsonView is hand-rolled.
    - No bulk inline-edit grid — edits are one row at a time via DetailPane (B32).
    - No saved views / column customization / user preferences.
    - No mobile/responsive layout beyond overflow-x:auto scroll containers — /ops is a desktop tool.

### WS-B29 — OpsLayout shell + /ops routes + stage_queue_counts view + status dashboard  [spiritolo]
- depends_on: ['WS-B28 (primitives)', 'WS-B2/B3 (stage_runs + queue predicate — data-model half)']
- parallelism: serialize-after WS-B28. parallel-safe with the DB browsers (B30) after the shell lands — B29 owns App.tsx route registration + OpsLayout + the dashboard + the counts view migration; B30 adds child routes. Slight overlap on App.tsx (route table) → B29 lands the <Route path=/ops> wrapper first, B30 fills children.
- goal: The /ops console shell (left nav + Outlet under RequireAdmin) with the route tree, plus the live status dashboard — a grid of StageCards showing queue depth (from a stage_queue_counts view), in-flight jobs, and last-run outcome mix, each with the whole-queue TriggerBar affordance.
- files: web/src/pages/ops/OpsLayout.tsx, web/src/pages/ops/OpsLayout.test.tsx, web/src/pages/ops/Dashboard.tsx, web/src/pages/ops/Dashboard.test.tsx, web/src/pages/ops/StageCard.tsx, web/src/pages/ops/StageCard.test.tsx, web/src/App.tsx, supabase/migrations/20260718090000_stage_queue_counts_view.sql, ingredients/tests/test_stage_queue_counts.py
- RED tests:
    - test_stage_queue_counts.py::test_view_one_row_per_stage — after seeding recipe_docs + stage_runs, stage_queue_counts returns one row per stage with queue_depth = count(content qualifies AND NOT EXISTS(stage_run @ current version)); a doc with a current-version run is NOT counted, one with an older-version run IS. Fails: no view.
    - test_stage_queue_counts.py::test_view_admin_read_only — SET ROLE anon cannot select the view; authenticated admin can.
    - OpsLayout.test.tsx::test_guarded_and_nav — /ops renders under RequireAdmin (non-admin → redirected/blocked, reusing useIsAdmin mock); left nav lists dashboard/jobs/pages/docs/runs/audit/clusters/exports/review; Outlet renders the child.
    - App.test / OpsLayout.test.tsx::test_lazy_route_registered — /ops is a lazy nested route like Taxonomy; visiting /ops/docs resolves the child.
    - StageCard.test.tsx::test_renders_depth_and_outcome_mix — mock the counts view + a stage_runs outcome aggregate; card shows queue depth and a StatusPill row (resolved/abstain/pending/failed/proposes_new).
    - StageCard.test.tsx::test_inflight_from_realtime — a mocked useRealtimeJobs({stage}) payload with two running jobs → card shows in-flight=2 live.
    - StageCard.test.tsx::test_has_whole_queue_triggerbar — the card renders a <TriggerBar scope={{kind:'whole_queue',stage}}> (composition asserted by role/label, not re-testing TriggerBar internals).
    - Dashboard.test.tsx::test_grid_of_stagecards — one StageCard per pipeline stage in discover→...→export order.
- GREEN: stage_queue_counts_view.sql: a SQL view selecting per-stage queue_depth via the NOT EXISTS predicate against the current version constant (version source coordinated with data-model half — a stage_config/const table). OpsLayout: <div class='ops'><nav/><Outlet/></div> under the existing RequireAuth→RequireAdmin nesting; add the lazy <Route path='/ops'> to App.tsx. Dashboard maps stages → StageCard. StageCard composes usePagedQuery(counts view) + useRealtimeJobs + StatusPill + TriggerBar. No charts.
- DONE:
    - web-ci.yml + ingredients-ci.yml green.
    - Dashboard renders live depth + outcome pills; UI never re-derives queue logic (reads the view).
    - Route tree + guard in place so B30/B31/B32/B33 attach child routes.
- YAGNI:
    - No charts/graphs library — counts + StatusPill breakdowns only.
    - No dashboard customization / saved layouts.
    - No cron/scheduling UI — the only affordance is the manual TriggerBar.
    - UI never recomputes the queue predicate client-side — it reads stage_queue_counts.

### WS-B30 — /ops DB browsers — docs, jobs, runs, audit, clusters, exports (composed from the kit)  [spiritolo]
- depends_on: ['WS-B29 (OpsLayout + routes)', 'Tract A tagged v0.4.0 (for the exports bundle == strip_x(doc) shape)']
- parallelism: serialize-after WS-B29 (attaches child routes; shares App.tsx route children with B29's wrapper). Internal fan-out: the six browsers are independent files → up to 6 parallel sub-tasks; /ops/docs must land first because review (B32) reuses it. Each browser is pure composition of B28 primitives + B27 hooks (no new data layer).
- goal: The read surfaces: recipe_docs browser (centerpiece: doc JsonView with dimmed _x, per-entity stage_runs timeline, edit entry), jobs ledger (live, batch deep-link to review), stage_runs ledger, audit_log browser (actor legibility), clusters browser, and the generate-on-demand bundle preview + download — each a SplitView(DataTable, DetailPane).
- files: web/src/pages/ops/DocsBrowser.tsx, web/src/pages/ops/DocsBrowser.test.tsx, web/src/pages/ops/JobsLedger.tsx, web/src/pages/ops/JobsLedger.test.tsx, web/src/pages/ops/RunsLedger.tsx, web/src/pages/ops/RunsLedger.test.tsx, web/src/pages/ops/AuditBrowser.tsx, web/src/pages/ops/AuditBrowser.test.tsx, web/src/pages/ops/ClustersBrowser.tsx, web/src/pages/ops/ClustersBrowser.test.tsx, web/src/pages/ops/ExportsPreview.tsx, web/src/pages/ops/ExportsPreview.test.tsx, web/src/App.tsx
- RED tests:
    - DocsBrowser.test.tsx::test_splitview_doc_and_stageruns — SplitView renders a DataTable over recipe_docs (name from doc, site generated col, state breadcrumb with current cursor bolded); selecting a row shows JsonView of doc with the _x sidecar DIMMED and flagged 'stripped at export', plus a stage_runs timeline (method/confidence/model/cost).
    - DocsBrowser.test.tsx::test_batch_filter_entry — ?batch=<id> filters the table to that batch (the review entry point; DRY with /ops/review).
    - DocsBrowser.test.tsx::test_composes_kit — asserts it renders the shared DataTable + JsonView (by their roles/labels), not re-implementing them.
    - JobsLedger.test.tsx::test_live_jobs_table — DataTable over jobs (stage, kind, state StatusPill, CostBadge est/actual, created_by, heartbeat age) driven by useRealtimeJobs; a mocked payload updates a row's state pill live.
    - JobsLedger.test.tsx::test_review_deeplink — a completed batch job's detail pane shows a 'Review results' button linking to /ops/review?job=<id>.
    - RunsLedger.test.tsx::test_below_current_version_visible — filtering by stage/version surfaces rows below the current version (the --reset candidates) — read-only.
    - AuditBrowser.test.tsx::test_actor_legibility — DataTable over audit_log shows actor (human uid vs worker job_id vs system), source (manual-ui-edit vs job:*), table, pk, ts; detail pane shows before/after via JsonView.
    - ClustersBrowser.test.tsx::test_members_join — a cluster row's detail lists member recipes (reuses the recipes(...) join style from NodeCard).
    - ExportsPreview.test.tsx::test_bundle_generated_on_demand — JsonView of {recipe,verbs,meta} generated client-side from the fetched rows (never a stored blob); a Download button produces a Blob (no server); a UI note states bundle == doc minus _x.
    - ExportsPreview.test.tsx::test_strip_x_parity — the previewed recipe equals doc with _x removed (asserted against a fixture doc).
- GREEN: Each browser = <SplitView list={<DataTable ... usePagedQuery over table/view>} detail={<DetailPane .../>}>. DocsBrowser detail: JsonView(doc) with _x dimmed + stage_runs timeline + Edit entry (opens B32 editor). JobsLedger: useRealtimeJobs, StatusPill/CostBadge cells, batch deep-link. AuditBrowser: audit_log query + JsonView diff. ExportsPreview: fetch relational rows, generate bundle via a small client strip_x + verb-collection, JsonView + Blob download. Register all as children of the /ops route.
- DONE:
    - web-ci.yml green (all six browser suites).
    - Every browser asserted to COMPOSE the shared kit (kit role/label queries), not re-test widget internals — the QoL-lands-everywhere property.
    - Bundle generated on demand with strip_x parity; no stored blob, no relational trio.
- YAGNI:
    - No stored export bundle — generated on demand from strip_x(doc).
    - No WYSIWYG doc editing here — read surfaces; edits live in B32.
    - No graph/visualization of clusters — a table + member list.
    - No cross-browser saved filters — FilterBar state is URL-driven only.

### WS-B31 — TriggerBar (four scopes) + CostConfirmModal + stage_config metering gate  [spiritolo]
- depends_on: ['WS-B22 (enqueue_job/approve_job RPCs)', 'WS-B28 (Modal/CostBadge/primitives)', 'WS-B29 (dashboard host) / WS-B30 (browser hosts)']
- parallelism: serialize-after WS-B22 + WS-B28. parallel-safe with individual browsers (they only slot <TriggerBar>). Owns the stage_config source + CostConfirmModal + TriggerBar; coordinates the ScopeDescriptor type with FilterBar (B28) and DataTable selection (B28).
- goal: One <TriggerBar> present on the dashboard and every browser, supporting item / multiselect / filter / whole_queue scopes; metered stages (read from stage_config, not hardcoded) open a CostConfirmModal (item count + CostBadge estimate + max_cost_cents input) that calls enqueue_job then approve_job; free stages enqueue directly. A persistent progress Toast tracks the job live.
- files: web/src/ui/TriggerBar.tsx, web/src/ui/TriggerBar.test.tsx, web/src/ui/CostConfirmModal.tsx, web/src/ui/CostConfirmModal.test.tsx, web/src/ui/stageConfig.ts, web/src/ui/stageConfig.test.ts, supabase/migrations/20260718100000_stage_config.sql, ingredients/tests/test_stage_config.py
- RED tests:
    - test_stage_config.py::test_stage_config_shape — a stage_config table (or a read view) exposes per-stage {stage, metered boolean, requires_approval boolean} readable by authenticated admin; the UI consults it (not hardcoded). Fails: no migration.
    - stageConfig.test.ts::test_metered_lookup — isMetered('fetch') true, isMetered('parse'|deterministic-only) false, driven by the fetched config not a literal.
    - TriggerBar.test.tsx::test_four_scopes — renders scope affordances for item / multiselect (from DataTable selection ids) / filter (from FilterBar object) / whole_queue; the ScopeDescriptor passed to enqueue matches the chosen scope.
    - TriggerBar.test.tsx::test_free_stage_enqueues_directly — for a non-metered stage, clicking run calls useRpc('enqueue_job') immediately with NO CostConfirmModal.
    - TriggerBar.test.tsx::test_metered_opens_cost_modal — for a metered stage, run opens CostConfirmModal instead of enqueuing.
    - CostConfirmModal.test.tsx::test_confirm_disabled_until_acknowledged — Confirm is disabled until the estimate is acknowledged (mirror DeleteNodeModal.test), shows item count + CostBadge estimate + a max_cost_cents input.
    - CostConfirmModal.test.tsx::test_confirm_calls_enqueue_then_approve — on confirm, enqueue_job is called with {stage,version,kind,scope,max_cost_cents} then approve_job with the returned id (metered flow), and a persistent progress Toast appears.
    - TriggerBar.test.tsx::test_filter_scope_matches_view — the scope handed to enqueue for a 'filter' trigger is the SAME object FilterBar emitted for the current view (what-you-see == what-you-act-on).
- GREEN: stage_config.sql: small reference table {stage, metered, requires_approval} (seed for the current chain; owner rewires). stageConfig.ts: usePagedQuery/useQuery over it + isMetered helper. TriggerBar: builds ScopeDescriptor from item/selection/FilterBar/whole_queue; if isMetered → open CostConfirmModal (composes ui/Modal); else useRpc('enqueue_job'). CostConfirmModal: item count + CostBadge(estimate) + max_cost input + acknowledge gate → enqueue_job then approve_job. Progress Toast tracks via useRealtimeJobs(jobId).
- DONE:
    - web-ci.yml + ingredients-ci.yml green.
    - Metered vs free routing driven by stage_config (config-not-code), asserted.
    - enqueue→approve two-step for metered work with a hard max_cost input; free work single-step.
    - filter-scope == view-scope proven (no drift).
- YAGNI:
    - No client-side cost simulation engine beyond item_count × per_item_cents (a worker estimate_job_cost RPC is a future swap behind the same modal).
    - No confirm-before-cost on free stages.
    - No per-view permission tiers — single is_admin gate.
    - No scheduling — every trigger is a manual, scoped, one-shot enqueue.

### WS-B32 — Review/edit-after-batch: edit_recipe_doc RPC → content + audit(actor=human) + /ops/review route  [spiritolo]
- depends_on: ['WS-B26 (audit trigger — the single audit writer)', 'WS-B30 (/ops/docs browser reused)', 'WS-B27 (useRpc)']
- parallelism: serialize-after WS-B26 + WS-B30. parallel-safe with other views. Owns the edit_recipe_doc migration + the review route (a preset, not a new screen) + the DetailPane editor wiring.
- goal: After a batch finishes, make it trivial to find what the machine punted on and fix it: /ops/review is a canned-filter preset of the docs browser (outcome='abstain' OR confidence<threshold, scoped to the batch); a field edit routes through a typed SECURITY-DEFINER edit_recipe_doc RPC that patches the doc AND appends one audit_log row with actor=auth.uid(), source='manual-ui-edit'.
- files: supabase/migrations/20260719090000_edit_recipe_doc_rpc.sql, web/src/pages/ops/Review.tsx, web/src/pages/ops/Review.test.tsx, web/src/pages/ops/DocEditor.tsx, web/src/pages/ops/DocEditor.test.tsx, ingredients/tests/test_edit_recipe_doc_rpc.py, web/src/App.tsx
- RED tests:
    - test_edit_recipe_doc_rpc.py::test_admin_only — SET ROLE authenticated non-admin → edit_recipe_doc raises 'not authorized'; admin succeeds. Fails: no function.
    - test_edit_recipe_doc_rpc.py::test_patches_doc_and_audits — edit_recipe_doc(id, patch) shallow-merges doc||patch, bumps updated_at, AND (via the B26 trigger, because the RPC sets app.source='manual-ui-edit' under the user JWT) inserts exactly ONE audit_log row with actor_kind='human', actor_id=<uid>, source='manual-ui-edit', correct before/after. (No explicit audit INSERT in the RPC — the trigger is the sole writer; asserts no double-log.)
    - test_edit_recipe_doc_rpc.py::test_optional_manual_stage_run — the edited field's stage is marked settled: an UPSERT stage_run (method='manual', outcome='resolved') so it is not re-queued (assert it's present and latest-only).
    - test_edit_recipe_doc_rpc.py::test_missing_doc_raises — editing a non-existent id raises, no partial write.
    - Review.test.tsx::test_canned_filter_preset — /ops/review?job=<id> renders the docs DataTable preset to outcome='abstain' OR confidence<threshold scoped to the batch (a preset of DocsBrowser, not a new screen — DRY).
    - DocEditor.test.tsx::test_edit_calls_rpc_optimistic — editing a field via EditableField calls useRpc('edit_recipe_doc') with {p_doc_id, p_patch}, optimistically applies, and shows a Toast; on RPC throw it rolls back (mirrors taxonomy handleEditField).
    - DocEditor.test.tsx::test_shows_raw_input_machine_output — the detail pane shows raw input (recipeIngredient string / source.jsonld), the machine's output, and the current doc field side by side for correction.
- GREEN: edit_recipe_doc_rpc.sql: SECURITY DEFINER, admin-gate via profiles.is_admin, perform set_config('app.source','manual-ui-edit',true), SELECT doc FOR UPDATE, UPDATE recipe_docs SET doc=doc||p_patch, optional UPSERT stage_run(manual/resolved); the B26 trigger writes the audit row. Review.tsx: renders DocsBrowser with a preset FilterBar object from ?job/?batch. DocEditor: DetailPane composing EditableField + useRpc('edit_recipe_doc'). Register /ops/review child route.
- DONE:
    - web-ci.yml + ingredients-ci.yml green.
    - Human edit proven to route RPC → content patch + exactly one audit row (actor=human, source=manual-ui-edit) via the single trigger — no double-log, cleanly distinct from worker/system writes.
    - Review is a canned filter of /ops/docs, not a separate screen (DRY).
- YAGNI:
    - No generic content-edit framework — one typed edit RPC per editable table (mirrors update_taxonomy_node).
    - No WYSIWYG / deep nested-doc editor — shallow jsonb doc||patch; jsonb_set paths deferred until a real nested case demands it.
    - No bulk edit — one row at a time via DetailPane.
    - No separate audit INSERT in the RPC — the B26 trigger is the sole audit writer.

### WS-B33 — sign-corpus-url Edge Function + sandboxed corpus iframe (/ops/pages)  [spiritolo]
- depends_on: ['WS-B20 (pages table + r2_key)', 'WS-B30 (browser pattern)']
- parallelism: serialize-after WS-B20 (needs pages.r2_key) + WS-B30 (SplitView browser pattern). parallel-safe otherwise. Owns the Edge Function (new server surface) + the PagesBrowser view.
- goal: The corpus/pages browser renders the stored HTML from R2 in a script-disabled, same-origin-only sandboxed iframe whose src is a short-lived signed URL minted by a single Supabase Edge Function (sign-corpus-url) — the one place server code enters the UI tract. Captured HTML is rendered, never executed.
- files: supabase/functions/sign-corpus-url/index.ts, supabase/functions/sign-corpus-url/index.test.ts, web/src/pages/ops/PagesBrowser.tsx, web/src/pages/ops/PagesBrowser.test.tsx, web/src/App.tsx
- RED tests:
    - index.test.ts::test_admin_only — sign-corpus-url invoked without an admin JWT returns 401/403; with an admin JWT returns a signed URL (the function verifies is_admin via the caller's JWT). Fails: no function.
    - index.test.ts::test_signs_by_r2_key — given a pages.r2_key it returns a presigned R2 GET URL scoped to that key with a short TTL (assert expiry is minutes, not open-ended); it never returns the R2 secret.
    - index.test.ts::test_rejects_unknown_key — a key not present in pages is refused (no signing arbitrary bucket objects).
    - PagesBrowser.test.tsx::test_datatable_over_pages — SplitView with a DataTable over pages (url, site, denylist, fetch meta) composing the shared kit.
    - PagesBrowser.test.tsx::test_iframe_sandbox_same_origin_only — the detail iframe has sandbox='allow-same-origin' and NOT allow-scripts (captured HTML rendered, never executed); assert the exact sandbox attribute.
    - PagesBrowser.test.tsx::test_iframe_src_from_signed_fn — selecting a page calls supabase.functions.invoke('sign-corpus-url',{r2_key}) (mocked) and sets the iframe src to the returned signed URL; while pending, no src is set.
    - PagesBrowser.test.tsx::test_denylisted_render — a denylisted page still browsable, flagged with a StatusPill; no trigger to re-fetch (corpus is read-only).
- GREEN: supabase/functions/sign-corpus-url/index.ts: Deno Edge Function that (1) verifies the caller's JWT + is_admin, (2) looks up the r2_key in pages, (3) mints a short-TTL presigned R2 GET via the S3-compat API using R2 creds held server-side, (4) returns {url}. PagesBrowser: SplitView(DataTable over pages, DetailPane with a sandboxed iframe whose src is set from functions.invoke). Register /ops/pages route. The R2 secret lives only in the function's env, never in the browser.
- DONE:
    - web-ci.yml green (PagesBrowser + a Deno test for the function, or a mocked-boundary Vitest if Deno test isn't wired — function shape asserted).
    - iframe is sandboxed same-origin-only (no script execution) and src is always a short-lived signed URL; R2 secret never reaches the client.
    - This is the ONLY server code in the UI tract (documented), closing the signed-URL open item.
- YAGNI:
    - No worker endpoint for signing — a single tiny Edge Function is the whole server surface.
    - No script execution / interactive replay of captured HTML — sandboxed render only.
    - No re-fetch/re-scrape affordance in the pages view — corpus is read-only.
    - No long-lived or public R2 URLs — short TTL, admin-gated minting only.


