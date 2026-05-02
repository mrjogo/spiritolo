# Staging Deploy + Auth Lockdown — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock down all data + page access behind Supabase magic-link auth, add a `profiles`/`is_admin` model, restructure the SPA with a public landing page and layout-route guards, add SPA rewrite + migrations CI, and document the staging-branch deploy flow. Hosting infra (Supabase + Vercel project creation) is operator runbook, not code.

**Architecture:** A single migration adds `profiles`, `is_admin()`, the auto-create trigger, and rewrites every existing public-read policy under a 3-tier naming convention (`*_temp_authed_read` / `*_authed_read` / `*_admin_read`). The frontend gets an `AuthProvider` context driving layout-route `<RequireAuth>` and `<RequireAdmin>` guards; the route tree is restructured so adding a new public page requires actively moving it *outside* the wrapper. Vercel handles deploys; one GH Action handles migration push when `staging` branch advances.

**Tech Stack:** Postgres 17 (Supabase), `@supabase/supabase-js` v2, React 19, React Router 7, Vite 8, Vitest 4, `@testing-library/react` 16. Magic-link auth (`signInWithOtp`).

**Spec:** [docs/superpowers/specs/2026-05-02-staging-deploy-and-auth-design.md](docs/superpowers/specs/2026-05-02-staging-deploy-and-auth-design.md)

---

## Conventions

- Repo root: `/workspaces/spiritolo`. All commands run from there unless otherwise noted.
- Web tests: `cd web && npm test -- <vitest pattern>`. Bare `npm test` runs the full suite.
- TS build: `cd web && npm run build`. Lint: `cd web && npm run lint`.
- DB tests / sanity: `supabase db reset --db-url "$SUPABASE_DB_URL" --yes` from repo root after the env-var dance from `CLAUDE.md`.
- Branch: stay on `supabase-staging` (the branch the operator already created). Do NOT push elsewhere.
- Commit subject style: short imperative, e.g. `Add profiles table and admin RLS helpers`.

---

## File Structure

**New (DB):**
- `supabase/migrations/20260502140000_auth_and_rls_lockdown.sql`

**New (frontend code):**
- `web/src/auth/AuthProvider.tsx` — context provider, `useAuth` hook, `signOut`
- `web/src/auth/RequireAuth.tsx` — layout-route guard for tier-(a) and tier-(b)
- `web/src/auth/RequireAdmin.tsx` — layout-route guard for tier-(c), nests inside `RequireAuth`
- `web/src/components/AppLayout.tsx` — `<Header/>` + `<main><Outlet/></main>`
- `web/src/pages/Landing.tsx` — public hero (image + title + sign-in link)
- `web/src/pages/Login.tsx` — magic-link form
- `web/src/pages/AuthCallback.tsx` — post-magic-link landing
- `web/public/landing.jpg` — operator-supplied; placeholder file created in plan

**New (frontend tests):**
- `web/src/auth/AuthProvider.test.tsx`
- `web/src/auth/RequireAuth.test.tsx`
- `web/src/auth/RequireAdmin.test.tsx`
- `web/src/components/AppLayout.test.tsx`
- `web/src/components/Header.test.tsx` (new — exists for sign-out button coverage)
- `web/src/pages/Landing.test.tsx`
- `web/src/pages/Login.test.tsx`
- `web/src/pages/AuthCallback.test.tsx`

**New (infra):**
- `web/vercel.json`
- `.github/workflows/deploy-migrations.yml`

**Modified:**
- `web/src/App.tsx` — restructured route tree
- `web/src/main.tsx` — wrap `<App/>` in `<AuthProvider/>`
- `web/src/components/Header.tsx` — sign-out button, drop `/taxonomy` link from public nav (it's admin-only and uses `RequireAdmin` redirect for protection; we can keep the link visible only when admin via `useAuth`)
- `web/.env.local.example` — note staging URL/key alternative
- `CLAUDE.md` — add a "Hosting" section

---

## Task 1 — DB migration: profiles, admin helper, tier-reclassified policies

**Why:** All later tasks depend on `profiles`, `is_admin()`, and the new policy/grant shape. Doing this first lets us validate the migration locally before any frontend wiring.

**Files:**
- Create: `supabase/migrations/20260502140000_auth_and_rls_lockdown.sql`

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/20260502140000_auth_and_rls_lockdown.sql` with:

```sql
-- Auth + RLS lockdown.
-- See docs/superpowers/specs/2026-05-02-staging-deploy-and-auth-design.md.
--
-- Tier convention (encoded in policy names):
--   *_temp_authed_read  — tier (a): authenticated only for now,
--                         eventually opens to anon. Find with `grep`.
--   *_authed_read       — tier (b): permanently authenticated, no admin gate.
--   *_admin_read        — tier (c): admin only.

------------------------------------------------------------------------
-- 1. profiles + is_admin helper + auto-create trigger
------------------------------------------------------------------------

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
  for select to authenticated
  using (id = auth.uid());

create policy profiles_admin_read on profiles
  for select to authenticated
  using (is_admin());

create or replace function public.handle_new_user() returns trigger
  language plpgsql security definer
  set search_path = public
  as $$
  begin
    insert into profiles (id) values (new.id);
    return new;
  end
  $$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

------------------------------------------------------------------------
-- 2. Revoke all anon access to existing data tables and views
------------------------------------------------------------------------

revoke all on recipes              from anon;
revoke all on recipes_public       from anon;
revoke all on recipe_ingredients   from anon;
revoke all on taxonomy_nodes       from anon;
revoke all on taxonomy_edges       from anon;
revoke all on taxonomy_aliases     from anon;
revoke all on taxonomy_public      from anon;

------------------------------------------------------------------------
-- 3. Drop existing public-read policies; recreate under tier convention
------------------------------------------------------------------------

-- tier (a): recipes (eventually anon)
drop policy if exists recipes_public_read on recipes;
create policy recipes_temp_authed_read on recipes
  for select to authenticated
  using (true);

-- tier (a): recipe_ingredients (eventually anon)
drop policy if exists recipe_ingredients_taxonomy_count_read on recipe_ingredients;
create policy recipe_ingredients_temp_authed_read on recipe_ingredients
  for select to authenticated
  using (true);

-- tier (c): taxonomy_nodes (admin only)
drop policy if exists taxonomy_nodes_public_read on taxonomy_nodes;
create policy taxonomy_nodes_admin_read on taxonomy_nodes
  for select to authenticated
  using (is_admin());

-- tier (c): taxonomy_edges (admin only)
drop policy if exists taxonomy_edges_public_read on taxonomy_edges;
create policy taxonomy_edges_admin_read on taxonomy_edges
  for select to authenticated
  using (is_admin());

-- tier (c): taxonomy_aliases (admin only)
drop policy if exists taxonomy_aliases_public_read on taxonomy_aliases;
create policy taxonomy_aliases_admin_read on taxonomy_aliases
  for select to authenticated
  using (is_admin());
```

- [ ] **Step 2: Apply migration locally and confirm clean reset**

```bash
DB_URL='postgresql://postgres:postgres@192.168.65.254:54322/postgres?sslmode=disable'
supabase db reset --db-url "$DB_URL" --yes
```

Expected: migrations apply without error; CLI prints completion summary; auto-seed runs taxonomy + cocktail-aliases SQL files.

If anon-revoke errors with "role anon does not exist" for one of the tables/views (rare — only if a prior migration ordering changed), inspect the error and add `if exists` guards or split the revoke statements per table.

- [ ] **Step 3: Smoke-test the new policies via psql**

Run:

```bash
psql "$DB_URL" -v ON_ERROR_STOP=1 -c "
  set role anon;
  select count(*) from recipes_public;       -- expect 0 (revoked + RLS)
  select count(*) from taxonomy_public;      -- expect 0
  reset role;
  select pg_get_functiondef('public.is_admin()'::regprocedure);
  select polname from pg_policy
    where polname in (
      'profiles_self_read', 'profiles_admin_read',
      'recipes_temp_authed_read',
      'recipe_ingredients_temp_authed_read',
      'taxonomy_nodes_admin_read', 'taxonomy_edges_admin_read',
      'taxonomy_aliases_admin_read'
    )
    order by polname;
"
```

Expected: anon counts are 0 (or query errors with "permission denied" — either is acceptable proof the revoke worked); `is_admin()` definition prints; the 7 expected policies all listed.

If any policy is missing, the migration didn't apply that statement — re-read the migration file for typos.

- [ ] **Step 4: Restore processed seeds + recipes (sanity for downstream tasks)**

```bash
scripts/refresh-processed-seeds.sh restore
psql "$DB_URL" -v ON_ERROR_STOP=1 -f supabase/seeds/recipes.sql
```

Expected: restore script completes; recipes seed loads ~thousands of rows.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260502140000_auth_and_rls_lockdown.sql
git commit -m "Add profiles, is_admin helper, and tier-reclassified RLS policies"
```

---

## Task 2 — `AuthProvider` context + `useAuth` hook

**Why:** Single source of truth for `user`, `isAdmin`, `loading`, `signOut`. Every later frontend task consumes it.

**Files:**
- Create: `web/src/auth/AuthProvider.tsx`
- Create: `web/src/auth/AuthProvider.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `web/src/auth/AuthProvider.test.tsx`:

```tsx
import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AuthProvider, useAuth } from './AuthProvider';

type AuthChangeHandler = (event: string, session: unknown) => void;
let authChangeHandler: AuthChangeHandler | null = null;
const getSessionMock = vi.fn();
const profileSelectMock = vi.fn();
const signOutMock = vi.fn(async () => ({ error: null }));

vi.mock('../supabase', () => ({
  supabase: {
    auth: {
      getSession: () => getSessionMock(),
      onAuthStateChange: (cb: AuthChangeHandler) => {
        authChangeHandler = cb;
        return { data: { subscription: { unsubscribe: () => {} } } };
      },
      signOut: () => signOutMock(),
    },
    from: (_table: string) => ({
      select: () => ({
        eq: () => ({ maybeSingle: () => profileSelectMock() }),
      }),
    }),
  },
}));

function Probe() {
  const { user, isAdmin, loading } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="user">{user?.id ?? 'none'}</span>
      <span data-testid="admin">{String(isAdmin)}</span>
    </div>
  );
}

beforeEach(() => {
  authChangeHandler = null;
  getSessionMock.mockReset();
  profileSelectMock.mockReset();
  signOutMock.mockClear();
});

describe('AuthProvider', () => {
  it('exposes loading=true on first render and user=null after empty session', async () => {
    getSessionMock.mockResolvedValue({ data: { session: null } });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    expect(screen.getByTestId('loading').textContent).toBe('true');
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('none');
    expect(screen.getByTestId('admin').textContent).toBe('false');
  });

  it('hydrates user from initial session and fetches is_admin from profiles', async () => {
    getSessionMock.mockResolvedValue({
      data: { session: { user: { id: 'u-1' } } },
    });
    profileSelectMock.mockResolvedValue({ data: { is_admin: true }, error: null });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('u-1');
    expect(screen.getByTestId('admin').textContent).toBe('true');
  });

  it('updates user and re-fetches is_admin when auth state changes', async () => {
    getSessionMock.mockResolvedValue({ data: { session: null } });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('none');

    profileSelectMock.mockResolvedValue({ data: { is_admin: false }, error: null });
    await act(async () => {
      authChangeHandler!('SIGNED_IN', { user: { id: 'u-2' } });
    });

    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('u-2'));
    expect(screen.getByTestId('admin').textContent).toBe('false');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- AuthProvider
```

Expected: FAIL — `Cannot find module './AuthProvider'` or similar.

- [ ] **Step 3: Implement `AuthProvider.tsx`**

Create `web/src/auth/AuthProvider.tsx`:

```tsx
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { Session, User } from '@supabase/supabase-js';
import { supabase } from '../supabase';

type AuthContextValue = {
  user: User | null;
  session: Session | null;
  isAdmin: boolean;
  loading: boolean;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const fetchSeq = useRef(0);

  const fetchAdminFlag = useCallback(async (userId: string | null) => {
    const seq = ++fetchSeq.current;
    if (!userId) {
      if (seq === fetchSeq.current) setIsAdmin(false);
      return;
    }
    const { data } = await supabase
      .from('profiles')
      .select('is_admin')
      .eq('id', userId)
      .maybeSingle();
    if (seq !== fetchSeq.current) return;
    setIsAdmin(Boolean(data?.is_admin));
  }, []);

  useEffect(() => {
    let mounted = true;
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (!mounted) return;
      setSession(data.session ?? null);
      await fetchAdminFlag(data.session?.user?.id ?? null);
      if (!mounted) return;
      setLoading(false);
    })();

    const { data: sub } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next ?? null);
      void fetchAdminFlag(next?.user?.id ?? null);
    });

    return () => {
      mounted = false;
      sub.subscription.unsubscribe();
    };
  }, [fetchAdminFlag]);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: session?.user ?? null,
      session,
      isAdmin,
      loading,
      signOut,
    }),
    [session, isAdmin, loading, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- AuthProvider
```

Expected: PASS, all 3 tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/auth/AuthProvider.tsx web/src/auth/AuthProvider.test.tsx
git commit -m "Add AuthProvider context and useAuth hook"
```

---

## Task 3 — `RequireAuth` layout-route guard

**Why:** Tier-(a)/(b) gating. Wraps a group of routes with `<Outlet/>`-based guarding so adding a protected page can't accidentally leak.

**Files:**
- Create: `web/src/auth/RequireAuth.tsx`
- Create: `web/src/auth/RequireAuth.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `web/src/auth/RequireAuth.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom';
import { RequireAuth } from './RequireAuth';

const useAuthMock = vi.fn();
vi.mock('./AuthProvider', () => ({ useAuth: () => useAuthMock() }));

function LoginSpy() {
  const [params] = useSearchParams();
  return <div>login-page next={params.get('next') ?? 'none'}</div>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<RequireAuth />}>
          <Route path="/recipes" element={<div>recipes-page</div>} />
        </Route>
        <Route path="/login" element={<LoginSpy />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('RequireAuth', () => {
  it('renders nothing while loading', () => {
    useAuthMock.mockReturnValue({ user: null, loading: true });
    renderAt('/recipes');
    expect(screen.queryByText('recipes-page')).toBeNull();
    expect(screen.queryByText(/login-page/)).toBeNull();
  });

  it('renders child route when user is present', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });
    renderAt('/recipes');
    expect(screen.getByText('recipes-page')).toBeInTheDocument();
  });

  it('redirects to /login with the encoded next param when no user', () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    renderAt('/recipes?foo=bar');
    expect(
      screen.getByText('login-page next=/recipes?foo=bar'),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- RequireAuth
```

Expected: FAIL — `Cannot find module './RequireAuth'`.

- [ ] **Step 3: Implement `RequireAuth.tsx`**

Create `web/src/auth/RequireAuth.tsx`:

```tsx
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from './AuthProvider';

export function RequireAuth() {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return null;
  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <Outlet />;
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- RequireAuth
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/auth/RequireAuth.tsx web/src/auth/RequireAuth.test.tsx
git commit -m "Add RequireAuth layout-route guard"
```

---

## Task 4 — `RequireAdmin` layout-route guard

**Why:** Tier-(c) gating. Nests inside `RequireAuth`, so by the time it runs, `user` is guaranteed.

**Files:**
- Create: `web/src/auth/RequireAdmin.tsx`
- Create: `web/src/auth/RequireAdmin.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `web/src/auth/RequireAdmin.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { RequireAdmin } from './RequireAdmin';

const useAuthMock = vi.fn();
vi.mock('./AuthProvider', () => ({ useAuth: () => useAuthMock() }));

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/recipes" element={<div>recipes-page</div>} />
        <Route element={<RequireAdmin />}>
          <Route path="/taxonomy" element={<div>taxonomy-page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('RequireAdmin', () => {
  it('renders child route when user is admin', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, isAdmin: true, loading: false });
    renderAt('/taxonomy');
    expect(screen.getByText('taxonomy-page')).toBeInTheDocument();
  });

  it('redirects to /recipes when authed but not admin', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, isAdmin: false, loading: false });
    renderAt('/taxonomy');
    expect(screen.getByText('recipes-page')).toBeInTheDocument();
  });

  it('renders nothing while loading', () => {
    useAuthMock.mockReturnValue({ user: null, isAdmin: false, loading: true });
    renderAt('/taxonomy');
    expect(screen.queryByText('taxonomy-page')).toBeNull();
    expect(screen.queryByText('recipes-page')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- RequireAdmin
```

Expected: FAIL.

- [ ] **Step 3: Implement `RequireAdmin.tsx`**

Create `web/src/auth/RequireAdmin.tsx`:

```tsx
import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from './AuthProvider';

export function RequireAdmin() {
  const { isAdmin, loading } = useAuth();
  if (loading) return null;
  if (!isAdmin) return <Navigate to="/recipes" replace />;
  return <Outlet />;
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- RequireAdmin
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/auth/RequireAdmin.tsx web/src/auth/RequireAdmin.test.tsx
git commit -m "Add RequireAdmin layout-route guard"
```

---

## Task 5 — Login page (magic-link form)

**Files:**
- Create: `web/src/pages/Login.tsx`
- Create: `web/src/pages/Login.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `web/src/pages/Login.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { Login } from './Login';

const signInMock = vi.fn();
vi.mock('../supabase', () => ({
  supabase: { auth: { signInWithOtp: (args: unknown) => signInMock(args) } },
}));

beforeEach(() => {
  signInMock.mockReset();
  signInMock.mockResolvedValue({ data: {}, error: null });
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Login />
    </MemoryRouter>,
  );
}

describe('Login', () => {
  it('calls signInWithOtp with the typed email and a callback URL preserving ?next=', async () => {
    const user = userEvent.setup();
    renderAt('/login?next=%2Frecipes%2Fabc');

    await user.type(screen.getByLabelText(/email/i), 'me@example.com');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    expect(signInMock).toHaveBeenCalledTimes(1);
    const call = signInMock.mock.calls[0][0] as {
      email: string;
      options: { emailRedirectTo: string };
    };
    expect(call.email).toBe('me@example.com');
    expect(call.options.emailRedirectTo).toMatch(
      /\/auth\/callback\?next=%2Frecipes%2Fabc$/,
    );
  });

  it('shows a confirmation after a successful submit', async () => {
    const user = userEvent.setup();
    renderAt('/login');

    await user.type(screen.getByLabelText(/email/i), 'me@example.com');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    expect(await screen.findByText(/check your email/i)).toBeInTheDocument();
  });

  it('shows an error message when signInWithOtp returns an error', async () => {
    signInMock.mockResolvedValue({ data: null, error: { message: 'rate limit' } });
    const user = userEvent.setup();
    renderAt('/login');

    await user.type(screen.getByLabelText(/email/i), 'me@example.com');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    expect(await screen.findByText(/rate limit/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- Login
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `Login.tsx`**

Create `web/src/pages/Login.tsx`:

```tsx
import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { supabase } from '../supabase';

export function Login() {
  const [params] = useSearchParams();
  const next = params.get('next') ?? '/recipes';
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<
    | { kind: 'idle' }
    | { kind: 'sending' }
    | { kind: 'sent' }
    | { kind: 'error'; message: string }
  >({ kind: 'idle' });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setStatus({ kind: 'sending' });
    const emailRedirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(
      next,
    )}`;
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo },
    });
    if (error) {
      setStatus({ kind: 'error', message: error.message });
      return;
    }
    setStatus({ kind: 'sent' });
  }

  return (
    <main className="page page--login">
      <h1>Spiritolo</h1>
      <form onSubmit={onSubmit}>
        <label>
          Email
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </label>
        <button type="submit" disabled={status.kind === 'sending'}>
          Send magic link
        </button>
      </form>
      {status.kind === 'sent' && <p>Check your email for a sign-in link.</p>}
      {status.kind === 'error' && <p role="alert">{status.message}</p>}
    </main>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- Login
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Login.tsx web/src/pages/Login.test.tsx
git commit -m "Add /login page with magic-link form"
```

---

## Task 6 — `AuthCallback` page

**Files:**
- Create: `web/src/pages/AuthCallback.tsx`
- Create: `web/src/pages/AuthCallback.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `web/src/pages/AuthCallback.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthCallback } from './AuthCallback';

const useAuthMock = vi.fn();
vi.mock('../auth/AuthProvider', () => ({ useAuth: () => useAuthMock() }));

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="/recipes" element={<div>recipes-page</div>} />
        <Route path="/recipes/:id" element={<div>detail-page</div>} />
        <Route path="/login" element={<div>login-page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('AuthCallback', () => {
  it('shows a working message while auth is still loading', () => {
    useAuthMock.mockReturnValue({ user: null, loading: true });
    renderAt('/auth/callback?next=%2Frecipes');
    expect(screen.getByText(/signing you in/i)).toBeInTheDocument();
  });

  it('navigates to ?next= once user appears', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });
    renderAt('/auth/callback?next=%2Frecipes%2Fabc');
    expect(screen.getByText('detail-page')).toBeInTheDocument();
  });

  it('falls back to /recipes when ?next= missing', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });
    renderAt('/auth/callback');
    expect(screen.getByText('recipes-page')).toBeInTheDocument();
  });

  it('navigates to /login if loading finishes with no user (link expired/invalid)', () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    renderAt('/auth/callback');
    expect(screen.getByText('login-page')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- AuthCallback
```

Expected: FAIL.

- [ ] **Step 3: Implement `AuthCallback.tsx`**

Create `web/src/pages/AuthCallback.tsx`:

```tsx
import { Navigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';

export function AuthCallback() {
  const { user, loading } = useAuth();
  const [params] = useSearchParams();
  const next = params.get('next') || '/recipes';

  if (loading) {
    return (
      <main className="page page--auth-callback">
        <p>Signing you in…</p>
      </main>
    );
  }

  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={next} replace />;
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- AuthCallback
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/AuthCallback.tsx web/src/pages/AuthCallback.test.tsx
git commit -m "Add /auth/callback page that hands off to ?next= after sign-in"
```

---

## Task 7 — Landing page

**Files:**
- Create: `web/src/pages/Landing.tsx`
- Create: `web/src/pages/Landing.test.tsx`
- Create: `web/public/landing.jpg` (1×1 placeholder; operator will overwrite with real image)

- [ ] **Step 1: Place an image placeholder**

Create a 1×1 black JPEG at `web/public/landing.jpg` (any byte sequence valid as JPEG works for tests; the operator replaces with the real image during deploy):

```bash
# 1×1 black JPEG. base64 → file.
mkdir -p web/public && \
  echo '/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDAREAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AVN//2Q==' \
  | base64 -d > web/public/landing.jpg && \
  ls -l web/public/landing.jpg
```

Expected: file created, size ~250–500 bytes.

- [ ] **Step 2: Write the failing test**

Create `web/src/pages/Landing.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Landing } from './Landing';

const useAuthMock = vi.fn();
vi.mock('../auth/AuthProvider', () => ({ useAuth: () => useAuthMock() }));

function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/recipes" element={<div>recipes-page</div>} />
        <Route path="/login" element={<div>login-page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Landing', () => {
  it('renders title, image, and a sign-in link when logged out', () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    renderApp();
    expect(screen.getByRole('heading', { name: /spiritolo/i })).toBeInTheDocument();
    expect(screen.getByRole('img')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /sign in/i })).toHaveAttribute(
      'href',
      '/login',
    );
  });

  it('renders nothing visible while auth is loading', () => {
    useAuthMock.mockReturnValue({ user: null, loading: true });
    renderApp();
    expect(screen.queryByRole('heading', { name: /spiritolo/i })).toBeNull();
  });

  it('redirects to /recipes when already logged in', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });
    renderApp();
    expect(screen.getByText('recipes-page')).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd web && npm test -- Landing
```

Expected: FAIL.

- [ ] **Step 4: Implement `Landing.tsx`**

Create `web/src/pages/Landing.tsx`:

```tsx
import { Link, Navigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';

export function Landing() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to="/recipes" replace />;

  return (
    <main className="page page--landing">
      <img src="/landing.jpg" alt="" className="landing__image" />
      <h1 className="landing__title">Spiritolo</h1>
      <Link to="/login" className="landing__signin">
        Sign in
      </Link>
    </main>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd web && npm test -- Landing
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/Landing.tsx web/src/pages/Landing.test.tsx web/public/landing.jpg
git commit -m "Add public Landing page (image + title + sign-in)"
```

---

## Task 8 — `AppLayout` (Header + outlet wrapper)

**Why:** Sit between `<RequireAuth>` and the inner pages so every authed page renders inside Header+main without per-page boilerplate.

**Files:**
- Create: `web/src/components/AppLayout.tsx`
- Create: `web/src/components/AppLayout.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `web/src/components/AppLayout.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AppLayout } from './AppLayout';

vi.mock('./Header', () => ({ Header: () => <header>mock-header</header> }));

describe('AppLayout', () => {
  it('renders Header and the matched child route via Outlet', () => {
    render(
      <MemoryRouter initialEntries={['/recipes']}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/recipes" element={<div>child-page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('mock-header')).toBeInTheDocument();
    expect(screen.getByText('child-page')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- AppLayout
```

Expected: FAIL.

- [ ] **Step 3: Implement `AppLayout.tsx`**

Create `web/src/components/AppLayout.tsx`:

```tsx
import { Outlet } from 'react-router-dom';
import { Header } from './Header';

export function AppLayout() {
  return (
    <>
      <Header />
      <Outlet />
    </>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- AppLayout
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/AppLayout.tsx web/src/components/AppLayout.test.tsx
git commit -m "Add AppLayout (Header + Outlet) for authed routes"
```

---

## Task 9 — Header: sign-out button + admin-only Taxonomy link

**Why:** Header today renders a permanent `/taxonomy` nav link to anyone. After lockdown, only admins should see it. Add a sign-out button visible only when authed.

**Files:**
- Modify: `web/src/components/Header.tsx`
- Create: `web/src/components/Header.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `web/src/components/Header.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Header } from './Header';

const useAuthMock = vi.fn();
const signOutMock = vi.fn(async () => {});
vi.mock('../auth/AuthProvider', () => ({
  useAuth: () => ({ ...useAuthMock(), signOut: signOutMock }),
}));

beforeEach(() => signOutMock.mockClear());

function renderHeader() {
  return render(
    <MemoryRouter initialEntries={['/recipes']}>
      <Routes>
        <Route path="/recipes" element={<Header />} />
        <Route path="/" element={<div>landing-page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Header', () => {
  it('shows Recipes link and Sign out for an authed non-admin', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, isAdmin: false, loading: false });
    renderHeader();
    expect(screen.getByRole('link', { name: /recipes/i })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /taxonomy/i })).toBeNull();
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
  });

  it('shows Taxonomy link when isAdmin', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, isAdmin: true, loading: false });
    renderHeader();
    expect(screen.getByRole('link', { name: /taxonomy/i })).toBeInTheDocument();
  });

  it('clicking Sign out calls signOut and navigates to /', async () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, isAdmin: false, loading: false });
    const user = userEvent.setup();
    renderHeader();
    await user.click(screen.getByRole('button', { name: /sign out/i }));
    expect(signOutMock).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('landing-page')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- Header
```

Expected: FAIL — old Header component doesn't read auth, doesn't render sign out.

- [ ] **Step 3: Replace `Header.tsx`**

Replace the contents of `web/src/components/Header.tsx`:

```tsx
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';

export function Header() {
  const { user, isAdmin, signOut } = useAuth();
  const navigate = useNavigate();

  async function onSignOut() {
    await signOut();
    navigate('/');
  }

  return (
    <header className="site-header">
      <Link to="/recipes" className="site-header__brand">SPIRITOLO</Link>
      <nav className="site-header__nav">
        <Link to="/recipes">Recipes</Link>
        {isAdmin && <Link to="/taxonomy">Taxonomy</Link>}
      </nav>
      {user && (
        <button type="button" onClick={onSignOut} className="site-header__signout">
          Sign out
        </button>
      )}
    </header>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- Header
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/Header.tsx web/src/components/Header.test.tsx
git commit -m "Header: hide /taxonomy from non-admins, add Sign out button"
```

---

## Task 10 — Restructure `App.tsx` route tree + wrap `<App/>` in `<AuthProvider/>`

**Why:** Wires every previous component into the routing tree under the layout-route guards. This is the change that actually locks down access.

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/main.tsx`
- Possibly modify (only if Step 3 reveals collateral failures): `web/src/pages/RecipeList.test.tsx`, `web/src/pages/RecipeDetail.test.tsx`, `web/src/pages/Taxonomy.test.tsx`

- [ ] **Step 1: Replace `App.tsx`**

Replace the contents of `web/src/App.tsx`:

```tsx
import { lazy, Suspense } from 'react';
import { Routes, Route } from 'react-router-dom';
import { AppLayout } from './components/AppLayout';
import { RequireAuth } from './auth/RequireAuth';
import { RequireAdmin } from './auth/RequireAdmin';
import { Landing } from './pages/Landing';
import { Login } from './pages/Login';
import { AuthCallback } from './pages/AuthCallback';
import { RecipeList } from './pages/RecipeList';
import { RecipeDetail } from './pages/RecipeDetail';
import { ErrorPage } from './components/ErrorPage';

// Lazy-load Taxonomy to keep react-force-graph-2d + d3-force out of the
// recipe-page bundle (~600 KB saved on first paint of /recipes).
const Taxonomy = lazy(() =>
  import('./pages/Taxonomy').then((m) => ({ default: m.Taxonomy })),
);

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/auth/callback" element={<AuthCallback />} />

      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route path="/recipes" element={<RecipeList />} />
          <Route path="/recipes/:id" element={<RecipeDetail />} />

          <Route element={<RequireAdmin />}>
            <Route
              path="/taxonomy"
              element={
                <Suspense fallback={<div className="page">Loading taxonomy…</div>}>
                  <Taxonomy />
                </Suspense>
              }
            />
          </Route>
        </Route>
      </Route>

      <Route
        path="*"
        element={<ErrorPage title="Page not found" message="That URL doesn't match any page." />}
      />
    </Routes>
  );
}
```

- [ ] **Step 2: Wrap `<App/>` in `<AuthProvider/>` in `main.tsx`**

Replace `web/src/main.tsx` with:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { AuthProvider } from './auth/AuthProvider';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
```

- [ ] **Step 3: Run the full test suite to find collateral damage**

```bash
cd web && npm test
```

Pre-check confirms no existing test renders `<App />`, and `RecipeList`/`RecipeDetail`/`Taxonomy` page tests render their pages in isolation under `<MemoryRouter>` without Header, so they should be unaffected by the route restructure and don't need `AuthProvider`.

Expected: PASS. If a page test does fail because it transitively renders something that calls `useAuth`, mock the auth module at the top of that test file:

```tsx
vi.mock('../auth/AuthProvider', () => ({
  useAuth: () => ({
    user: { id: 'u-test' },
    session: null,
    isAdmin: true,
    loading: false,
    signOut: vi.fn(),
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
```

- [ ] **Step 4: TypeScript build**

```bash
cd web && npm run build
```

Expected: SUCCESS — clean build, no TS errors.

- [ ] **Step 5: Lint**

```bash
cd web && npm run lint
```

Expected: SUCCESS.

- [ ] **Step 6: Commit**

```bash
git add web/src/App.tsx web/src/main.tsx
# add any test files you had to mock-patch in Step 3 above
git commit -m "Restructure routes under layout-route auth guards; wrap app in AuthProvider"
```

---

## Task 11 — `web/vercel.json` (SPA deep-link rewrite)

**Why:** Without this, hard-refreshing `/recipes/<id>` returns 404 from Vercel's static handler.

**Files:**
- Create: `web/vercel.json`

- [ ] **Step 1: Create the file**

Create `web/vercel.json`:

```json
{
  "rewrites": [
    { "source": "/(.*)", "destination": "/index.html" }
  ]
}
```

- [ ] **Step 2: Sanity-check valid JSON**

```bash
python3 -c "import json; json.load(open('web/vercel.json'))" && echo OK
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add web/vercel.json
git commit -m "Add SPA deep-link rewrite for Vercel"
```

---

## Task 12 — `.github/workflows/deploy-migrations.yml` (push migrations to staging)

**Why:** When `staging` branch advances with new migrations, push them to the remote Supabase project. Without this, schema drift between staging branch and the staging DB happens silently.

**Files:**
- Create: `.github/workflows/deploy-migrations.yml`

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/deploy-migrations.yml`:

```yaml
name: Deploy migrations to staging

on:
  push:
    branches: [staging]
    paths:
      - 'supabase/migrations/**'

jobs:
  push:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v6

      - name: Set up Supabase CLI
        uses: supabase/setup-cli@v1
        with:
          version: latest

      - name: Push migrations to staging
        env:
          STAGING_DB_URL: ${{ secrets.SUPABASE_STAGING_DB_URL }}
        run: |
          if [ -z "$STAGING_DB_URL" ]; then
            echo "SUPABASE_STAGING_DB_URL is not set" >&2
            exit 1
          fi
          supabase db push --db-url "$STAGING_DB_URL" --include-all
```

- [ ] **Step 2: Validate YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-migrations.yml'))" && echo OK
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy-migrations.yml
git commit -m "Add CI workflow that pushes migrations to staging on staging-branch updates"
```

---

## Task 13 — `.env.local.example` update + `CLAUDE.md` "Hosting" section

**Files:**
- Modify: `web/.env.local.example`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `web/.env.local.example`**

Replace `web/.env.local.example` with:

```
# Local dev (default).
# Copy to .env.local and fill in the publishable key from `supabase status` on the Mac host.
# The publishable key (sb_publishable_...) replaced the legacy anon key in Nov 2025.
VITE_SUPABASE_URL=http://localhost:54321
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_your-local-key-here

# To point local dev at the staging project instead, paste the URL + publishable
# key from the spiritolo-staging project's API settings page on supabase.com.
# All access still requires authentication.
```

- [ ] **Step 2: Add a "Hosting" section to `CLAUDE.md`**

Append to `CLAUDE.md` (insert before the existing "## Web UI" section so deploy mechanics live near the runtime they affect; if uncertain, append at end):

```markdown
## Hosting

The app is hosted on Supabase + Vercel free tiers under the project name
`spiritolo-staging`. There is no separate production environment yet.

**Branches:**

- `main` — integration trunk. PRs from `claude/<topic>` branches land here.
  Deploys nowhere.
- `staging` — deploy trunk. Both Vercel and the migrations workflow watch
  this branch.

**Promotion (run locally):**

```bash
git checkout staging
git merge --ff-only main
git push
```

If `--ff-only` refuses, something landed on `staging` that isn't on `main`.
Investigate before forcing.

**Frontend deploys:** Vercel handles them natively on every push to
`staging` (production) and every PR (preview).

**Migrations:** `.github/workflows/deploy-migrations.yml` pushes any
migration changes to staging when `staging` advances. Requires the
`SUPABASE_STAGING_DB_URL` repo secret.

**Auth:** Magic-link only, no self-signup. Create users from Supabase
Studio (Authentication → Users → Invite). After their first sign-in,
flip `profiles.is_admin` in the table editor to grant admin access.

See [docs/superpowers/specs/2026-05-02-staging-deploy-and-auth-design.md](docs/superpowers/specs/2026-05-02-staging-deploy-and-auth-design.md)
for the bootstrap runbook and RLS tier conventions.
```

- [ ] **Step 3: Commit**

```bash
git add web/.env.local.example CLAUDE.md
git commit -m "Document hosting (branches, promote flow, auth)"
```

---

## Task 14 — Manual verification against local Supabase

**Why:** Before the operator runs the staging bootstrap, confirm end-to-end against local that auth works, RLS gates as intended, and the route tree behaves.

**Files:**
- (none — manual verification)

- [ ] **Step 1: Reset + restore local DB**

```bash
DB_URL='postgresql://postgres:postgres@192.168.65.254:54322/postgres?sslmode=disable'
supabase db reset --db-url "$DB_URL" --yes
scripts/refresh-processed-seeds.sh restore
psql "$DB_URL" -v ON_ERROR_STOP=1 -f supabase/seeds/recipes.sql
```

- [ ] **Step 2: Create a local auth user via Studio**

In Supabase Studio (http://localhost:54323):
- Authentication → Users → "Add user" → "Create new user" → email + auto-confirm.
- Note the new user's UUID.

- [ ] **Step 3: Verify the trigger created a `profiles` row**

```bash
psql "$DB_URL" -c "select id, is_admin from profiles;"
```

Expected: one row matching the user UUID, `is_admin = false`.

- [ ] **Step 4: Start the dev server**

```bash
cd web && npm run dev
```

Open http://localhost:5173.

- [ ] **Step 5: Verify logged-out behavior**
  - `/` shows Landing (image + title + Sign in).
  - `/recipes` redirects to `/login?next=%2Frecipes`.
  - `/recipes/abc` redirects to `/login?next=%2Frecipes%2Fabc`.
  - `/taxonomy` redirects to `/login?next=%2Ftaxonomy`.

- [ ] **Step 6: Sign in via Studio (magic link OTP local trick)**

In Studio Authentication → Users, find the test user → click the row → use the "Send magic link" button. Mailpit (or whatever the local Supabase mail catcher is — `http://localhost:54324` for the Supabase Inbucket UI) holds the mail. Click the link.

- [ ] **Step 7: Verify logged-in non-admin behavior**
  - After magic-link redirect, you land on `/recipes` (or the `next=` target).
  - Header shows "Recipes" + "Sign out" — no "Taxonomy" link.
  - `/recipes/<some-id>` loads RecipeDetail.
  - Manual nav to `/taxonomy` redirects to `/recipes`.
  - Sign out → returns to `/`.

- [ ] **Step 8: Promote to admin and re-verify**

```bash
psql "$DB_URL" -c "update profiles set is_admin = true where id = '<user-uuid>';"
```

Sign out and back in (so `AuthProvider` refetches the flag). Verify:
- Header now shows "Taxonomy" link.
- `/taxonomy` loads.

- [ ] **Step 9: Verify anon REST blockade**

```bash
ANON_KEY=$(supabase status --output json 2>/dev/null | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['ANON_KEY'])")
curl -s -H "apikey: $ANON_KEY" \
  "http://localhost:54321/rest/v1/recipes_public?select=id&limit=1" | head
```

Expected: empty array `[]` or a permission-denied error — never a row.

If `supabase status` doesn't output JSON in this CLI version, grab the anon key from the textual output instead.

- [ ] **Step 10: No commit (verification only) — record findings**

If anything in steps 5–9 deviated from expected, fix the underlying code in the relevant earlier task and re-verify. Once everything passes, this plan's code work is complete; the operator runs the bootstrap runbook (spec §6) next.

---

## Out-of-scope (deliberately left to operator runbook)

These steps are documented in the spec but are not implementation tasks because they require operator credentials and external service interaction:

- Creating the Supabase staging project at supabase.com.
- Enabling Email provider + magic-link only in the staging project's Auth settings.
- Setting Site URL + redirect allow-list in staging Auth.
- Creating the Vercel project, pointing root to `web/`, choosing `staging` as the production branch, and setting `VITE_SUPABASE_URL` + `VITE_SUPABASE_PUBLISHABLE_KEY` env vars.
- Adding the `SUPABASE_STAGING_DB_URL` GH Action secret.
- The one-shot bootstrap (push schema + push seeds via psql + run deterministic recompute against staging + create the operator user + flip `is_admin`).

The bootstrap script is intentionally ephemeral (per spec) — keep it in `/tmp/` or your scratch dir; do not commit.
