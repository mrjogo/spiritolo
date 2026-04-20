# Classify URLs

One-time manual classification of URLs by structure and content. Run this in Claude Code after sitemap discovery populates the database.

## Prerequisites

- Sitemaps have been discovered: `python3 -m scraper.src.discover`
- Database exists at `data/scraper.db` with `content_type` column

## After classification

Run the fetch pipeline, which will only fetch `likely_drink_recipe` pages:

```bash
SCRAPERAPI_KEY=your-key python3 -m scraper.src.fetch --site {site_name} --limit 50
```

Start with a small `--limit` to verify the drink confirmation logic before doing a full run.

## Prompt

Copy and paste the following into Claude Code:

---

Classify every unclassified URL in `data/scraper.db` into exactly one of six categories. The decision for each URL is made by reading that URL — not by pattern-matching keywords in slugs.

**Categories:**
- `likely_drink_recipe` — an individual drink recipe, alcoholic or non-alcoholic (single drink name, mixing method, drink ingredient).
- `likely_food_recipe` — an individual food recipe (single dish, cooking method, food ingredient).
- `likely_drink_article` — drink-related but not a single recipe: articles, listicles, bar guides, "best-of" roundups, technique explainers, news pieces, glossary entries, ingredient explainers.
- `likely_food_article` — food-related but not a single recipe: articles, tips, reviews, restaurant guides, health pieces, cooking technique explainers.
- `likely_junk` — structural/meta pages with no editorial content. Three groups: structural/legal (about, FAQ, privacy, contact, terms, sitemap); navigation/index (author bios, tag/category/topic indexes); commercial (product reviews, brand pages, retail/affiliate, advertise/subscribe).
- `likely_user_generated` — user-submitted content from a community/forum sitemap, not editorially curated. **Note:** guest authors are editorial; their articles do NOT belong here.

**Signal priority** (strongest to weakest): path hierarchy (`/recipes/`, `/articles/`, `/tag/`, `/about/`) → subdomain (`recipes.example.com` vs `news.example.com`) → `sitemap_source` (the sitemap file the URL came from) → slug content. The slug is the **weakest** signal — read it as a sentence, never as a bag of keywords to match.

## How to classify each URL

Work through this sequence per row — not a keyword scan:

1. **Look at the path segment after the domain.** A recognizable section determines most of the answer:
   - `/recipes/<single-slug>/` → recipe (drink vs food still needs the slug)
   - `/articles/<slug>/` → article (drink vs food still needs the slug)
   - `/tag/`, `/category/`, `/topics/` → junk (taxonomy pages)
   - `/author/`, `/by-` → junk (author bio/index pages — guest authors are still editorial, not user-generated)
   - `/brands/`, `/venues/`, `/shop/`, `/store/` → junk (retail/structural)
   - `/about/`, `/privacy/`, `/contact/`, `/faq/`, `/sitemap`, `/advertise/`, `/subscribe/`, `/terms/` → junk
   - `/glossary/`, `/az-glossary/` → article (reference entry)
2. **Root-level paths (`/<slug>/`)** are usually articles or landing pages, not recipes — even on a recipe-heavy site. Series landing pages (`/spirit-forward/`, `/the-gin-companion-with-plymouth-gin/`) live at root.
3. **Read the slug as a sentence.** Ask: "What would I expect to see if I clicked this link?"
   - "household-uses-for-vodka" → article about *uses for* vodka. Not a recipe.
   - "what-drinking-milk-every-day-does-to-your-body" → health article. Not a recipe.
   - "best-gin-for-negroni" → buyers' roundup. Not a recipe.
   - "how-to-stock-a-home-bar" → a guide. Not a recipe.
   - "trader-joes-cocktail-shaker-review" → product review → `likely_junk`.
   - "blueberry-jello-mold-recipe" → individual recipe. Yes, a recipe.
4. **Tie-breaking, only when steps 1–3 leave a genuine ambiguity:** drink vs food → lean drink; recipe vs article → lean recipe.

## Failure modes from prior runs (do not repeat)

Real misclassifications caused by reaching for slug-keyword shortcuts. Each row is a slug substring match that beat sentence-level reading.

| URL | Wrongly classified as | Correct classification | Why the shortcut failed |
| --- | --- | --- | --- |
| `marthastewart.com/marthas-flower-arranging-secrets` | `likely_drink_recipe` | `likely_food_article` | Catch-all default applied; slug had no drink content at all |
| `marthastewart.com/is-sourdough-ultraprocessed-...` | `likely_drink_recipe` | `likely_food_article` | Health article about bread |
| `marthastewart.com/what-drinking-milk-every-day-does-to-your-body` | `likely_drink_recipe` | `likely_food_article` | "drinking" matched a drink keyword; page is about milk |
| `marthastewart.com/household-uses-for-vodka-...` | `likely_drink_recipe` | `likely_drink_article` | "vodka" matched; page is about cleaning uses |
| `simplyrecipes.com/best-gin-for-negroni-bartenders` | `likely_drink_recipe` | `likely_drink_article` | "gin"+"negroni" matched; page is a buyers' roundup |
| `simplyrecipes.com/dollar-tree-plastic-cocktail-shaker-review` | `likely_drink_recipe` | `likely_junk` | "cocktail" matched; page is a product review |
| `simplyrecipes.com/coconut-poached-fish-with-ginger-and-lime-recipe` | `likely_drink_recipe` | `likely_food_recipe` | "lime" matched; it's a fish dish |
| `simplyrecipes.com/blueberry-jello-mold-recipe` | `likely_junk` | `likely_food_recipe` | Over-broad junk rule caught a real recipe |
| `liquor.com/recipes/spiked-hot-chocolate/` | `likely_food_recipe` | `likely_drink_recipe` | "chocolate" matched food rule; it's a drink |
| `liquor.com/recipes/pineapple-upside-down-cake/` | `likely_drink_recipe` | `likely_food_recipe` | URL is under `/recipes/` on a drinks site, but slug is clearly a cake |
| `punchdrink.com/spirit-forward/` | `likely_drink_recipe` | `likely_drink_article` | Root-level series landing page |
| `punchdrink.com/all-things-bitter-amaro-...-cocktail-recipes/` | `likely_drink_recipe` | `likely_drink_article` | "cocktail-recipes" is a roundup hub, not a recipe |
| `punchdrink.com/recipes/` | `likely_drink_recipe` | `likely_junk` | The `/recipes/` index page itself is a navigation hub |

**Pattern:** every row above came from a regex/LIKE rule that matched a substring of the slug. The fix is always the same — read the URL.

## Process

Work one site at a time, smallest first (validate the approach before scaling up). For each site, dispatch a subagent so the main context stays clean. Tell the subagent to follow this entire prompt.

**You are both implementer and auditor.** A second subagent will spot-check your work; plan to deliver classifications that survive a 10-URL random audit *per category* on the first try. If you would not stake your output on that audit, slow down and read more carefully.

### Default mode: per-row judgment

For every NULL row not covered by a verified bulk rule (see exception below):

1. Pull a small batch: `SELECT id, url, sitemap_source FROM pages WHERE content_type IS NULL AND site = '{site_name}' ORDER BY id LIMIT 200`. Process batches small enough that you actually read each URL — never load 2000 rows into a regex pipeline.
2. For each row, walk through "How to classify each URL" and record (id, category).
3. Apply the batch in one transaction with explicit id lists, one UPDATE per category:
   ```sql
   BEGIN;
   UPDATE pages SET content_type = 'likely_drink_recipe' WHERE id IN (1,2,...);
   UPDATE pages SET content_type = 'likely_drink_article' WHERE id IN (3,...);
   COMMIT;
   ```
4. Repeat until no NULL rows remain for the site.

### Narrow exception: structural bulk rules

Bulk rules (regex, SQL LIKE) are allowed only when the predicate is **structural** and **deterministic**.

**❌ Forbidden predicates: any substring of the slug.** `slug LIKE '%cocktail%'`, `slug LIKE '%-recipe-%'`, `slug LIKE '%best-%'`, `slug LIKE '%review%'`, `slug LIKE '%how-to%'`, `slug LIKE '%chocolate%'` — **none of these qualify, ever.** The failure table above is what happens when this rule is bent.

**✅ Allowed predicates:** a path **segment** (`url LIKE '%/tag/%'`), a **subdomain**, a `sitemap_source` value, an exact structural path (`/about/`).

The rule must also map to a single category with near-zero false positives:
- ✅ `url LIKE '%/tag/%'` → `likely_junk`
- ✅ `url LIKE '%/author/%'` → `likely_junk` (author bio/index pages)
- ✅ `url LIKE '%/brands/%'` → `likely_junk` (verify per site)
- ✅ `sitemap_source = 'user-generated-sitemap.xml'` → `likely_user_generated`
- ❌ `url LIKE '%/recipes/%'` → `likely_drink_recipe` — food recipes live there too
- ❌ slug ends in `-recipe-NNNNN` → `likely_food_recipe` — looks deterministic but isn't (drinks use the same pattern)

Before running any bulk UPDATE:
1. State the predicate and estimated row count.
2. `SELECT url FROM pages WHERE site = ? AND <predicate> ORDER BY RANDOM() LIMIT 30` and read all 30 by eye.
3. If even one URL would be wrongly labeled, the rule is too broad — narrow it or drop it.
4. Only then UPDATE. Log the rule (predicate + affected count) in your final report.

### Mandatory self-audit before reporting done

For every category that received rows in this run (skip `likely_junk` — too broad to spot-check usefully):

1. `SELECT url FROM pages WHERE site = ? AND content_type = ? ORDER BY RANDOM() LIMIT 10`.
2. Read each sampled URL against the spec; use the failure table as your reference for what "wrong" looks like.
3. If **any** sample fails the sentence-level reading test, fix it on the spot — and treat it as a signal there are more like it. Re-scan that category for the same pattern and fix the rest before resampling.
4. Repeat until two consecutive samples come back clean per category.

### Report

Include per-category counts, every bulk rule applied (predicate + row count), and the self-audit result (samples checked, fixes made, final clean state).

After all sites are done, run `SELECT site, content_type, COUNT(*) FROM pages GROUP BY site, content_type` and show the summary.

## Sites to process

Smallest first:
```sql
SELECT site, COUNT(*) FROM pages WHERE content_type IS NULL GROUP BY site ORDER BY COUNT(*) ASC;
```
