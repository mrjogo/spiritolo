# Spiritolo — Future Direction

## Vision

A worldwide compendium of cocktail recipes — every recipe ever published online, with AI-powered substitutions, a graph of related recipes, and a data source for RecipeGF.

## Phase 1: Scraper (current)

Fetch and archive raw HTML from cocktail recipe sites. See `docs/superpowers/specs/2026-04-12-scraper-design.md`.

## Phase 2: Extractor

Read archived HTML from local disk, extract structured recipe data, write directly to Supabase Postgres.

Key decisions already made:
- Extract structured data using LLM (HTML varies too much across sites for hand-written parsers)
- Write directly to Supabase (no intermediate files) — use Supabase local dev as a checkpoint/staging environment, then bulk upload to production
- Schema lives in Supabase migrations (`supabase/migrations/`)
- A `reviewed` field or similar can gate extracted recipes before they're considered production-ready

Data to extract per recipe:
- Name, description, instructions
- Ingredients (structured: amount, unit, ingredient name)
- Source URL, source site name, attribution
- Category/tags if available
- Original Schema.org JSON-LD if present (already validated during scraping)

## Phase 3: App

TBD. Whatever consumes the data — API, web UI, data export. Supabase is the backend.

## Long-Term Features

- **AI substitutions** — given a recipe and available ingredients, suggest substitutions
- **Recipe graph** — related recipes via ingredient similarity, technique similarity, flavor profile. Possibly using embeddings / vector database (Supabase pgvector)
- **Data source for RecipeGF** (`/Users/ruddick/code-projects/RecipeGF`) — spiritolo provides structured cocktail recipe data that RecipeGF consumes
- **Deduplication** — fuzzy matching across sources (same cocktail, different recipes)
- **Completeness tracking** — how many known cocktails are covered, what's missing

## Infrastructure

- **Database:** Supabase (hosted Postgres) — free tier covers 15K recipes easily (~100MB)
- **Raw HTML archive:** local disk on Ubuntu desktop (~1.5GB)
- **Scraping:** ScraperAPI for Cloudflare bypass
- **Vector storage (future):** Supabase pgvector
