# Staging Deploy + Auth Lockdown — Design

**Date:** 2026-05-02
**Branch:** `supabase-staging`
**Status:** Awaiting user review.

## Problem

Spiritolo has been running locally only. We want to host the web app on the
Supabase + Vercel free tiers, accessible to a single user (the operator) over
the open internet, with everything behind authentication. The hosted
environment is named `spiritolo-staging` because real production will follow
later.

Three coupled deliverables:

1. **Hosting infrastructure** — Supabase + Vercel projects, branching strategy,
   migration CI.
2. **Auth + RLS lockdown** — Supabase Auth with magic link, a `profiles`
   table with `is_admin`, and a tiered RLS structure that lets us cheaply
   open up tier-(a) content to anonymous users later without touching
   tier-(c) admin policies.
3. **Frontend changes** — landing page, login page, route guards, header
   sign-out.

## Goals

1. A deployed staging site at a Vercel URL, gated by magic-link login.
2. Migrations and frontend deploy automatically when promoted via a
   `staging` branch — `main` stays the integration trunk.
3. RLS policies expressed so a future "open everything we currently
   gate temporarily" sweep is a mechanical grep + one migration, while
   admin-only and per-user-permanent policies are visibly distinct.
4. Route guards structured so adding a new protected page can't accidentally
   leak it — public routes have to be actively moved out of the auth wrapper.
5. Local development workflow unchanged. The local Supabase remains the
   source of truth for data *for now*; staging is seeded from local on
   first bootstrap and from migrations + manual data ops afterwards.

## Non-goals (v1)

- Production environment. We deploy a single environment named "staging"
  with no live "production" yet. Adding a `production` branch + Supabase
  project later is a follow-up.
- Per-user data (favorites, comments, collections). Tier-(b) policies have
  no current consumers; the convention is reserved.
- Self-service signup. New users are created by the operator from the
  Supabase Studio.
- Password auth, OAuth providers, or any login method other than email
  magic link.
- A `/logout` route. Sign-out is a header button calling
  `supabase.auth.signOut()` then navigating home.
- A reusable, checked-in remote-seed script. The initial bootstrap script
  for staging is one-shot and ephemeral; do not commit it. (See "Future
  direction" below — data flow may invert.)
- Anything that would prevent the operator from later adopting
  staging-as-source-of-truth (with local seeded from staging backups).

## Future direction (flagged, not designed)

The operator is considering inverting the data flow so that staging is the
data source-of-truth and local development is seeded from staging backups.
This spec deliberately does not bake in the current local-as-truth direction
beyond the bootstrap. Concretely:

- The bootstrap script that seeds staging from local is one-shot and
  ephemeral, not checked in. We do not build a `seed-remote.sh` permanent
  tool that would compete with a future "restore-from-staging-backup"
  script.
- The committed `supabase/seeds/processed/*.sql` files keep their current
  meaning (LLM/curator-touched rows) for as long as local-as-truth holds.
  When we flip to staging-as-truth, those seeds become an "initial cold
  start" artifact rather than a continuously-refreshed snapshot. The flip
  is out of scope for this spec.

## Architecture

### 1. Supabase staging project (`spiritolo-staging`)

- Created at supabase.com (region nearest the operator).
- Linked locally with `supabase link --project-ref <ref>`.
- Schema: every committed migration applied via
  `supabase db push --include-all`.
- Auth: Email provider enabled, magic link only. Password disabled.
  Site URL set to the Vercel URL. Redirect allow-list includes
  `https://<vercel-url>/auth/callback` and any preview domain pattern
  Vercel uses.
- SMTP: default Supabase sender. Solo-use rate limit (~2 emails/hour) is
  acceptable.
- Outputs needed by Vercel + CI:
  - `Project URL`
  - publishable key (`sb_publishable_…`)
  - direct DB connection string (for the migrations workflow secret)

### 2. Vercel staging project (`spiritolo-staging`)

- Imports the GitHub repo.
- Root directory: `web/`. Framework auto-detected as Vite. Build:
  `npm run build`. Output: `dist`.
- Production branch (Vercel terminology): `staging` (not `main`).
- Environment variables (Production scope):
  - `VITE_SUPABASE_URL` = `https://<ref>.supabase.co`
  - `VITE_SUPABASE_PUBLISHABLE_KEY` = `sb_publishable_…`
- Per-PR previews left at default. Preview env vars: same as production
  (we don't have a preview-specific Supabase project).
- SPA deep-link routing: add `web/vercel.json` with a catch-all rewrite
  to `/index.html` so paths like `/recipes/<id>` survive a hard refresh.

### 3. Branching + CI

**Long-lived branches:**

- `main` — integration trunk. Short-lived `claude/<topic>-<id>` branches
  PR into `main` as today. `main` deploys nowhere.
- `staging` — deploy trunk. Both Vercel and the migrations workflow watch
  this branch.

**Promotion workflow (operator runs locally):**

```
git checkout staging
git merge --ff-only main
git push
```

That's the full ceremony. If `--ff-only` refuses, something landed on
staging that isn't on main — investigate before forcing.

**Migrations workflow:**
`.github/workflows/deploy-migrations.yml`

- Trigger: `push` to `staging` with paths `supabase/migrations/**`.
- Steps: install Supabase CLI, run
  `supabase db push --db-url "${{ secrets.SUPABASE_STAGING_DB_URL }}" --include-all`.
- Secret: `SUPABASE_STAGING_DB_URL` (full Postgres URL with password) added
  in repo settings.

**Vercel deploys:**
Native — no GH action. Vercel watches `staging` for production deploys
and any PR branch for previews.

### 4. Auth + RLS architecture (DB)

A single new migration `<timestamp>_auth_and_rls_lockdown.sql` does the
full lift atomically. Its responsibilities:

#### 4a. `profiles` + admin helper

```sql
create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  is_admin boolean not null default false,
  created_at timestamptz not null default now()
);
alter table profiles enable row level security;

create or replace function public.is_admin() returns boolean
  language sql security definer stable
  set search_path = public
  as $$
    select coalesce((select is_admin from profiles where id = auth.uid()), false)
  $$;

create policy profiles_self_read on profiles
  for select to authenticated using (id = auth.uid());

create policy profiles_admin_read on profiles
  for select to authenticated using (is_admin());
```

#### 4b. Auto-create profile on signup

```sql
create or replace function public.handle_new_user() returns trigger
  language plpgsql security definer
  set search_path = public
  as $$ begin insert into profiles (id) values (new.id); return new; end $$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
```

#### 4c. Tier reclassification of existing public-read policies

The existing migrations (`20260424054315_recipes_public_security_invoker.sql`,
`20260501120000_create_taxonomy_public.sql`,
`20260502130000_recreate_taxonomy_public_post_rename.sql`) currently grant
`select` on the public-facing views/tables to both `anon` and
`authenticated`, with `using (true)` policies on the underlying tables.

This migration drops those policies and recreates them under the tier
naming convention, and revokes/regrants column access accordingly.

| Object | Before | After | Tier | Policy name |
|---|---|---|---|---|
| `recipes` | `to anon, authenticated using (true)` | `to authenticated using (true)`, revoke from `anon` | (a) | `recipes_temp_authed_read` |
| `recipe_ingredients` (taxonomy_count cols) | `to anon, authenticated using (true)` | `to authenticated using (true)`, revoke from `anon` | (a) | `recipe_ingredients_temp_authed_read` |
| `taxonomy_nodes` | `to anon, authenticated using (true)` | `to authenticated using (is_admin())`, revoke from `anon` | (c) | `taxonomy_nodes_admin_read` |
| `taxonomy_edges` | `to anon, authenticated using (true)` | `to authenticated using (is_admin())`, revoke from `anon` | (c) | `taxonomy_edges_admin_read` |
| `taxonomy_aliases` | `to anon, authenticated using (true)` | `to authenticated using (is_admin())`, revoke from `anon` | (c) | `taxonomy_aliases_admin_read` |
| `recipes_public` view | grant select to `anon, authenticated` | grant select to `authenticated` only | (a) | (no policy — view) |
| `taxonomy_public` view | grant select to `anon, authenticated` | grant select to `authenticated` only (admin gating happens via underlying-table policies due to security invoker) | (c) | (no policy — view) |

All existing `*_public_read` policies are dropped and replaced. The
existing column-level grants to `anon` are revoked.

#### 4d. Tier convention (legibility for future opens)

- **Tier (a) — temp-auth-gated, eventually anon.** Policy name suffix
  `_temp_authed_read`. A future PR that opens these to anon is one
  migration that drops + recreates them with `to anon, authenticated`,
  found by `grep -r '_temp_authed_read' supabase/migrations`.
- **Tier (b) — permanent auth-required (per-user, no admin requirement).**
  Suffix `_authed_read` (no `temp_`). No instances today.
- **Tier (c) — admin-only.** Suffix `_admin_read`. `using (is_admin())`.

The convention is enforced by code review; no DB-level constraint forces it.

### 5. Frontend auth + routing

#### 5a. Routes

```
/                  Landing (public, no Header)
/login             Magic link form (public, no Header, no nav link)
/auth/callback     Supabase magic-link return target
/recipes           RecipeList (auth-required, with Header)
/recipes/:id       RecipeDetail (auth-required, with Header)
/taxonomy          Taxonomy graph (admin-required, with Header)
/*                 ErrorPage (public)
```

#### 5b. Route guard structure (layout routes, not per-page)

```tsx
<Routes>
  <Route path="/" element={<Landing />} />
  <Route path="/login" element={<Login />} />
  <Route path="/auth/callback" element={<AuthCallback />} />

  <Route element={<RequireAuth />}>          {/* renders <Outlet/> or <Navigate/> */}
    <Route element={<AppLayout />}>          {/* Header + page container */}
      <Route path="/recipes" element={<RecipeList />} />
      <Route path="/recipes/:id" element={<RecipeDetail />} />

      <Route element={<RequireAdmin />}>
        <Route path="/taxonomy" element={<Taxonomy />} />
      </Route>
    </Route>
  </Route>

  <Route path="*" element={<ErrorPage … />} />
</Routes>
```

Adding a new protected page = add a `<Route>` inside the wrapper. Making
a page public = move it outside. Forgetting to gate a new protected page
requires actively choosing to put it outside the wrapper, which is much
more visible in code review than "did we remember to wrap?"

Logged-in users hitting `/` get a one-time `<Navigate to="/recipes">`
inside the Landing component (driven by `useAuth().user`).

#### 5c. Auth context

`AuthProvider` lives at the `BrowserRouter` boundary in `main.tsx`.

- Subscribes to `supabase.auth.onAuthStateChange`.
- Exposes `{ user, session, isAdmin, loading, signOut }`.
- After a session appears, runs `select is_admin from profiles where id = auth.uid()`
  once, caches the result in context, refetches on auth change.
- `loading=true` while the session is being hydrated from
  `localStorage` on first paint, so guards render `null` (or a tiny
  splash) instead of flashing the redirect.

#### 5d. Login flow

- `/login` form: single email field + submit. On submit:
  ```ts
  await supabase.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: `${origin}/auth/callback?next=${nextParam}` },
  });
  ```
- `/auth/callback`: on mount, the Supabase JS client picks the session out
  of the URL automatically; once `useAuth().user` is set, navigate to
  `searchParams.get('next') || '/recipes'`.
- `<RequireAuth>` redirect target: `/login?next=<encoded current path>`.

#### 5e. Sign out

- Header button (right side, only when authed): "Sign out".
- Handler: `await supabase.auth.signOut(); navigate('/');`.
- No `/logout` route.

#### 5f. Landing page content

- Background or hero image (operator-supplied; placed at
  `web/public/landing.<ext>`).
- Title "Spiritolo" rendered as a styled `<h1>`.
- A small "Sign in" link to `/login`. No other navigation.
- No Header (Header is rendered inside `<AppLayout>`, not at the route
  root).

### 6. Initial staging bootstrap (one-time, manual)

This is operator runbook, not an automated workflow. The script is
ephemeral (placed in `/tmp/` or the operator's scratch directory, not
committed).

**Pre-flight checks (local):**

1. `cd ingredients && uv run python -m ingredients.cli` (and friends) —
   make sure no pending unmerged LLM work.
2. `scripts/refresh-processed-seeds.sh dump` — flush LLM/curator-touched
   rows back into committed seed files. `git status` should show only
   intended diffs in `supabase/seeds/processed/*.sql`.
3. `supabase db reset --db-url "$SUPABASE_DB_URL" --yes` then
   `scripts/refresh-processed-seeds.sh restore` then
   `psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f supabase/seeds/recipes.sql`.
4. `cd web && npm run dev`. Sanity-check the app against the rebuilt
   local DB.

**Staging push (one-shot):**

5. Apply migrations to staging:
   `supabase db push --db-url "$STAGING_DB_URL" --include-all`.
6. Apply seeds to staging via psql, in the same order as `restore`:
   ```
   psql "$STAGING_DB_URL" -v ON_ERROR_STOP=1 \
     -f supabase/seeds/taxonomy_nodes_00_families.sql \
     -f supabase/seeds/taxonomy_nodes_*.sql \
     -f supabase/seeds/cocktail_aliases.sql \
     -f supabase/seeds/processed/00_taxonomy_grown.sql \
     -f supabase/seeds/processed/10_recipe_ingredients_llm.sql \
     -f supabase/seeds/processed/20_recipes_normalized.sql \
     -f supabase/seeds/processed/30_cocktail_aliases.sql \
     -f supabase/seeds/recipes.sql
   ```
7. Run the deterministic recompute against staging (mapping, normalize,
   cluster) — same calls `restore` makes locally, but with `SUPABASE_DB_URL`
   pointed at staging for the duration of the run.
8. Create the operator's first auth user in Supabase Studio (Auth → Users
   → Invite). After magic-link sign-in, Studio → Table editor → `profiles`
   → flip `is_admin` to `true` on that row.

After step 8, every subsequent migration goes via `staging` branch + the
GH Action. Schema and code drift in lockstep; data drift is operator-driven.

### 7. CI / GH Actions

`.github/workflows/deploy-migrations.yml`:

```yaml
name: Deploy migrations to staging
on:
  push:
    branches: [staging]
    paths: ['supabase/migrations/**']
jobs:
  push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: supabase/setup-cli@v1
        with: { version: latest }
      - run: supabase db push --db-url "$STAGING_DB_URL" --include-all
        env:
          STAGING_DB_URL: ${{ secrets.SUPABASE_STAGING_DB_URL }}
```

No frontend workflow needed; Vercel handles it natively.

## Files created or modified

**New:**

- `supabase/migrations/<ts>_auth_and_rls_lockdown.sql` — section 4.
- `web/vercel.json` — SPA rewrite for deep links.
- `web/src/auth/AuthProvider.tsx` — context, hooks, profile fetch.
- `web/src/auth/RequireAuth.tsx` — layout-route guard.
- `web/src/auth/RequireAdmin.tsx` — layout-route guard.
- `web/src/components/AppLayout.tsx` — Header + `<Outlet/>` wrapper.
- `web/src/pages/Landing.tsx` — image + title + sign-in link.
- `web/src/pages/Login.tsx` — magic link form.
- `web/src/pages/AuthCallback.tsx` — post-magic-link landing.
- `web/public/landing.<ext>` — operator-supplied image.
- `.github/workflows/deploy-migrations.yml` — section 7.
- `docs/superpowers/specs/2026-05-02-staging-deploy-and-auth-design.md` — this doc.

**Modified:**

- `web/src/App.tsx` — new route tree (section 5b).
- `web/src/main.tsx` — wrap `<App/>` in `<AuthProvider>`.
- `web/src/components/Header.tsx` — add sign-out button (only when authed).
- `web/.env.local.example` — comment about staging URL/key alternative.
- `CLAUDE.md` — add a "Hosting" section with the promote-to-staging
  one-liner and a pointer to this spec.

**Test additions:**

- `web/src/auth/RequireAuth.test.tsx` — redirects unauthenticated, renders
  `<Outlet/>` when authed.
- `web/src/auth/RequireAdmin.test.tsx` — redirects authed-but-not-admin,
  renders when admin.
- `web/src/pages/Login.test.tsx` — submit triggers `signInWithOtp` with
  the correct redirect URL.
- `web/src/pages/Landing.test.tsx` — renders image+title+sign-in for
  logged-out, redirects to `/recipes` for logged-in.

## Open questions / explicit deferrals

- **Magic-link rate limit on the default Supabase SMTP.** Acceptable for
  solo use; if the operator hits it during testing, switch to a custom
  SMTP. Not designed here.
- **Preview deploys share the production Supabase project.** A PR with a
  bad migration could harm staging data via the Vercel preview env.
  Mitigation: the migrations workflow is keyed to `staging` branch only,
  not previews. Frontend previews can read/write live data via the
  publishable key but RLS keeps them from doing damage outside what
  authed users can already do.
- **Token refresh + admin demotion lag.** `is_admin()` reads `profiles`
  on every policy evaluation, so demotion takes effect immediately at the
  DB layer; the frontend's cached `isAdmin` flag in `AuthProvider` will
  briefly show stale truth until next auth event. Acceptable for
  single-operator use.
- **No production yet.** Adding production is its own follow-up: new
  Supabase project, new Vercel project, new long-lived branch
  `production`, identical workflow shape with one more promotion step.
