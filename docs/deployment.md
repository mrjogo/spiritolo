# Deployment

There is no production environment yet. Everything described here is the staging
setup, which doubles as the live demo.

## Branches

- **`main`** — integration trunk. Feature branches (`claude/<topic>-<id>`) merge
  here via PR. Deploys nowhere.
- **`staging`** — deploy trunk. Pushing here triggers Vercel and (if migrations
  changed) the Supabase migration workflow.

Promote with a fast-forward only:

```bash
git checkout staging
git merge --ff-only main
git push
```

If `--ff-only` refuses, something landed on `staging` that isn't on `main`.
Investigate before forcing.

## Frontend — Vercel

- Project: `spiritolo-staging`
- URL: <https://spiritolo-staging.vercel.app>
- Triggers: every push to `staging` (production deploy), every PR (preview).

The frontend reads `recipes_public` from Supabase via the publishable key
(`sb_publishable_…`). No backend, no server-side env.

## Database — Supabase

- Project: `spiritolo-staging`
- URL: <https://atvlzbgrquiseczzeczn.supabase.co>
- Studio: dashboard at supabase.com (signed in as the project owner).

This Supabase project is the source of truth for pipeline data
(`recipes`, `recipe_ingredients`, `recipe_clusters`, taxonomy growth, etc.).
Pipeline runs mutate this data directly — the worker daemon over the `jobs`
queue, or the CLI pointed at it; one-off SQL hand-edits and the curation UI
hit staging directly.

### Migrations

[.github/workflows/deploy-migrations.yml](../.github/workflows/deploy-migrations.yml)
runs on every push to `staging`. It detects migration changes and applies them
via `supabase db push --include-all`. Requires the `SUPABASE_STAGING_DB_URL`
repo secret.

The only seed file is `supabase/seeds/dev_admin_user.local-only.sql`,
which pre-creates a magic-link admin for local dev. The seed self-aborts
on any non-`*.local.{test,dev}` user, so it's safe by construction, but
it's never applied to staging anyway — Supabase only runs seeds on `db
reset`, which we don't run against the hosted project. Reference data
(taxonomy nodes, cocktail aliases, recipes, etc.) lives on staging and
is curated there directly via the admin UI. Local dev populates this
data by restoring a staging backup; see [backups.md](backups.md).

## Email — Resend

Magic-link auth emails go through Resend. We have **not** verified a custom
domain, so Resend will only deliver to the owner email (the address that owns
the Resend account). Inviting any other email address will appear to succeed in
Supabase Studio but the message will be dropped.

Practical consequence: staging is single-user. To onboard another person we'd
need to verify a domain in Resend first.

## Auth

Magic-link only — no self-signup. To add a user:

1. Supabase Studio → Authentication → Users → **Invite user**.
2. They click the magic link in the email. (Subject to the Resend constraint
   above.)
3. After their first sign-in, flip `profiles.is_admin` to `true` in the table
   editor to grant admin access.
