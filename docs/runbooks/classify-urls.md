# Classify URLs

One-time manual classification of URLs by slug. Run this in Claude Code after sitemap discovery populates the database.

## Prerequisites

- Sitemaps have been discovered: `python3 -m scraper.src.discover`
- Database exists at `data/scraper.db` with `content_type` column

## Prompt

Copy and paste the following into Claude Code:

---

Classify all unclassified URLs in `data/scraper.db` by URL slug into one of six categories. The `sitemap_source` column tells you which sitemap each URL came from — use this as a strong signal.

**Categories:**
- `likely_drink_recipe` — URL slug suggests a drink recipe (cocktail name, drink type, spirit-based drink)
- `likely_food_recipe` — URL slug suggests a food recipe (dish name, cooking method, food ingredient)
- `likely_drink_article` — drink-related but not a recipe (articles, listicles, bar guides, "best-of" roundups, technique explainers)
- `likely_food_article` — food-related but not a recipe (articles, tips, reviews, restaurant guides)
- `likely_junk` — structural/meta pages with no content value (about pages, FAQs, privacy policy, author bios, tag/category indexes, contact pages, ad/sponsored landing pages)
- `likely_user_generated` — user-submitted content (not editorially curated)

**Rules:**
- **First pass:** Bulk-classify by `sitemap_source` before looking at individual slugs:
  - URLs from `cocktail-user-generated.xml` (Difford's) → `likely_user_generated`
  - URLs from `guest-author-sitemap.xml` (Punch) → `likely_user_generated`
- If ambiguous between drink and food, lean toward drink — false positives are cheaper than missed drinks
- If ambiguous between recipe and article, lean toward recipe
- URLs with slugs like `/about`, `/privacy`, `/contact`, `/authors/`, `/tags/`, `/category/` are junk
- URLs with slugs like `/best-`, `/guide-`, `/how-to-choose-`, `/review-`, `/tips-`, `/what-is-` are articles
- A recipe URL typically has a specific food/drink name in the slug (e.g. `/margarita`, `/grilled-salmon`)

**Process:**
- Work through one site at a time
- For each site, spawn a subagent to handle the classification so the main context stays clean
- Each subagent should:
  1. Query: `SELECT id, url FROM pages WHERE content_type IS NULL AND site = '{site_name}' LIMIT 2000`
  2. Classify each URL by reading the slug
  3. Update in a single transaction: `BEGIN; UPDATE pages SET content_type = ? WHERE id IN (...); COMMIT;`
  4. Repeat until no NULL rows remain for that site
  5. Report back only the counts: `{site}: {n} likely_drink_recipe, {n} likely_food_recipe, {n} likely_drink_article, {n} likely_food_article, {n} likely_junk, {n} likely_user_generated`
- After all sites are done, run `SELECT site, content_type, COUNT(*) FROM pages GROUP BY site, content_type` and show the summary

**Sites to process (in order):**
```sql
SELECT site, COUNT(*) FROM pages WHERE content_type IS NULL GROUP BY site ORDER BY COUNT(*) ASC;
```
Start with the smallest sites to validate the approach before hitting the large ones.

---

## After classification

Run the fetch pipeline, which will only fetch `likely_drink_recipe` pages:

```bash
SCRAPERAPI_KEY=your-key python3 -m scraper.src.fetch --site {site_name} --limit 50
```

Start with a small `--limit` to verify the drink confirmation logic before doing a full run.
