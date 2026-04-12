# Classify URLs as Drink or Food

One-time manual classification of recipe URLs by slug. Run this in Claude Code after sitemap discovery populates the database.

## Prerequisites

- Sitemaps have been discovered: `python3 -m scraper.src.discover`
- Database exists at `data/scraper.db` with `content_type` column

## Prompt

Copy and paste the following into Claude Code:

---

Classify all unclassified URLs in `data/scraper.db` as `likely_drink` or `likely_food` based on the URL slug.

**Rules:**
- If the URL slug suggests a drink recipe (cocktail name, drink type, spirit-based drink), set `content_type = 'likely_drink'`
- If the URL slug suggests a food recipe (dish name, cooking method, food ingredient), set `content_type = 'likely_food'`
- If ambiguous, lean toward `likely_drink` — false positives are cheaper than missed drinks
- Non-recipe URLs that slipped through sitemap filtering (articles, listicles, about pages) should be `likely_food`

**Process:**
- Work through one site at a time
- For each site, spawn a subagent to handle the classification so the main context stays clean
- Each subagent should:
  1. Query: `SELECT id, url FROM pages WHERE content_type IS NULL AND site = '{site_name}' LIMIT 500`
  2. Classify each URL by reading the slug
  3. Update in a single transaction: `BEGIN; UPDATE pages SET content_type = ? WHERE id IN (...); COMMIT;`
  4. Repeat until no NULL rows remain for that site
  5. Report back only the counts: `{site}: {n_drink} likely_drink, {n_food} likely_food`
- After all sites are done, run `SELECT site, content_type, COUNT(*) FROM pages GROUP BY site, content_type` and show the summary

**Sites to process (in order):**
```sql
SELECT site, COUNT(*) FROM pages WHERE content_type IS NULL GROUP BY site ORDER BY COUNT(*) ASC;
```
Start with the smallest sites to validate the approach before hitting the large ones.

---

## After classification

Run the fetch pipeline, which will only fetch `likely_drink` pages:

```bash
SCRAPERAPI_KEY=your-key python3 -m scraper.src.fetch --site {site_name} --limit 50
```

Start with a small `--limit` to verify the drink confirmation logic before doing a full run.
