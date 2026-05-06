# LLM providers: OpenAI sync + OpenAI Batch, plus workspace cleanup

## Goal

Add OpenAI as a third LLM provider — both a synchronous client and a Batch API
client — to all three of spiritolo's prompt-driven flows:

1. `ingredients.cli map resolve-pending` — Phase 2 of taxonomy mapping.
2. `ingredients.cli normalize-names resolve-pending` — Phase 2 of dedup name
   normalization.
3. `scraper`'s URL classifier (today's `scraper/src/classify.py`).

Batch mode (50% off real-time, ~24h SLA) is the cheapness lever; the sync
provider exists for parity, iteration, and small jobs.

Fold in a small workspace cleanup so the new shared `llm/` subpackage lands
in a sensible spot rather than cementing the existing inconsistency.

**Out of scope.** Anthropic Message Batches (designed for as a future peer
of `OpenAIBatchProvider`, not implemented). Migration of the
`scraper/src/ollama_client.py` prompt module beyond the call site that
hits the LLM.

## Background

Today there are two LLM-driven flows in `ingredients/`. Both share a
`LLMProvider` Protocol defined in `ingredients/src/ingredients/mapping/llm_provider.py`
and a `resolve_with_retry` helper in `llm_resolver.py`. Two implementations
exist: `ClaudeProvider` (Anthropic) and `OllamaProvider` (local qwen3:14b).
Each flow loops the queue one row at a time, calls the provider, parses the
JSON response, and writes per-row.

The scraper's URL classifier predates this Protocol and calls `ollama_client`
directly.

The motivating use case is bulk re-runs after a prompt or extractor version
bump — currently expensive on Anthropic and slow on local ollama. OpenAI's
Batch API is the natural fit: cheap, asynchronous, idempotent re-ingest.

## Workspace cleanup (folded into scope)

The current workspace has four members with three different layouts:

| Workspace dir | Inner package dir | Today's import |
|---|---|---|
| `scraper/`     | `scraper/src/<files>`           | `from scraper.src.X import Y` |
| `ingredients/` | `ingredients/src/ingredients/`  | `from ingredients.X import Y` |
| `common/`      | `common/src/spiritolo_common/`  | `from spiritolo_common.X import Y` |
| `scripts/`     | `scripts/src/upload_to_staging/`| `from upload_to_staging.X import Y` |

`scraper.src.X` exposes "src" as a public module name via a `package-dir`
hack in `scraper/pyproject.toml`. `spiritolo_common` repeats the project
name redundantly given the workspace dir is already `common/`.

**Target.** Sensible, not wordy, dir == package name everywhere it makes sense:

| Workspace dir | Inner package dir | Import |
|---|---|---|
| `scraper/`     | `scraper/src/scraper/`         | `from scraper.X import Y` |
| `ingredients/` | `ingredients/src/ingredients/` | `from ingredients.X import Y` (unchanged) |
| `common/`      | `common/src/common/`           | `from common.X import Y` |
| `scripts/`     | `scripts/src/upload_to_staging/`| `from upload_to_staging.X import Y` (unchanged) |

PyPI distribution names stay `spiritolo-{common,scraper,ingredients,scripts}`
— never typed in code, no harm.

**Touches.**
- Rename `common/src/spiritolo_common/` → `common/src/common/`.
- Rename `scraper/src/*.py` → `scraper/src/scraper/*.py`; add
  `scraper/src/scraper/__init__.py`; drop the
  `package-dir = { "scraper.src" = "src" }` hack from
  `scraper/pyproject.toml` and use the standard `find` in `src/`.
- Sed across the codebase: `spiritolo_common.` → `common.` and
  `scraper.src.` → `scraper.`.
- Update CLAUDE.md, `docs/`, eval-set imports, tests, conftest references.

The new shared LLM subpackage lands at `common/src/common/llm/`, imported as
`from common.llm.openai import OpenAIProvider`.

## Architecture

### Module layout

```
common/src/common/llm/
  __init__.py
  provider.py         # LLMProvider Protocol + ProviderResult (sync)
  batch_provider.py   # BatchProvider Protocol + BatchRequest/Submission/Status/Result
  retry.py            # resolve_with_retry (hoisted from mapping/llm_resolver.py)
  claude.py           # hoisted from mapping/llm_provider_claude.py
  ollama.py           # hoisted from mapping/llm_provider_ollama.py
  openai.py           # NEW — sync OpenAI provider
  openai_batch.py     # NEW — OpenAI Batch API impl of BatchProvider
```

Old files in `ingredients/src/ingredients/mapping/` deleted (no shims):
- `llm_provider.py`
- `llm_provider_claude.py`
- `llm_provider_ollama.py`

`mapping/llm_resolver.py` keeps `run_phase2` (the orchestrator), but its
`resolve_with_retry` helper moves to `common.llm.retry` so dedup and
classify can import it without depending on `ingredients/`. The current
`from .llm_resolver import resolve_with_retry` in
`dedup/normalizer_llm.py` becomes `from common.llm.retry import
resolve_with_retry`.

`common/pyproject.toml` gains `anthropic`, `openai`, `httpx`.
`ingredients/pyproject.toml` drops `anthropic` and `httpx` (transitive via
common). `scraper/pyproject.toml` drops `ollama>=0.4` — `ollama_client.py`'s
LLM call routes through `common.llm.OllamaProvider` (which uses `httpx`).

### Sync Protocol (kept as-is, hoisted)

```python
# common/src/common/llm/provider.py
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class ProviderResult:
    raw_text: str
    model_id: str

class LLMProvider(Protocol):
    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult: ...
    @property
    def model_id(self) -> str: ...
```

`OpenAIProvider` mirrors `ClaudeProvider`'s shape: dataclass with `client`,
`model_id`, `max_tokens`; `from_env()` reads `OPENAI_API_KEY`; defaults to
`gpt-5-mini`; lazy SDK import.

### Batch Protocol (new)

```python
# common/src/common/llm/batch_provider.py
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class BatchRequest:
    custom_id: str           # caller-chosen, opaque to provider; max 64 char alphanum+_-
    system_prompt: str
    user_prompt: str

@dataclass(frozen=True)
class BatchSubmission:
    batch_id: str
    provider: str            # 'openai' — written to sidecar so --ingest knows
    model_id: str
    request_count: int

@dataclass(frozen=True)
class BatchStatus:
    batch_id: str
    state: str               # 'in_progress' | 'completed' | 'failed' | 'expired' | 'cancelled'
    completed: int
    total: int

@dataclass(frozen=True)
class BatchResult:
    custom_id: str
    raw_text: str | None     # None on per-request failure
    error: str | None

class BatchProvider(Protocol):
    @property
    def model_id(self) -> str: ...
    def submit(self, requests: Iterable[BatchRequest]) -> BatchSubmission: ...
    def status(self, batch_id: str) -> BatchStatus: ...
    def fetch_results(self, batch_id: str) -> Iterable[BatchResult]: ...
```

`OpenAIBatchProvider` implements via:
- `client.files.create(file=..., purpose='batch')` — upload JSONL.
- `client.batches.create(input_file_id=..., endpoint='/v1/chat/completions',
  completion_window='24h')` — submit.
- `client.batches.retrieve(batch_id)` — status.
- `client.files.content(output_file_id)` — download results JSONL.

### custom_id mapping (sidecar)

OpenAI's `custom_id` is alphanumeric + `_-`, max 64 chars. The orchestrator
assigns sequential `custom_id = f"r{idx}"` and writes a sidecar JSON at
`data/batches/<batch_id>.json`:

```json
{
  "batch_id": "batch_abc123",
  "provider": "openai",
  "flow": "mapping.resolve_pending",
  "model_id": "gpt-5-mini",
  "submitted_at": "2026-05-05T12:34:56Z",
  "version_constant": "v3",
  "request_map": { "r0": "vodka", "r1": "regan's orange bitters" }
}
```

`data/batches/` is gitignored (per-operator state). `--ingest` reads the
sidecar to fan results back to the right writers.

`flow` values:
- `mapping.resolve_pending`
- `dedup.normalize_names.resolve_pending`
- `scraper.classify.url`

`version_constant` records the mapper / normalizer / prompt version at
submit time. Ingest refuses if the current value differs (prevents writing
results computed under an old prompt against a newer schema).

Lost the sidecar file? Print the batch_id; OpenAI dashboard still has the
requests, but the operator must re-derive the mapping or re-submit.

## CLI surface

Same skeleton on all three flows:

```bash
# sync (today's behavior, plus openai)
ingredients.cli map resolve-pending --provider {claude,ollama,openai} \
                                    [--model M] [--limit N] [--yes]
ingredients.cli normalize-names resolve-pending --provider {claude,ollama,openai} \
                                                [--model M] [--limit N] [--yes]
classify --provider {claude,ollama,openai} [--model M] [--limit N] ...

# batch (new) — submit returns immediately, --wait blocks inline
<flow> --provider openai --batch [--model M] [--limit N] [--yes]
                                  # default action = submit; prints batch_id + sidecar path; exits
<flow> --provider openai --batch --wait [--poll-interval 600]
                                  # submit + poll + ingest in one command
<flow> --provider openai --batch --ingest BATCH_ID
                                  # later command; reads sidecar, fetches results, writes DB
```

Rules:
- `--batch` without `--provider openai` → CLI error.
- `--review` (eval) refuses `--batch`.
- `--ingest` without a sidecar at `data/batches/<batch_id>.json` → CLI error.
- `--wait` with `--ingest` is meaningless → CLI error.

Confirmation gate (existing `--yes` interactive prompt) extends to batch:

```
About to submit 4,217 requests to OpenAI Batch API (model gpt-5-mini).
Batch will complete within ~24h. Sidecar: data/batches/<batch_id>.json
Proceed? [y/N]:
```

No cost estimation — too noisy. Operator can check the dashboard.

## Orchestration

### Sync path

Unchanged from today; just gains `OpenAIProvider` as an option in the
provider switch in `ingredients/src/ingredients/cli.py` and in the new
`scraper` classify CLI.

### Batch submit path

1. Build the same per-row `(system_prompt, user_prompt)` tuples the sync
   loop would build (reuses `prompt.SYSTEM_PROMPT` and the flow's
   `build_user_prompt`).
2. Assign sequential `custom_id = f"r{idx}"`.
3. Call `BatchProvider.submit(requests)` → returns `BatchSubmission`.
4. Write sidecar `data/batches/<batch_id>.json` with `request_map`, `flow`,
   `version_constant`, `model_id`, `submitted_at`.
5. Print batch_id + sidecar path. Exit 0.

### Batch ingest path

1. Load sidecar by batch_id; refuse if missing, if `flow` doesn't match the
   invoking command, or if `version_constant` differs from the current
   value.
2. Call `provider.status(batch_id)`. If not `completed`, print state +
   counts, exit 1.
3. Stream `provider.fetch_results(batch_id)`. For each `BatchResult`:
   - Look up the row identity via `request_map[custom_id]`.
   - If `error`: bump `error` counter, leave row pending_llm.
   - Else: parse `raw_text` with the flow's existing `parse_response`,
     dispatch through the same `chose / propose / abstain` writer the sync
     loop uses, commit per row.
4. Print `Counter`-shaped summary; exit 0.
5. Sidecar gets renamed `<batch_id>.json.ingested` so re-running noisily
   skips. Re-ingest possible by removing the suffix.

### Wait path

= submit, then poll status every `--poll-interval` (default 600s = 10min)
with `InterruptHandler` so Ctrl-C exits cleanly without losing the
batch_id, then ingest.

### Idempotency

All existing `write_resolution` / `write_normalization` / classify writes
are upserts on `(normalized_name, mapper_version)` etc. Re-ingest of the
same batch overwrites identically — safe.

## Classify.py refactor

Replace direct `ollama_client.classify_url(...)` calls with the Protocol
path. Default provider stays `ollama` (free, local — preserves day-to-day
cost behavior). `scraper/src/scraper/ollama_client.py` (post-cleanup path)
keeps owning prompt assembly; the LLM call goes through
`common.llm.OllamaProvider`. The `classify_url()` function stays as the
public sync entrypoint, taking an `LLMProvider` arg.

Eval (`--review`) and `--sample` paths unchanged — they call
`classify_url()` with whichever provider the operator picked.

The scraper's `classify` CLI gains `--provider` and `--batch` flags
matching the ingredients flows. The work-queue gating (`content_type IS
NULL`) stays unchanged — batch is most useful for one-time backfills after
a `PROMPT_VERSION` bump on tens of thousands of rows.

## Tests

- Move existing `ingredients/tests/test_mapping_provider_claude.py` and
  `test_mapping_provider_ollama.py` to `common/tests/test_provider_*.py`.
- Add `common/tests/test_provider_openai.py` (mocked OpenAI client; mirrors
  Claude's shape).
- Add `common/tests/test_batch_openai.py` (mocked submit/status/fetch_results;
  verifies sidecar round-trip — submit writes sidecar, ingest reads it,
  results land in expected per-row writes).
- Add orchestrator tests for batch submit/ingest at the flow level
  (mapping, dedup, classify) using a `StubBatchProvider`. These verify:
  - sidecar is written with correct `flow`, `version_constant`, `request_map`
  - ingest refuses on flow mismatch
  - ingest refuses on version mismatch
  - per-result writes go through the same writer the sync loop uses
  - sidecar gets `.ingested` suffix on success
- Optional integration test gated on `OPENAI_API_KEY` env var, marked
  `@pytest.mark.live`, opt-in only.

## Failure modes

| Failure | Behavior |
|---|---|
| `OPENAI_API_KEY` missing | `from_env()` raises with actionable message before any HTTP call. |
| Batch submit network error | Provider raises; orchestrator does NOT write sidecar. Operator re-runs. |
| Batch in `failed` / `expired` / `cancelled` state at ingest | Print state + error, exit 1. Sidecar stays in place for re-ingest after operator action (e.g. cancel manually then re-submit). |
| Per-request error in batch results | Bump `error` counter; row stays pending_llm. |
| Sidecar missing at ingest | Refuse with clear error: "no sidecar at data/batches/<batch_id>.json — re-derive from OpenAI dashboard or re-submit." |
| Sidecar `flow` doesn't match invoking command | Refuse with clear error. |
| Sidecar `version_constant` doesn't match current | Refuse with clear error. |
| `--wait` interrupted | `InterruptHandler` exits cleanly; batch_id printed; operator can resume with `--ingest <batch_id>`. |
| Re-ingest after success | Sidecar `.ingested` suffix → "already ingested; remove suffix to force re-ingest." |

## Migration / ordering

1. Workspace cleanup (rename + sed) lands first as a discrete unit; tests
   pass before any LLM work starts.
2. Hoist Protocol + helpers + existing providers to `common.llm`. Tests
   green.
3. Add `OpenAIProvider` (sync) + tests.
4. Add `BatchProvider` Protocol + `OpenAIBatchProvider` + tests.
5. Wire batch CLI surface into `ingredients.cli map resolve-pending` and
   `normalize-names resolve-pending`. Tests green.
6. Refactor `scraper/src/scraper/classify.py` + `ollama_client.py` to use
   the Protocol; add `--provider` + `--batch` to scraper CLI. Tests green.
7. Update CLAUDE.md and `docs/` for new flags + workspace layout.

Each step is a self-contained subagent task so failures stay local.

## Open questions resolved

- **Use a library (LiteLLM)?** No. Three providers, dead-simple Protocol,
  and the hard part of batch is row→prompt→DB glue that no library
  abstracts. Revisit if ≥4 more providers ever come in scope.
- **Model default?** `gpt-5-mini`, `--model` override.
- **Provider naming?** `--provider openai` plus `--batch` flag (not
  `--provider openai-batch`); leaves room for future `--provider claude
  --batch`.
- **Batch flow shape?** D — submit returns immediately by default,
  `--wait` polls inline, `--ingest BATCH_ID` runs separately. No tracking
  table.
- **Classify gets batch?** Yes — bulk re-classification after PROMPT_VERSION
  bumps is exactly the cheap-bulk use case batch was made for.
