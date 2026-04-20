# URL Classifier via Local Ollama Model

**Date:** 2026-04-19
**Status:** Design approved, pending implementation plan

## Problem

`data/scraper.db` has ~521k URLs with `content_type IS NULL` across 13 sites. Prior attempts to classify them via Claude Code in-conversation kept degrading into regex/LIKE heuristics and produced repeated failure modes (e.g. slug-keyword matches like "vodka" labeling cleaning-tip articles as drink recipes). We need a repeatable, non-conversational classifier.

## Solution

A standalone Python module (`scraper/src/classify.py`) that reads unclassified rows from SQLite, sends each URL to a local ollama-hosted model for classification into one of six labels, and writes the result back. Runs as an ordinary CLI (`python -m scraper.src.classify`) alongside `discover`/`fetch`/`validate`.

## Model

- **qwen3:14b** via ollama, local NVIDIA GPU (4060 Ti 16GB).
- Thinking mode off — we want decisive single-token-class outputs, not reasoning traces.
- Structured output via ollama's `format` parameter constrained to a JSON schema with an enum of the six valid labels. This makes parse errors structurally impossible.

## Labels

Six labels, unchanged from current schema:

- `likely_drink_recipe` — individual drink recipe (alcoholic or not).
- `likely_food_recipe` — individual food recipe.
- `likely_drink_article` — drink-related editorial that is not a single recipe.
- `likely_food_article` — food-related editorial that is not a single recipe.
- `likely_junk` — structural/meta/commercial pages with no editorial content.
- `likely_user_generated` — user-submitted content from a community sitemap.

## Prompt Strategy

Deliberately minimal. The previous runbook prompt was written to wrestle Claude off tool-use tangents and never worked reliably; none of that scaffolding is needed here.

**System prompt** — one paragraph plus six one-line label definitions. Instructs the model to read the URL as English, not scan for keywords. ~20 lines total.

**Few-shot examples** — 6–10 curated cases drawn from the known confusion zones (these are the concrete slug-keyword traps from prior runs and should be preserved here as the authoritative set, since the old runbook is gone):
- `marthastewart.com/household-uses-for-vodka` → `likely_drink_article` (topical drink content, not a recipe).
- `marthastewart.com/what-drinking-milk-every-day-does-to-your-body` → `likely_food_article` (health article, "drinking" is not a drink signal).
- `simplyrecipes.com/best-gin-for-negroni-bartenders` → `likely_drink_article` (buyers' roundup, not a recipe).
- `simplyrecipes.com/coconut-poached-fish-with-ginger-and-lime-recipe` → `likely_food_recipe` ("lime" is not a drink signal).
- `liquor.com/recipes/spiked-hot-chocolate/` → `likely_drink_recipe` (drink despite "chocolate" in slug).
- `liquor.com/recipes/pineapple-upside-down-cake/` → `likely_food_recipe` (URL path is `/recipes/` on a drinks site, but slug is a cake).
- `simplyrecipes.com/trader-joes-cocktail-shaker-review` → `likely_junk` (product review, "cocktail" is a distractor).
- `punchdrink.com/recipes/` → `likely_junk` (bare recipes index is a navigation hub, not a recipe).
- `punchdrink.com/spirit-forward/` → `likely_drink_article` (root-level series landing page, not a recipe).

**User message** — structurally uniform:
```
URL: <url>
Sitemap: <sitemap_source>
```

No chain-of-thought instructions, no numbered steps, no anti-pattern warnings. The prompt is expected to iterate; the spec treats the prompt as a tunable artifact, not a fixed contract.

## Data Model

**`pages` table** — unchanged. `content_type` gets the final label.

**New `classifications` table** — audit sidecar:
```sql
CREATE TABLE classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL REFERENCES pages(id),
    label TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    raw_response TEXT,
    latency_ms INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_classifications_page_id ON classifications(page_id);
CREATE INDEX idx_classifications_label ON classifications(label);
```

This supports:
- Post-hoc sampling without re-running the model.
- Re-classification attempts on the same URL across prompt/model versions.
- Inspecting raw model output when a classification is questioned.

## Control Flow

Single CLI with these modes:

### Main classify run
```
python -m scraper.src.classify [--site SITE] [--limit N] [--concurrency N] [--model MODEL]
```
- Default: processes smallest unclassified site first, all sites if `--site` omitted.
- Concurrency: asyncio pool of 4 in-flight ollama requests by default. Ollama queues them serially on one GPU; 4–8 keeps the pipeline full without starving the KV cache.
- Commits every 50 rows. On crash/kill, only the in-flight batch is lost; next run resumes from remaining NULL rows.
- Writes label to `pages.content_type` and full record to `classifications`.
- **No auditing in this mode.** Script runs straight through. Progress bar with rate and ETA only.

### Review mode (prompt iteration)
```
python -m scraper.src.classify --review [--sample-size N]
```
- Runs against a checked-in eval set (not the live DB).
- Outputs side-by-side: url, expected label (if known), predicted label, raw response.
- Used to tune prompts before committing a new `prompt_version` and kicking off a main run.
- Eval set lives at `scraper/eval/classify-urls.jsonl` — ~100 hand-labeled URLs covering each known failure mode and at least 5 examples per label. Checked into git so prompt changes are measurable, not vibes.

### Ad-hoc sampling (separate tiny command)
```
python -m scraper.src.classify --sample --site SITE --category CATEGORY [--n 20]
```
- Pulls N random rows of that category from `classifications` + `pages`, prints url + raw_response.
- Entirely read-only; no model calls.
- For spot-checking after a main run, or when a downstream step surfaces suspect rows.

## Ollama Client

Use the `ollama` Python package if it's painless, otherwise raw `httpx` against `http://localhost:11434/api/chat`. Pinned in `scraper/pyproject.toml`. No custom streaming — each request is a single non-streamed JSON-constrained completion.

Retries: on transport error, retry up to 3× with exponential backoff. Structured output makes content errors nearly impossible, but if the response fails schema validation we log and skip (row stays NULL for a later run).

## What Is Not In Scope

- No pre-pass of structural SQL rules (`/tag/` → junk, etc). One code path, one source of truth.
- No auto-correction after classification. Spot-checks are human-driven via the sample command.
- No model ensembling, no confidence scores, no two-pass voting. YAGNI.
- No live-reload of prompts during a run. To iterate, stop the run, edit the prompt, bump `prompt_version`, start again. Previous labels stay in `classifications` for comparison.

## Risks

- **Model drift between runs** — if someone pulls a new qwen3 tag between runs, labels could shift. Mitigated by recording `model` in `classifications` and pinning the tag in docs.
- **GPU saturation under concurrency** — 4060 Ti 16GB fits qwen3:14b q4 with room, but concurrency >8 will fight the KV cache. Default 4 is conservative; `--concurrency` flag lets us tune after measuring.
- **Eval set drift** — if the eval set grows too small or stops representing real failure modes, prompt iteration loses its measurement. Eval set is part of the spec, not a throwaway.

## Documentation

The old `docs/runbooks/classify-urls.md` is deleted — classification is no longer a manual runbook, it is a script. Install and usage instructions live in the script's `--help` output and a short section added to the top-level `CLAUDE.md` covering:
- One-time ollama install: `curl -fsSL https://ollama.com/install.sh | sh` then `ollama pull qwen3:14b`.
- Typical invocations: main run, review mode, ad-hoc sample.
