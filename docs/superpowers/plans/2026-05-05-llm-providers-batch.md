# LLM providers (OpenAI sync + batch) + workspace cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenAI sync + Batch API providers across all three prompt-driven flows (mapping resolve-pending, dedup normalize-names, scraper classify), and fold in a workspace-layout cleanup so the new shared LLM subpackage lands at `common/src/common/llm/` rather than cementing the existing `common/spiritolo_common` and `scraper/src.X` inconsistencies.

**Architecture:** Lift the existing 6-line `LLMProvider` Protocol from `ingredients.mapping` to a new `common.llm` subpackage; add a parallel `BatchProvider` Protocol for the async submit/poll/ingest lifecycle. OpenAI is the first batch implementation; sidecar JSON files at `data/batches/<batch_id>.json` map OpenAI `custom_id` back to row identity for ingest. Workspace-cleanup pass fixes layout inconsistencies first so subsequent imports land at clean paths (`from common.llm import ...`, `from scraper.X import Y`).

**Tech Stack:** Python 3.11+, uv workspace (`common`, `scraper`, `ingredients`, `scripts`), pytest, OpenAI SDK (`openai>=1.50`), Anthropic SDK (existing), httpx (existing for ollama). Postgres via psycopg for ingredient flows, SQLite for scraper.

**Spec:** [docs/superpowers/specs/2026-05-05-llm-providers-batch-design.md](../specs/2026-05-05-llm-providers-batch-design.md)

---

## File map

**New files:**
- `common/src/common/llm/__init__.py`
- `common/src/common/llm/provider.py` — `LLMProvider` Protocol + `ProviderResult`
- `common/src/common/llm/batch_provider.py` — `BatchProvider` Protocol + `BatchRequest/Submission/Status/Result`
- `common/src/common/llm/sidecar.py` — sidecar read/write helpers
- `common/src/common/llm/retry.py` — `resolve_with_retry` (hoisted from `mapping.llm_resolver`)
- `common/src/common/llm/claude.py` — hoisted `ClaudeProvider`
- `common/src/common/llm/ollama.py` — hoisted `OllamaProvider`
- `common/src/common/llm/openai.py` — new sync OpenAI provider
- `common/src/common/llm/openai_batch.py` — new OpenAI Batch API provider
- `common/src/common/llm/batch_runner.py` — flow-agnostic submit/ingest/wait orchestrator
- `common/tests/test_provider_claude.py` (moved from `ingredients/tests/test_mapping_provider_claude.py`)
- `common/tests/test_provider_ollama.py` (moved from `ingredients/tests/test_mapping_provider_ollama.py`)
- `common/tests/test_provider_openai.py`
- `common/tests/test_batch_openai.py`
- `common/tests/test_sidecar.py`
- `common/tests/test_batch_runner.py`
- `ingredients/tests/test_mapping_resolve_pending_batch.py`
- `ingredients/tests/test_normalize_names_resolve_pending_batch.py`
- `scraper/tests/test_classify_batch.py`

**Renamed/restructured:**
- `common/src/spiritolo_common/` → `common/src/common/`
- `scraper/src/<files>.py` → `scraper/src/scraper/<files>.py` (wrap in package dir)
- `ingredients/src/ingredients/mapping/llm_provider.py` → DELETED (moved to `common.llm.provider`)
- `ingredients/src/ingredients/mapping/llm_provider_claude.py` → DELETED (moved to `common.llm.claude`)
- `ingredients/src/ingredients/mapping/llm_provider_ollama.py` → DELETED (moved to `common.llm.ollama`)

**Modified:**
- `pyproject.toml` (root) — workspace member list unchanged but verify
- `common/pyproject.toml` — adds `anthropic`, `openai`, `httpx`
- `scraper/pyproject.toml` — drop `package-dir` hack; drop `ollama>=0.4`
- `ingredients/pyproject.toml` — drop `anthropic`, `httpx`
- All `.py` files importing `spiritolo_common.X` → `common.X` (43+ files)
- All `.py` files importing `scraper.src.X` → `scraper.X`
- `ingredients/src/ingredients/mapping/llm_resolver.py` — `run_phase2` stays; imports of `LLMProvider` and helpers come from `common.llm`
- `ingredients/src/ingredients/dedup/normalizer_llm.py` — same import change
- `ingredients/src/ingredients/cli.py` — extend `--provider` to include `openai`; add `--batch`, `--submit`, `--ingest`, `--wait`, `--poll-interval`, `--model` flags to `map resolve-pending` and `normalize-names resolve-pending`
- `scraper/src/scraper/classify.py` — refactor to use `common.llm.LLMProvider`; add `--provider`, `--batch`, etc. flags
- `scraper/src/scraper/ollama_client.py` — keep prompt assembly; route LLM call through Protocol (or replace function with provider-aware wrapper)
- `scraper/src/scraper/__init__.py` — new (empty)
- `CLAUDE.md` — update for new flags + workspace layout
- `docs/pipeline.md` — same
- `.gitignore` — add `data/batches/`
- `common/tests/conftest.py` — imports update

---

## Phase A — Workspace cleanup (foundational)

Mechanical refactor; success criterion is "all existing tests still pass." No new behavior.

### Task 1: Rename `spiritolo_common` package to `common`

**Files:**
- Modify: `common/src/spiritolo_common/` → `common/src/common/` (directory rename)
- Modify: every `.py`/`.toml`/`.md` referencing `spiritolo_common` (sed)

- [ ] **Step 1: Verify on the right branch and clean tree**

```bash
git status
git branch --show-current
```

Expected: clean tree, branch `claude/llm-providers-batch-*`.

- [ ] **Step 2: Move the directory**

```bash
git mv common/src/spiritolo_common common/src/common
```

- [ ] **Step 3: Sed all `spiritolo_common` references in Python sources**

```bash
grep -rl 'spiritolo_common' --include='*.py' . \
  | grep -v '.venv/' | grep -v 'egg-info' \
  | xargs sed -i 's/spiritolo_common/common/g'
```

- [ ] **Step 4: Sed `spiritolo_common` references in TOML / docs / shell scripts**

```bash
grep -rl 'spiritolo_common' --include='*.toml' --include='*.md' --include='*.sh' --include='*.yml' --include='*.yaml' . \
  | grep -v '.venv/' \
  | xargs sed -i 's/spiritolo_common/common/g' || true
```

(The `|| true` covers an empty match list.)

- [ ] **Step 5: Verify no stragglers**

```bash
grep -rn 'spiritolo_common' --include='*.py' --include='*.toml' --include='*.md' --include='*.sh' --include='*.yml' . \
  | grep -v '.venv/' | grep -v 'egg-info'
```

Expected: empty output.

- [ ] **Step 6: Reinstall workspace**

```bash
cd /workspaces/spiritolo && uv sync --all-packages
```

Expected: succeeds; `common` package installed.

- [ ] **Step 7: Run full test suite to verify nothing broke**

```bash
cd /workspaces/spiritolo && uv run pytest common/tests scraper/tests ingredients/tests scripts/tests
```

Expected: same pass/skip counts as `main` (DB tests will skip without `TEST_DB_URL`; that's fine — count matches baseline).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Refactor: rename spiritolo_common Python package to common

Workspace dir was already common/; the inner Python package name
spiritolo_common repeated the project name redundantly. PyPI distribution
name (spiritolo-common) is unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Restructure scraper package layout

**Files:**
- Modify: `scraper/src/<files>.py` → `scraper/src/scraper/<files>.py` (wrap in package)
- Modify: `scraper/pyproject.toml`
- Modify: every importer of `scraper.src.X` (sed)

- [ ] **Step 1: Create the inner package dir and move files**

```bash
mkdir -p scraper/src/scraper
git mv scraper/src/__init__.py scraper/src/scraper/__init__.py
for f in scraper/src/*.py; do
  [ -f "$f" ] && git mv "$f" scraper/src/scraper/$(basename "$f")
done
```

- [ ] **Step 2: Verify the move**

```bash
ls scraper/src/scraper/
ls scraper/src/
```

Expected: `scraper/src/scraper/` contains all the .py files including `__init__.py`; `scraper/src/` contains only `scraper/` (and any cache dirs).

- [ ] **Step 3: Drop the package-dir hack from `scraper/pyproject.toml`**

Replace this block:

```toml
[tool.setuptools.packages]
find = {where = ["."]}

[tool.setuptools.package-dir]
"scraper.src" = "src"
```

with:

```toml
[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 4: Sed all `scraper.src.` imports**

```bash
grep -rl 'scraper\.src\.' --include='*.py' . \
  | grep -v '.venv/' | grep -v 'egg-info' \
  | xargs sed -i 's/scraper\.src\./scraper\./g'
```

Also fix any `from scraper.src import` (if present) and any `import scraper.src` (if present):

```bash
grep -rn 'scraper\.src' --include='*.py' . | grep -v '.venv/' | grep -v 'egg-info'
```

If non-empty, hand-fix each.

- [ ] **Step 5: Sed `scraper.src.` references in non-Python files**

```bash
grep -rl 'scraper\.src\.' --include='*.toml' --include='*.md' --include='*.sh' --include='*.yml' . \
  | grep -v '.venv/' \
  | xargs sed -i 's/scraper\.src\./scraper\./g' || true
```

- [ ] **Step 6: Reinstall workspace**

```bash
cd /workspaces/spiritolo && uv sync --all-packages
```

Expected: succeeds; `scraper` package installed at `scraper/src/scraper/`.

- [ ] **Step 7: Verify imports resolve**

```bash
uv run python -c "from scraper.classify import build_arg_parser; from scraper.ollama_client import classify_url; from scraper.db import Database; print('ok')"
```

Expected: `ok`.

- [ ] **Step 8: Run full test suite**

```bash
cd /workspaces/spiritolo && uv run pytest common/tests scraper/tests ingredients/tests scripts/tests
```

Expected: same pass/skip counts as before Task 2.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Refactor: wrap scraper modules in scraper/ package

Old layout exposed 'src' as a public Python module name via a package-dir
hack (from scraper.src.X import Y). New layout matches the
ingredients/src/ingredients pattern: from scraper.X import Y.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Update CLAUDE.md and docs for new layout

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/pipeline.md` (if it references old paths)

- [ ] **Step 1: Grep for stale path references in `CLAUDE.md`**

```bash
grep -n 'spiritolo_common\|scraper\.src\|scraper/src/[a-z]*\.py' CLAUDE.md
```

Resolve each:
- `spiritolo_common` → `common`
- `scraper/src/foo.py` → `scraper/src/scraper/foo.py`
- `scraper.src.X` → `scraper.X`

- [ ] **Step 2: Same grep across `docs/`**

```bash
grep -rn 'spiritolo_common\|scraper\.src\.' docs/
```

Hand-edit each match. `docs/superpowers/` historical specs/plans are immutable — leave those alone (they describe past state). Only update non-superpowers docs (e.g. `docs/pipeline.md`).

- [ ] **Step 3: Verify**

```bash
grep -rn 'spiritolo_common' --include='*.md' . | grep -v 'docs/superpowers/' | grep -v '.venv/'
grep -rn 'scraper\.src\.' --include='*.md' . | grep -v 'docs/superpowers/' | grep -v '.venv/'
```

Expected: empty.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Docs: update CLAUDE.md + docs/ for new package layout

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase B — Hoist existing LLM code to `common.llm`

### Task 4: Create `common.llm` subpackage with sync Protocol

**Files:**
- Create: `common/src/common/llm/__init__.py`
- Create: `common/src/common/llm/provider.py`

- [ ] **Step 1: Create the package dir + `__init__.py`**

```bash
mkdir -p common/src/common/llm
touch common/src/common/llm/__init__.py
```

- [ ] **Step 2: Write `provider.py` (copy from `ingredients/src/ingredients/mapping/llm_provider.py`)**

Create `common/src/common/llm/provider.py`:

```python
"""Sync LLM provider Protocol used by the per-row resolve loops in
mapping (Phase 2), dedup normalize-names (Phase 2), and scraper classify.

Implementations live in sibling modules: claude.py, ollama.py, openai.py.
Tests inject stubs via the same Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderResult:
    """Raw provider output. Caller parses with the flow's parse_response."""
    raw_text: str
    model_id: str           # e.g. 'claude-haiku-4-5', 'qwen3:14b', 'gpt-5-mini'


class LLMProvider(Protocol):
    """Anything that can answer a single prompt with structured JSON text."""

    def resolve(
        self, *, system_prompt: str, user_prompt: str,
    ) -> ProviderResult: ...

    @property
    def model_id(self) -> str: ...
```

- [ ] **Step 3: Re-export from `common.llm.__init__`**

Edit `common/src/common/llm/__init__.py`:

```python
"""Shared LLM provider Protocol + implementations.

Sync providers (one prompt, one response): see provider.py.
Batch providers (submit / poll / ingest lifecycle): see batch_provider.py.
"""

from .provider import LLMProvider, ProviderResult

__all__ = ["LLMProvider", "ProviderResult"]
```

- [ ] **Step 4: Verify import**

```bash
uv run python -c "from common.llm import LLMProvider, ProviderResult; print('ok')"
```

Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add common/src/common/llm/
git commit -m "Add common.llm package with sync LLMProvider Protocol

Hoisted from ingredients.mapping.llm_provider so the Protocol can be
shared across mapping, dedup, and scraper without ingredients
becoming an upstream dependency of scraper.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Move `ClaudeProvider` to `common.llm`

**Files:**
- Create: `common/src/common/llm/claude.py`
- Modify: `common/src/common/llm/__init__.py` (re-export)
- Modify: `common/pyproject.toml` (add `anthropic`)

- [ ] **Step 1: Add `anthropic` dep to common**

Edit `common/pyproject.toml` `dependencies = [...]` to include:

```toml
"anthropic>=0.40",
```

(Place it alphabetically next to existing entries.)

- [ ] **Step 2: Reinstall**

```bash
cd /workspaces/spiritolo && uv sync --all-packages
```

- [ ] **Step 3: Write `claude.py` (copy `ingredients/src/ingredients/mapping/llm_provider_claude.py` body, change relative import)**

Create `common/src/common/llm/claude.py`:

```python
"""Anthropic Claude provider (sync). Defaults to Haiku 4.5."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .provider import ProviderResult

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 256


@dataclass
class ClaudeProvider:
    client: object               # anthropic.Anthropic; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(cls, *, model_id: str = DEFAULT_MODEL) -> "ClaudeProvider":
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to .env or export before "
                "running --provider claude."
            )
        return cls(client=anthropic.Anthropic(api_key=api_key), model_id=model_id)

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        msg = self.client.messages.create(
            model=self.model_id,
            max_tokens=self.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = msg.content[0].text
        return ProviderResult(raw_text=text, model_id=self.model_id)
```

- [ ] **Step 4: Re-export in `__init__.py`**

Edit `common/src/common/llm/__init__.py`:

```python
"""Shared LLM provider Protocol + implementations."""

from .claude import ClaudeProvider
from .provider import LLMProvider, ProviderResult

__all__ = ["ClaudeProvider", "LLMProvider", "ProviderResult"]
```

- [ ] **Step 5: Move the existing test**

```bash
git mv ingredients/tests/test_mapping_provider_claude.py common/tests/test_provider_claude.py
sed -i 's|from ingredients\.mapping\.llm_provider_claude import ClaudeProvider|from common.llm.claude import ClaudeProvider|' common/tests/test_provider_claude.py
```

- [ ] **Step 6: Run the moved test**

```bash
uv run pytest common/tests/test_provider_claude.py -v
```

Expected: 2 tests pass (`test_resolve_returns_provider_result_with_model_id`, `test_model_id_property_matches_constructor`).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Hoist ClaudeProvider to common.llm

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Move `OllamaProvider` to `common.llm`

**Files:**
- Create: `common/src/common/llm/ollama.py`
- Modify: `common/src/common/llm/__init__.py`
- Modify: `common/pyproject.toml` (add `httpx`)

- [ ] **Step 1: Add `httpx` dep to common**

Edit `common/pyproject.toml` `dependencies = [...]` to add:

```toml
"httpx>=0.27",
```

- [ ] **Step 2: Reinstall**

```bash
cd /workspaces/spiritolo && uv sync --all-packages
```

- [ ] **Step 3: Write `ollama.py` (copy from `ingredients/src/ingredients/mapping/llm_provider_ollama.py`)**

Create `common/src/common/llm/ollama.py`:

```python
"""Ollama provider (sync). Calls the local /api/generate endpoint over HTTP."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .provider import ProviderResult

DEFAULT_MODEL = "qwen3:14b"
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_TIMEOUT = 120.0


@dataclass
class OllamaProvider:
    client: object               # httpx.Client; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL

    @classmethod
    def from_env(cls, *, model_id: str = DEFAULT_MODEL) -> "OllamaProvider":
        import httpx
        base_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)
        client = httpx.Client(timeout=DEFAULT_TIMEOUT)
        return cls(client=client, model_id=model_id, base_url=base_url)

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        url = self.base_url.rstrip("/") + "/api/generate"
        resp = self.client.post(
            url,
            json={
                "model": self.model_id,
                "system": system_prompt,
                "prompt": user_prompt,
                "stream": False,
            },
        )
        resp.raise_for_status()
        text = resp.json().get("response", "")
        return ProviderResult(raw_text=text, model_id=self.model_id)
```

- [ ] **Step 4: Re-export in `__init__.py`**

Edit `common/src/common/llm/__init__.py`:

```python
"""Shared LLM provider Protocol + implementations."""

from .claude import ClaudeProvider
from .ollama import OllamaProvider
from .provider import LLMProvider, ProviderResult

__all__ = ["ClaudeProvider", "LLMProvider", "OllamaProvider", "ProviderResult"]
```

- [ ] **Step 5: Move the existing test**

```bash
git mv ingredients/tests/test_mapping_provider_ollama.py common/tests/test_provider_ollama.py
sed -i 's|from ingredients\.mapping\.llm_provider_ollama import OllamaProvider|from common.llm.ollama import OllamaProvider|' common/tests/test_provider_ollama.py
```

- [ ] **Step 6: Run the moved test**

```bash
uv run pytest common/tests/test_provider_ollama.py -v
```

Expected: 2 tests pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Hoist OllamaProvider to common.llm

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Move `resolve_with_retry` to `common.llm.retry`

**Files:**
- Create: `common/src/common/llm/retry.py`
- Modify: `common/src/common/llm/__init__.py`
- Create: `common/tests/test_retry.py`

- [ ] **Step 1: Write the failing test**

Create `common/tests/test_retry.py`:

```python
import time
from unittest.mock import MagicMock

from common.llm.retry import resolve_with_retry


def test_returns_parsed_dict_on_success():
    provider = MagicMock()
    provider.resolve.return_value.raw_text = '{"action": "chose"}'
    parse_fn = MagicMock(return_value={"action": "chose"})
    result = resolve_with_retry(
        provider, system_prompt="s", user_prompt="u",
        normalized_name="vodka", parse_fn=parse_fn,
    )
    assert result == {"action": "chose"}
    assert provider.resolve.call_count == 1


def test_retries_on_exception_then_succeeds(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    provider = MagicMock()
    provider.resolve.side_effect = [
        RuntimeError("first fails"),
        MagicMock(raw_text='{"action": "chose"}'),
    ]
    parse_fn = MagicMock(return_value={"action": "chose"})
    result = resolve_with_retry(
        provider, system_prompt="s", user_prompt="u",
        normalized_name="vodka", parse_fn=parse_fn, max_attempts=3,
    )
    assert result == {"action": "chose"}
    assert provider.resolve.call_count == 2


def test_returns_none_when_all_attempts_exhausted(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    provider = MagicMock()
    provider.resolve.side_effect = RuntimeError("always fails")
    parse_fn = MagicMock()
    result = resolve_with_retry(
        provider, system_prompt="s", user_prompt="u",
        normalized_name="vodka", parse_fn=parse_fn, max_attempts=2,
    )
    assert result is None
    assert provider.resolve.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest common/tests/test_retry.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'common.llm.retry'`.

- [ ] **Step 3: Write `retry.py` (move from `ingredients/src/ingredients/mapping/llm_resolver.py`)**

Create `common/src/common/llm/retry.py`:

```python
"""Retry helper used by every flow that drains an LLM queue.

Used by:
  - mapping.llm_resolver.run_phase2
  - dedup.normalizer_llm.run_phase2
  - scraper.classify (when --provider != ollama, when batch=False)

The orchestrator owns the queue; this helper owns the per-call retry policy.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from .provider import LLMProvider

log = logging.getLogger("common.llm.retry")


def resolve_with_retry(
    provider: LLMProvider, *, system_prompt: str, user_prompt: str,
    normalized_name: str, max_attempts: int = 3,
    parse_fn: Callable[[str], dict] | None = None,
) -> dict | None:
    """Call provider.resolve + parse the raw text; retry on any exception
    with exponential backoff. Returns the parsed action dict, or None if
    all attempts failed.

    parse_fn must validate and return a dict; raise on bad shape so retry
    can fire. Callers pass the flow's own parse_response (mapping, dedup,
    classify all have their own action vocabulary).
    """
    if parse_fn is None:
        raise TypeError("parse_fn is required; pass the flow's parse_response")
    for attempt in range(max_attempts):
        try:
            raw = provider.resolve(
                system_prompt=system_prompt, user_prompt=user_prompt,
            ).raw_text
            return parse_fn(raw)
        except Exception as exc:
            if attempt + 1 == max_attempts:
                log.error(
                    "LLM call exhausted retries for %r: %s",
                    normalized_name, exc,
                )
                return None
            sleep_for = 2 ** attempt   # 1s, 2s, 4s
            log.warning(
                "LLM call failed for %r (attempt %d/%d): %s — retrying in %ds",
                normalized_name, attempt + 1, max_attempts, exc, sleep_for,
            )
            time.sleep(sleep_for)
    return None
```

(NOTE: this version makes `parse_fn` required. The previous version in `mapping.llm_resolver` defaulted to `mapping.prompt.parse_response` — that creates an awkward dependency from common into mapping. Fix this by requiring callers to pass it explicitly. Mapping's `run_phase2` will pass its own `parse_response` — see Task 8.)

- [ ] **Step 4: Re-export in `__init__.py`**

Edit `common/src/common/llm/__init__.py`:

```python
"""Shared LLM provider Protocol + implementations."""

from .claude import ClaudeProvider
from .ollama import OllamaProvider
from .provider import LLMProvider, ProviderResult
from .retry import resolve_with_retry

__all__ = [
    "ClaudeProvider", "LLMProvider", "OllamaProvider", "ProviderResult",
    "resolve_with_retry",
]
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest common/tests/test_retry.py -v
```

Expected: 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add common/src/common/llm/retry.py common/src/common/llm/__init__.py common/tests/test_retry.py
git commit -m "Add common.llm.retry helper

Hoisted from ingredients.mapping.llm_resolver. parse_fn is now required
(rather than defaulting to mapping.prompt.parse_response) so that
common.llm doesn't have an awkward upward dependency on ingredients.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Switch mapping/dedup imports to `common.llm`; delete old provider files

**Files:**
- Modify: `ingredients/src/ingredients/mapping/llm_resolver.py`
- Modify: `ingredients/src/ingredients/dedup/normalizer_llm.py`
- Delete: `ingredients/src/ingredients/mapping/llm_provider.py`
- Delete: `ingredients/src/ingredients/mapping/llm_provider_claude.py`
- Delete: `ingredients/src/ingredients/mapping/llm_provider_ollama.py`

- [ ] **Step 1: Update imports in `mapping/llm_resolver.py`**

In `ingredients/src/ingredients/mapping/llm_resolver.py`, replace the existing import block:

```python
from .llm_provider import LLMProvider
```

with:

```python
from common.llm import LLMProvider
from common.llm.retry import resolve_with_retry as _resolve_with_retry_helper
```

Then DELETE the local `_resolve_with_retry` function (lines defining it) and the `resolve_with_retry = _resolve_with_retry` re-export. Replace internal call sites of `_resolve_with_retry(...)` with calls that pass the flow's parse_fn explicitly:

```python
action_obj = _resolve_with_retry_helper(
    provider,
    system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt,
    normalized_name=normalized,
    parse_fn=parse_response,    # already imported from .prompt above
)
```

(No re-export needed — Step 2 below updates dedup's import in the same task, and there are no other importers.)

- [ ] **Step 2: Update imports in `dedup/normalizer_llm.py`**

In `ingredients/src/ingredients/dedup/normalizer_llm.py`, replace:

```python
from ingredients.mapping.llm_provider import LLMProvider
from ingredients.mapping.llm_resolver import resolve_with_retry
```

with:

```python
from common.llm import LLMProvider
from common.llm.retry import resolve_with_retry
```

Then update the call site (`resolve_with_retry(provider, ..., parse_fn=_parse_response)` already passes parse_fn — no change needed).

- [ ] **Step 3: Verify nothing else still imports the old paths**

```bash
grep -rn 'from ingredients\.mapping\.llm_provider\b\|from ingredients\.mapping\.llm_provider_' --include='*.py' . | grep -v '.venv/'
```

Expected: empty.

- [ ] **Step 4: Delete the old provider files**

```bash
git rm ingredients/src/ingredients/mapping/llm_provider.py
git rm ingredients/src/ingredients/mapping/llm_provider_claude.py
git rm ingredients/src/ingredients/mapping/llm_provider_ollama.py
```

- [ ] **Step 5: Update CLI provider-instantiation imports in `ingredients/src/ingredients/cli.py`**

Replace these imports (appear twice, in `run_resolve_pending` and the normalize-names resolve-pending handler):

```python
from ingredients.mapping.llm_provider_claude import ClaudeProvider
# ...
from ingredients.mapping.llm_provider_ollama import OllamaProvider
```

with:

```python
from common.llm.claude import ClaudeProvider
# ...
from common.llm.ollama import OllamaProvider
```

(These are inside `if args.provider == "claude":` blocks; just change the module path.)

- [ ] **Step 6: Drop `anthropic` and `httpx` from `ingredients/pyproject.toml`**

Edit `ingredients/pyproject.toml`:

```diff
 dependencies = [
     "spiritolo-common",
     "psycopg[binary]>=3.2",
     "python-dotenv>=1.0",
-    "anthropic>=0.40",
-    "httpx>=0.27",
 ]
```

- [ ] **Step 7: Reinstall**

```bash
cd /workspaces/spiritolo && uv sync --all-packages
```

- [ ] **Step 8: Run mapping + dedup tests**

```bash
uv run pytest ingredients/tests/ -v -k 'mapping or dedup or cli'
```

Expected: same pass/skip counts as before. (DB tests skip without `TEST_DB_URL`; that's fine.)

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Switch mapping/dedup to common.llm; delete old provider files

ingredients no longer declares anthropic or httpx — those come transitively
via common.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase C — Add OpenAI sync provider

### Task 9: Add OpenAI dep + `OpenAIProvider`

**Files:**
- Modify: `common/pyproject.toml` (add `openai`)
- Create: `common/src/common/llm/openai.py`
- Modify: `common/src/common/llm/__init__.py`
- Create: `common/tests/test_provider_openai.py`

- [ ] **Step 1: Write the failing test**

Create `common/tests/test_provider_openai.py`:

```python
from unittest.mock import MagicMock

from common.llm.openai import OpenAIProvider


def _fake_openai_client(reply_text: str) -> MagicMock:
    client = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = reply_text
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    client.chat.completions.create.return_value = fake_resp
    return client


def test_resolve_returns_provider_result_with_model_id():
    client = _fake_openai_client('{"action": "chose", "node_id": 7}')
    p = OpenAIProvider(client=client, model_id="gpt-5-mini")
    out = p.resolve(system_prompt="sys", user_prompt="u")
    assert out.raw_text == '{"action": "chose", "node_id": 7}'
    assert out.model_id == "gpt-5-mini"
    client.chat.completions.create.assert_called_once()
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-5-mini"
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}
    assert kwargs["messages"][1] == {"role": "user", "content": "u"}


def test_model_id_property_matches_constructor():
    p = OpenAIProvider(client=MagicMock(), model_id="gpt-4o-mini")
    assert p.model_id == "gpt-4o-mini"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest common/tests/test_provider_openai.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'common.llm.openai'`.

- [ ] **Step 3: Add `openai` dep to common**

Edit `common/pyproject.toml` `dependencies = [...]` to add:

```toml
"openai>=1.50",
```

- [ ] **Step 4: Reinstall**

```bash
cd /workspaces/spiritolo && uv sync --all-packages
```

- [ ] **Step 5: Write `openai.py`**

Create `common/src/common/llm/openai.py`:

```python
"""OpenAI sync provider. Defaults to gpt-5-mini.

For batch (50% off, ~24h SLA), see openai_batch.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .provider import ProviderResult

DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_MAX_TOKENS = 256


@dataclass
class OpenAIProvider:
    client: object               # openai.OpenAI; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(cls, *, model_id: str = DEFAULT_MODEL) -> "OpenAIProvider":
        import openai
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Add it to .env or export before "
                "running --provider openai."
            )
        return cls(client=openai.OpenAI(api_key=api_key), model_id=model_id)

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        resp = self.client.chat.completions.create(
            model=self.model_id,
            max_completion_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        return ProviderResult(raw_text=text, model_id=self.model_id)
```

(NOTE: gpt-5-mini uses `max_completion_tokens` not `max_tokens` in the new chat-completions schema. `response_format={"type": "json_object"}` enforces JSON output — matches the strict-JSON discipline the existing prompts assume.)

- [ ] **Step 6: Re-export in `__init__.py`**

Edit `common/src/common/llm/__init__.py`:

```python
from .claude import ClaudeProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .provider import LLMProvider, ProviderResult
from .retry import resolve_with_retry

__all__ = [
    "ClaudeProvider", "LLMProvider", "OllamaProvider", "OpenAIProvider",
    "ProviderResult", "resolve_with_retry",
]
```

- [ ] **Step 7: Run test to verify it passes**

The test mocks `client.chat.completions.create.return_value`. The implementation passes `max_completion_tokens` — the mock accepts any kwargs, so the test passes. Update the test to also assert on `max_completion_tokens`:

Edit `common/tests/test_provider_openai.py` adding to `test_resolve_returns_provider_result_with_model_id`:

```python
    assert kwargs["max_completion_tokens"] == 256
    assert kwargs["response_format"] == {"type": "json_object"}
```

```bash
uv run pytest common/tests/test_provider_openai.py -v
```

Expected: 2 tests pass.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add OpenAIProvider (sync) to common.llm

Defaults to gpt-5-mini. Uses response_format=json_object to enforce the
strict-JSON discipline the existing prompts assume.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Wire `--provider openai` into mapping `resolve-pending`

**Files:**
- Modify: `ingredients/src/ingredients/cli.py`

- [ ] **Step 1: Find the existing provider switch**

```bash
grep -n 'choices=\["claude", "ollama"\]' ingredients/src/ingredients/cli.py
```

Expected: 2 hits (one in `_add_resolve_pending_args` for map, one for normalize-names).

- [ ] **Step 2: Update both `choices=` lists**

Replace `choices=["claude", "ollama"]` with `choices=["claude", "ollama", "openai"]` at both sites in `ingredients/src/ingredients/cli.py`.

- [ ] **Step 3: Update both provider-instantiation switches**

In `run_resolve_pending` (around line 314):

```python
if args.provider == "claude":
    from common.llm.claude import ClaudeProvider
    provider = ClaudeProvider.from_env()
elif args.provider == "openai":
    from common.llm.openai import OpenAIProvider
    provider = OpenAIProvider.from_env()
else:
    from common.llm.ollama import OllamaProvider
    provider = OllamaProvider.from_env()
```

In the normalize-names equivalent (around line 525), make the same three-way switch.

- [ ] **Step 4: Verify CLI parses without error**

```bash
uv run python -m ingredients.cli map resolve-pending --provider openai --help
```

Expected: argparse usage output, no error. Lists `--provider {claude,ollama,openai}`.

- [ ] **Step 5: Run cli tests**

```bash
uv run pytest ingredients/tests/test_mapping_cli.py ingredients/tests/test_dedup_cli.py -v
```

Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add ingredients/src/ingredients/cli.py
git commit -m "Wire --provider openai into mapping + normalize-names resolve-pending

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase D — Batch infrastructure

### Task 11: `BatchProvider` Protocol + dataclasses

**Files:**
- Create: `common/src/common/llm/batch_provider.py`
- Modify: `common/src/common/llm/__init__.py`
- Create: `common/tests/test_batch_provider.py`

- [ ] **Step 1: Write the failing test**

Create `common/tests/test_batch_provider.py`:

```python
"""The Protocol itself has no behavior — these tests pin the dataclass shapes
so downstream code can rely on them. Behavior tests live in
test_batch_openai.py and test_batch_runner.py."""

from common.llm.batch_provider import (
    BatchRequest, BatchResult, BatchStatus, BatchSubmission,
)


def test_batch_request_is_frozen():
    r = BatchRequest(custom_id="r0", system_prompt="s", user_prompt="u")
    try:
        r.custom_id = "r1"
    except Exception:
        return
    assert False, "BatchRequest should be frozen"


def test_batch_submission_carries_provider_and_count():
    s = BatchSubmission(
        batch_id="batch_abc", provider="openai",
        model_id="gpt-5-mini", request_count=42,
    )
    assert s.batch_id == "batch_abc"
    assert s.provider == "openai"
    assert s.model_id == "gpt-5-mini"
    assert s.request_count == 42


def test_batch_status_carries_progress_counts():
    st = BatchStatus(batch_id="b", state="in_progress", completed=10, total=42)
    assert st.state == "in_progress"
    assert st.completed == 10
    assert st.total == 42


def test_batch_result_can_carry_either_text_or_error():
    ok = BatchResult(custom_id="r0", raw_text="hi", error=None)
    err = BatchResult(custom_id="r1", raw_text=None, error="timeout")
    assert ok.raw_text == "hi" and ok.error is None
    assert err.raw_text is None and err.error == "timeout"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest common/tests/test_batch_provider.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'common.llm.batch_provider'`.

- [ ] **Step 3: Write `batch_provider.py`**

Create `common/src/common/llm/batch_provider.py`:

```python
"""Async-batch LLM provider Protocol.

Lifecycle: caller assembles BatchRequests, calls submit() (returns a
BatchSubmission with the provider's batch_id), later calls status() and
fetch_results() once status='completed'.

The provider is opaque to the row→prompt mapping; callers persist a sidecar
JSON file (see common.llm.sidecar) keyed on the batch_id that maps each
custom_id back to row identity.

Implementations: openai_batch.OpenAIBatchProvider. Future: claude batch.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BatchRequest:
    custom_id: str           # alphanumeric + _-, max 64 chars (OpenAI constraint)
    system_prompt: str
    user_prompt: str


@dataclass(frozen=True)
class BatchSubmission:
    batch_id: str
    provider: str            # 'openai'; written to sidecar so --ingest knows
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

- [ ] **Step 4: Re-export in `__init__.py`**

Edit `common/src/common/llm/__init__.py`:

```python
from .batch_provider import (
    BatchProvider, BatchRequest, BatchResult, BatchStatus, BatchSubmission,
)
from .claude import ClaudeProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .provider import LLMProvider, ProviderResult
from .retry import resolve_with_retry

__all__ = [
    "BatchProvider", "BatchRequest", "BatchResult", "BatchStatus",
    "BatchSubmission",
    "ClaudeProvider", "LLMProvider", "OllamaProvider", "OpenAIProvider",
    "ProviderResult", "resolve_with_retry",
]
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest common/tests/test_batch_provider.py -v
```

Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add common/src/common/llm/batch_provider.py common/src/common/llm/__init__.py common/tests/test_batch_provider.py
git commit -m "Add BatchProvider Protocol + dataclasses

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Sidecar utilities

**Files:**
- Create: `common/src/common/llm/sidecar.py`
- Create: `common/tests/test_sidecar.py`
- Modify: `common/src/common/llm/__init__.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing tests**

Create `common/tests/test_sidecar.py`:

```python
import json
from pathlib import Path

import pytest

from common.llm.sidecar import (
    Sidecar, SidecarMismatch, load_sidecar, mark_ingested, write_sidecar,
)


def test_write_then_load_roundtrips(tmp_path):
    sc = Sidecar(
        batch_id="batch_abc",
        provider="openai",
        flow="mapping.resolve_pending",
        model_id="gpt-5-mini",
        version_constant="v3",
        submitted_at="2026-05-05T12:00:00Z",
        request_map={"r0": "vodka", "r1": "rye"},
    )
    path = write_sidecar(sc, batches_dir=tmp_path)
    assert path == tmp_path / "batch_abc.json"
    assert path.exists()

    loaded = load_sidecar("batch_abc", batches_dir=tmp_path)
    assert loaded == sc


def test_load_refuses_on_flow_mismatch(tmp_path):
    sc = Sidecar(
        batch_id="b1", provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={},
    )
    write_sidecar(sc, batches_dir=tmp_path)
    with pytest.raises(SidecarMismatch, match="flow mismatch"):
        load_sidecar("b1", batches_dir=tmp_path,
                     expected_flow="dedup.normalize_names.resolve_pending")


def test_load_refuses_on_version_mismatch(tmp_path):
    sc = Sidecar(
        batch_id="b1", provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={},
    )
    write_sidecar(sc, batches_dir=tmp_path)
    with pytest.raises(SidecarMismatch, match="version mismatch"):
        load_sidecar("b1", batches_dir=tmp_path,
                     expected_flow="mapping.resolve_pending",
                     expected_version="v4")


def test_load_raises_filenotfound_on_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_sidecar("nope", batches_dir=tmp_path)


def test_mark_ingested_renames_file(tmp_path):
    sc = Sidecar(
        batch_id="b1", provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={"r0": "vodka"},
    )
    path = write_sidecar(sc, batches_dir=tmp_path)
    new_path = mark_ingested(path)
    assert new_path == tmp_path / "b1.json.ingested"
    assert new_path.exists()
    assert not path.exists()


def test_load_refuses_already_ingested(tmp_path):
    sc = Sidecar(
        batch_id="b1", provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={},
    )
    path = write_sidecar(sc, batches_dir=tmp_path)
    mark_ingested(path)
    with pytest.raises(SidecarMismatch, match="already ingested"):
        load_sidecar("b1", batches_dir=tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest common/tests/test_sidecar.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Write `sidecar.py`**

Create `common/src/common/llm/sidecar.py`:

```python
"""Sidecar JSON files persist batch submissions so --ingest can fan results
back to the right writers.

Path: data/batches/<batch_id>.json (configurable per-call).
On successful ingest, file is renamed <batch_id>.json.ingested so re-runs
noisily skip; remove the suffix to force re-ingest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


class SidecarMismatch(Exception):
    """Sidecar exists but its metadata doesn't match the calling context.

    Raised when:
    - The sidecar's `flow` doesn't match the invoking command (e.g. trying
      to ingest a mapping batch via the dedup CLI).
    - The sidecar's `version_constant` doesn't match the current
      mapper/normalizer/prompt version.
    - The sidecar has been renamed `.ingested`.
    """


@dataclass(frozen=True)
class Sidecar:
    batch_id: str
    provider: str            # 'openai'
    flow: str                # e.g. 'mapping.resolve_pending'
    model_id: str
    version_constant: str    # mapper/normalizer/prompt version at submit time
    submitted_at: str        # ISO 8601 UTC
    request_map: dict[str, str] = field(default_factory=dict)


def write_sidecar(sc: Sidecar, *, batches_dir: Path) -> Path:
    """Write sidecar to <batches_dir>/<batch_id>.json. Returns the path."""
    batches_dir.mkdir(parents=True, exist_ok=True)
    path = batches_dir / f"{sc.batch_id}.json"
    with open(path, "w") as f:
        json.dump(asdict(sc), f, indent=2)
    return path


def load_sidecar(
    batch_id: str, *, batches_dir: Path,
    expected_flow: str | None = None,
    expected_version: str | None = None,
) -> Sidecar:
    """Load sidecar by batch_id. Optionally enforce flow + version match."""
    path = batches_dir / f"{batch_id}.json"
    if not path.exists():
        ingested = batches_dir / f"{batch_id}.json.ingested"
        if ingested.exists():
            raise SidecarMismatch(
                f"sidecar for {batch_id} already ingested "
                f"(at {ingested}). Remove the .ingested suffix to force re-ingest."
            )
        raise FileNotFoundError(
            f"no sidecar at {path} — re-derive from OpenAI dashboard or re-submit."
        )
    with open(path) as f:
        raw = json.load(f)
    sc = Sidecar(**raw)
    if expected_flow and sc.flow != expected_flow:
        raise SidecarMismatch(
            f"flow mismatch: sidecar says {sc.flow!r}, expected {expected_flow!r}"
        )
    if expected_version and sc.version_constant != expected_version:
        raise SidecarMismatch(
            f"version mismatch: sidecar was submitted under {sc.version_constant!r}, "
            f"current is {expected_version!r}. Re-submit under the new version."
        )
    return sc


def mark_ingested(sidecar_path: Path) -> Path:
    """Rename <batch_id>.json → <batch_id>.json.ingested. Idempotent."""
    new_path = sidecar_path.with_suffix(sidecar_path.suffix + ".ingested")
    sidecar_path.rename(new_path)
    return new_path
```

- [ ] **Step 4: Add `data/batches/` to `.gitignore`**

```bash
grep -q '^data/batches/' .gitignore || echo 'data/batches/' >> .gitignore
```

- [ ] **Step 5: Re-export in `__init__.py`**

Edit `common/src/common/llm/__init__.py`:

```python
from .batch_provider import (
    BatchProvider, BatchRequest, BatchResult, BatchStatus, BatchSubmission,
)
from .claude import ClaudeProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .provider import LLMProvider, ProviderResult
from .retry import resolve_with_retry
from .sidecar import Sidecar, SidecarMismatch, load_sidecar, mark_ingested, write_sidecar

__all__ = [
    "BatchProvider", "BatchRequest", "BatchResult", "BatchStatus",
    "BatchSubmission",
    "ClaudeProvider", "LLMProvider", "OllamaProvider", "OpenAIProvider",
    "ProviderResult", "resolve_with_retry",
    "Sidecar", "SidecarMismatch", "load_sidecar", "mark_ingested", "write_sidecar",
]
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest common/tests/test_sidecar.py -v
```

Expected: 6 tests pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add common.llm.sidecar for batch submission persistence

Sidecar JSON at data/batches/<batch_id>.json maps OpenAI custom_id back
to row identity, plus carries flow + version_constant so --ingest can
refuse mismatched uses. data/batches/ is gitignored.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: `OpenAIBatchProvider`

**Files:**
- Create: `common/src/common/llm/openai_batch.py`
- Create: `common/tests/test_batch_openai.py`
- Modify: `common/src/common/llm/__init__.py`

- [ ] **Step 1: Write failing tests**

Create `common/tests/test_batch_openai.py`:

```python
import io
import json
from unittest.mock import MagicMock

from common.llm.batch_provider import BatchRequest, BatchResult, BatchStatus
from common.llm.openai_batch import OpenAIBatchProvider


def _stub_openai_client():
    """Return a MagicMock OpenAI client whose files/batches surfaces are
    tracked individually."""
    client = MagicMock()
    return client


def test_submit_uploads_jsonl_then_creates_batch():
    client = _stub_openai_client()
    file_obj = MagicMock(id="file_xyz")
    client.files.create.return_value = file_obj
    batch_obj = MagicMock(id="batch_abc")
    client.batches.create.return_value = batch_obj

    p = OpenAIBatchProvider(client=client, model_id="gpt-5-mini")
    sub = p.submit([
        BatchRequest(custom_id="r0", system_prompt="s", user_prompt="u0"),
        BatchRequest(custom_id="r1", system_prompt="s", user_prompt="u1"),
    ])
    assert sub.batch_id == "batch_abc"
    assert sub.provider == "openai"
    assert sub.model_id == "gpt-5-mini"
    assert sub.request_count == 2

    # files.create called with a JSONL body containing both requests.
    assert client.files.create.call_count == 1
    call = client.files.create.call_args
    assert call.kwargs["purpose"] == "batch"
    raw = call.kwargs["file"]
    if hasattr(raw, "read"):
        body = raw.read().decode() if isinstance(raw.read(), bytes) else raw.read()
    else:
        body = raw
    lines = [json.loads(line) for line in body.splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0]["custom_id"] == "r0"
    assert lines[0]["method"] == "POST"
    assert lines[0]["url"] == "/v1/chat/completions"
    assert lines[0]["body"]["model"] == "gpt-5-mini"
    assert lines[0]["body"]["messages"][0] == {"role": "system", "content": "s"}
    assert lines[0]["body"]["messages"][1] == {"role": "user", "content": "u0"}

    # batches.create called with the uploaded file id + 24h window.
    assert client.batches.create.call_count == 1
    bcall = client.batches.create.call_args.kwargs
    assert bcall["input_file_id"] == "file_xyz"
    assert bcall["endpoint"] == "/v1/chat/completions"
    assert bcall["completion_window"] == "24h"


def test_status_maps_openai_response():
    client = _stub_openai_client()
    fake_batch = MagicMock(
        id="batch_abc", status="in_progress",
        request_counts=MagicMock(completed=5, total=10),
    )
    client.batches.retrieve.return_value = fake_batch

    p = OpenAIBatchProvider(client=client, model_id="gpt-5-mini")
    st = p.status("batch_abc")
    assert st == BatchStatus(batch_id="batch_abc", state="in_progress",
                             completed=5, total=10)


def test_fetch_results_streams_parsed_results():
    client = _stub_openai_client()
    # batches.retrieve returns the completed batch with output_file_id.
    fake_batch = MagicMock(
        id="batch_abc", status="completed",
        output_file_id="file_out", error_file_id=None,
    )
    client.batches.retrieve.return_value = fake_batch

    # files.content returns a binary stream of newline-delimited JSON.
    payload = (
        json.dumps({
            "custom_id": "r0",
            "response": {"status_code": 200, "body": {
                "choices": [{"message": {"content": '{"action":"chose"}'}}]
            }},
            "error": None,
        }) + "\n" +
        json.dumps({
            "custom_id": "r1",
            "response": None,
            "error": {"message": "rate limited"},
        }) + "\n"
    ).encode()
    fake_resp = MagicMock()
    fake_resp.text = payload.decode()
    fake_resp.read.return_value = payload
    client.files.content.return_value = fake_resp

    p = OpenAIBatchProvider(client=client, model_id="gpt-5-mini")
    results = list(p.fetch_results("batch_abc"))
    assert results == [
        BatchResult(custom_id="r0", raw_text='{"action":"chose"}', error=None),
        BatchResult(custom_id="r1", raw_text=None, error="rate limited"),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest common/tests/test_batch_openai.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Write `openai_batch.py`**

Create `common/src/common/llm/openai_batch.py`:

```python
"""OpenAI Batch API provider. 50% off real-time, ~24h SLA.

Lifecycle:
  submit()       — uploads a JSONL of requests, creates a batch, returns batch_id.
  status()       — polls the batch's status field.
  fetch_results()— downloads the output JSONL once status == 'completed'.

custom_id discipline: caller picks short alphanumeric IDs (max 64 chars,
[a-zA-Z0-9_-]). Persistence of custom_id → row identity is the caller's
responsibility (see common.llm.sidecar).
"""

from __future__ import annotations

import io
import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from .batch_provider import BatchRequest, BatchResult, BatchStatus, BatchSubmission

DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_MAX_TOKENS = 256
DEFAULT_COMPLETION_WINDOW = "24h"


@dataclass
class OpenAIBatchProvider:
    client: object               # openai.OpenAI; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(cls, *, model_id: str = DEFAULT_MODEL) -> "OpenAIBatchProvider":
        import openai
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Add it to .env or export before "
                "running --provider openai --batch."
            )
        return cls(client=openai.OpenAI(api_key=api_key), model_id=model_id)

    def submit(self, requests: Iterable[BatchRequest]) -> BatchSubmission:
        # Build JSONL body in memory (uses are bounded — tens of thousands
        # of small prompts, low MB).
        lines = []
        count = 0
        for r in requests:
            lines.append(json.dumps({
                "custom_id": r.custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": self.model_id,
                    "max_completion_tokens": self.max_tokens,
                    "messages": [
                        {"role": "system", "content": r.system_prompt},
                        {"role": "user", "content": r.user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                },
            }))
            count += 1
        body = ("\n".join(lines) + "\n").encode()
        file_obj = self.client.files.create(
            file=io.BytesIO(body),
            purpose="batch",
        )
        batch = self.client.batches.create(
            input_file_id=file_obj.id,
            endpoint="/v1/chat/completions",
            completion_window=DEFAULT_COMPLETION_WINDOW,
        )
        return BatchSubmission(
            batch_id=batch.id, provider="openai",
            model_id=self.model_id, request_count=count,
        )

    def status(self, batch_id: str) -> BatchStatus:
        b = self.client.batches.retrieve(batch_id)
        return BatchStatus(
            batch_id=batch_id, state=b.status,
            completed=b.request_counts.completed,
            total=b.request_counts.total,
        )

    def fetch_results(self, batch_id: str) -> Iterator[BatchResult]:
        b = self.client.batches.retrieve(batch_id)
        if b.status != "completed":
            raise RuntimeError(
                f"batch {batch_id} status is {b.status!r}, not 'completed'"
            )
        if not b.output_file_id:
            raise RuntimeError(f"batch {batch_id} has no output_file_id")
        resp = self.client.files.content(b.output_file_id)
        text = getattr(resp, "text", None)
        if text is None:
            text = resp.read().decode() if hasattr(resp, "read") else str(resp)
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            custom_id = row.get("custom_id", "")
            err = row.get("error")
            if err:
                yield BatchResult(
                    custom_id=custom_id, raw_text=None,
                    error=err.get("message", "unknown error"),
                )
                continue
            choices = (
                row.get("response", {})
                   .get("body", {})
                   .get("choices", [])
            )
            content = choices[0].get("message", {}).get("content") if choices else None
            yield BatchResult(custom_id=custom_id, raw_text=content, error=None)
```

- [ ] **Step 4: Re-export in `__init__.py`**

Edit `common/src/common/llm/__init__.py`:

```python
from .batch_provider import (
    BatchProvider, BatchRequest, BatchResult, BatchStatus, BatchSubmission,
)
from .claude import ClaudeProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .openai_batch import OpenAIBatchProvider
from .provider import LLMProvider, ProviderResult
from .retry import resolve_with_retry
from .sidecar import Sidecar, SidecarMismatch, load_sidecar, mark_ingested, write_sidecar

__all__ = [
    "BatchProvider", "BatchRequest", "BatchResult", "BatchStatus",
    "BatchSubmission",
    "ClaudeProvider", "LLMProvider", "OllamaProvider", "OpenAIProvider",
    "OpenAIBatchProvider",
    "ProviderResult", "resolve_with_retry",
    "Sidecar", "SidecarMismatch", "load_sidecar", "mark_ingested", "write_sidecar",
]
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest common/tests/test_batch_openai.py -v
```

Expected: 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add OpenAIBatchProvider implementing BatchProvider Protocol

Submit uploads JSONL via files.create, creates batch via batches.create.
Status maps OpenAI's batch.status to BatchStatus. fetch_results streams
the output file as BatchResult per row, mapping per-request errors
through.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Flow-agnostic batch runner (orchestrator)

**Files:**
- Create: `common/src/common/llm/batch_runner.py`
- Create: `common/tests/test_batch_runner.py`
- Modify: `common/src/common/llm/__init__.py`

- [ ] **Step 1: Write failing tests**

Create `common/tests/test_batch_runner.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from common.llm.batch_provider import BatchRequest, BatchResult, BatchStatus, BatchSubmission
from common.llm.batch_runner import (
    BatchSubmitOutcome, ingest_batch, submit_batch,
)
from common.llm.sidecar import load_sidecar


def _stub_provider(batch_id="batch_abc", model_id="gpt-5-mini"):
    p = MagicMock()
    p.model_id = model_id
    p.submit.return_value = BatchSubmission(
        batch_id=batch_id, provider="openai",
        model_id=model_id, request_count=2,
    )
    return p


def test_submit_writes_sidecar_with_request_map(tmp_path):
    provider = _stub_provider()
    rows = [("vodka", "system_prompt", "user_prompt 0"),
            ("rye",   "system_prompt", "user_prompt 1")]

    def to_request(idx, row):
        _, sys_p, user_p = row
        return BatchRequest(custom_id=f"r{idx}", system_prompt=sys_p, user_prompt=user_p)

    def row_to_id(row):
        return row[0]    # the normalized name

    outcome = submit_batch(
        provider=provider, rows=rows,
        to_request=to_request, row_to_id=row_to_id,
        flow="mapping.resolve_pending", version_constant="v3",
        batches_dir=tmp_path,
    )
    assert isinstance(outcome, BatchSubmitOutcome)
    assert outcome.submission.batch_id == "batch_abc"
    assert outcome.sidecar_path == tmp_path / "batch_abc.json"

    sc = load_sidecar("batch_abc", batches_dir=tmp_path,
                      expected_flow="mapping.resolve_pending",
                      expected_version="v3")
    assert sc.request_map == {"r0": "vodka", "r1": "rye"}
    assert sc.model_id == "gpt-5-mini"
    assert sc.flow == "mapping.resolve_pending"


def test_ingest_dispatches_to_callbacks_and_marks_sidecar(tmp_path):
    # Set up a sidecar from a prior submit.
    provider = _stub_provider()
    rows = [("vodka", "s", "u0"), ("rye", "s", "u1")]

    submit_batch(
        provider=provider, rows=rows,
        to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
        row_to_id=lambda r: r[0],
        flow="mapping.resolve_pending", version_constant="v3",
        batches_dir=tmp_path,
    )

    # Now ingest with a stub provider returning two results.
    ingest_provider = MagicMock()
    ingest_provider.status.return_value = BatchStatus(
        batch_id="batch_abc", state="completed", completed=2, total=2,
    )
    ingest_provider.fetch_results.return_value = iter([
        BatchResult(custom_id="r0", raw_text='{"action":"chose"}', error=None),
        BatchResult(custom_id="r1", raw_text=None, error="rate limited"),
    ])

    seen = []
    def on_result(row_id, raw_text, error):
        seen.append((row_id, raw_text, error))

    counts = ingest_batch(
        provider=ingest_provider, batch_id="batch_abc",
        flow="mapping.resolve_pending", version_constant="v3",
        on_result=on_result, batches_dir=tmp_path,
    )
    assert seen == [
        ("vodka", '{"action":"chose"}', None),
        ("rye",   None,                 "rate limited"),
    ]
    assert counts["ok"] == 1
    assert counts["error"] == 1

    # Sidecar renamed to .ingested.
    assert (tmp_path / "batch_abc.json.ingested").exists()
    assert not (tmp_path / "batch_abc.json").exists()


def test_ingest_refuses_when_status_not_completed(tmp_path):
    provider = _stub_provider()
    submit_batch(
        provider=provider, rows=[("v", "s", "u")],
        to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
        row_to_id=lambda r: r[0],
        flow="mapping.resolve_pending", version_constant="v3",
        batches_dir=tmp_path,
    )

    ingest_provider = MagicMock()
    ingest_provider.status.return_value = BatchStatus(
        batch_id="batch_abc", state="in_progress", completed=0, total=1,
    )

    with pytest.raises(RuntimeError, match="not yet completed"):
        ingest_batch(
            provider=ingest_provider, batch_id="batch_abc",
            flow="mapping.resolve_pending", version_constant="v3",
            on_result=lambda *a: None, batches_dir=tmp_path,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest common/tests/test_batch_runner.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Write `batch_runner.py`**

Create `common/src/common/llm/batch_runner.py`:

```python
"""Flow-agnostic submit / ingest orchestration for batch providers.

Callers provide:
- A list of `rows` (anything iterable; the orchestrator just enumerates them).
- `to_request(idx, row) -> BatchRequest` — builds the prompt.
- `row_to_id(row) -> str` — the row's identity for the sidecar.request_map.
- `on_result(row_id, raw_text, error) -> None` — per-result writer; bumps
  the appropriate counter in the caller's domain.

The orchestrator handles sidecar persistence + ingest dispatch + summary
counts. Each flow (mapping, dedup, classify) keeps its own parser and
DB writer; this module knows nothing about them.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .batch_provider import BatchProvider, BatchRequest, BatchResult, BatchSubmission
from .sidecar import Sidecar, load_sidecar, mark_ingested, write_sidecar


@dataclass(frozen=True)
class BatchSubmitOutcome:
    submission: BatchSubmission
    sidecar_path: Path


def submit_batch(
    *,
    provider: BatchProvider,
    rows: list,
    to_request: Callable[[int, object], BatchRequest],
    row_to_id: Callable[[object], str],
    flow: str,
    version_constant: str,
    batches_dir: Path,
) -> BatchSubmitOutcome:
    """Build batch requests from rows, submit, persist sidecar."""
    requests = []
    request_map: dict[str, str] = {}
    for idx, row in enumerate(rows):
        req = to_request(idx, row)
        requests.append(req)
        request_map[req.custom_id] = row_to_id(row)
    submission = provider.submit(requests)
    sc = Sidecar(
        batch_id=submission.batch_id,
        provider=submission.provider,
        flow=flow,
        model_id=submission.model_id,
        version_constant=version_constant,
        submitted_at=datetime.now(timezone.utc).isoformat(),
        request_map=request_map,
    )
    path = write_sidecar(sc, batches_dir=batches_dir)
    return BatchSubmitOutcome(submission=submission, sidecar_path=path)


def ingest_batch(
    *,
    provider: BatchProvider,
    batch_id: str,
    flow: str,
    version_constant: str,
    on_result: Callable[[str, str | None, str | None], None],
    batches_dir: Path,
) -> dict[str, int]:
    """Load sidecar, fetch results, dispatch each via on_result.
    Returns a dict with {'ok': N, 'error': M}.
    """
    sc = load_sidecar(
        batch_id, batches_dir=batches_dir,
        expected_flow=flow, expected_version=version_constant,
    )
    status = provider.status(batch_id)
    if status.state != "completed":
        raise RuntimeError(
            f"batch {batch_id} not yet completed (state={status.state!r}, "
            f"{status.completed}/{status.total})"
        )
    counts: Counter[str] = Counter()
    for r in provider.fetch_results(batch_id):
        row_id = sc.request_map.get(r.custom_id)
        if row_id is None:
            counts["unmapped"] += 1
            continue
        on_result(row_id, r.raw_text, r.error)
        counts["error" if r.error or r.raw_text is None else "ok"] += 1
    sidecar_path = batches_dir / f"{batch_id}.json"
    mark_ingested(sidecar_path)
    return dict(counts)
```

- [ ] **Step 4: Re-export in `__init__.py`**

Add to `common/src/common/llm/__init__.py`:

```python
from .batch_runner import BatchSubmitOutcome, ingest_batch, submit_batch
```

And update `__all__`:

```python
__all__ = [
    "BatchProvider", "BatchRequest", "BatchResult", "BatchStatus",
    "BatchSubmission", "BatchSubmitOutcome",
    "ClaudeProvider", "LLMProvider", "OllamaProvider", "OpenAIProvider",
    "OpenAIBatchProvider",
    "ProviderResult", "resolve_with_retry",
    "Sidecar", "SidecarMismatch", "load_sidecar", "mark_ingested", "write_sidecar",
    "ingest_batch", "submit_batch",
]
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest common/tests/test_batch_runner.py -v
```

Expected: 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add common.llm.batch_runner: flow-agnostic submit/ingest orchestrator

Each flow (mapping, dedup, classify) provides to_request/row_to_id
callbacks plus an on_result writer. The runner owns sidecar persistence,
status polling, and result fanout — flows stay focused on their own
parsing and DB writes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase E — Wire batch into ingredients flows

### Task 15: Add batch flag set to mapping `resolve-pending`

**Files:**
- Modify: `ingredients/src/ingredients/cli.py`
- Modify: `ingredients/src/ingredients/mapping/llm_resolver.py` (add batch helpers)
- Create: `ingredients/tests/test_mapping_resolve_pending_batch.py`

- [ ] **Step 1: Add batch CLI flags to map resolve-pending**

In `ingredients/src/ingredients/cli.py`, find the `_add_resolve_pending_args` function for map (around line 130). After the `--provider` and `--limit`/`--yes` args, add:

```python
    p.add_argument(
        "--batch", action="store_true",
        help="Use OpenAI Batch API (50%% off, ~24h SLA). "
             "Only valid with --provider openai.",
    )
    p.add_argument(
        "--ingest", metavar="BATCH_ID", default=None,
        help="Ingest results from a previously submitted batch. "
             "Implies --batch.",
    )
    p.add_argument(
        "--wait", action="store_true",
        help="With --batch, poll until completed and ingest in one command.",
    )
    p.add_argument(
        "--poll-interval", type=int, default=600,
        help="With --wait, seconds between status polls (default: 600).",
    )
    p.add_argument(
        "--model", default=None,
        help="Override the provider's default model id.",
    )
```

- [ ] **Step 2: Write the failing test**

Create `ingredients/tests/test_mapping_resolve_pending_batch.py`:

```python
"""End-to-end batch tests for `map resolve-pending --batch`.

These tests stub the batch provider (no live OpenAI calls) and exercise
the orchestrator's submit + ingest paths via the CLI handler. DB layer is
mocked at the resolver-call boundary."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingredients.mapping.llm_resolver import (
    submit_phase2_batch, ingest_phase2_batch,
)
from common.llm.batch_provider import BatchResult, BatchStatus, BatchSubmission


def _stub_batch_provider(batch_id="batch_abc"):
    p = MagicMock()
    p.model_id = "gpt-5-mini"
    p.submit.return_value = BatchSubmission(
        batch_id=batch_id, provider="openai",
        model_id="gpt-5-mini", request_count=2,
    )
    p.status.return_value = BatchStatus(
        batch_id=batch_id, state="completed", completed=2, total=2,
    )
    return p


def test_submit_phase2_batch_writes_sidecar(tmp_path, monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.fetch_pending_llm_names",
        lambda c, mapper_version, limit=None: ["vodka", "rye"],
    )
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver._candidates_with_parents",
        lambda c, n: [],
    )

    provider = _stub_batch_provider()
    outcome = submit_phase2_batch(
        conn, provider=provider, batches_dir=tmp_path, limit=None,
    )
    assert outcome.submission.batch_id == "batch_abc"
    assert (tmp_path / "batch_abc.json").exists()


def test_ingest_phase2_batch_dispatches_writes_per_action(tmp_path, monkeypatch):
    # Pre-populate the sidecar by simulating a submit.
    from common.llm.batch_runner import submit_batch
    from common.llm.batch_provider import BatchRequest

    submit_batch(
        provider=_stub_batch_provider(),
        rows=[("vodka", "s", "u0"), ("rye", "s", "u1")],
        to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
        row_to_id=lambda r: r[0],
        flow="mapping.resolve_pending",
        version_constant=__import__("ingredients.mapping.mapper", fromlist=["MAPPER_VERSION"]).MAPPER_VERSION,
        batches_dir=tmp_path,
    )

    # Wire ingest with a chose result + an abstain result.
    provider = MagicMock()
    provider.status.return_value = BatchStatus(
        batch_id="batch_abc", state="completed", completed=2, total=2,
    )
    provider.fetch_results.return_value = iter([
        BatchResult(custom_id="r0", raw_text='{"action": "chose", "node_id": 7}', error=None),
        BatchResult(custom_id="r1", raw_text='{"action": "abstain"}', error=None),
    ])

    writes_chose: list[tuple[str, int]] = []
    writes_abstain: list[str] = []
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.write_resolution",
        lambda conn, normalized_name, taxonomy_node_id, source, mapper_version: writes_chose.append((normalized_name, taxonomy_node_id)),
    )
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.write_abstain",
        lambda conn, normalized_name, mapper_version: writes_abstain.append(normalized_name),
    )

    counts = ingest_phase2_batch(
        conn=MagicMock(), provider=provider, batch_id="batch_abc",
        batches_dir=tmp_path,
    )
    assert ("vodka", 7) in writes_chose
    assert "rye" in writes_abstain
    assert counts["ok"] == 2
```

- [ ] **Step 3: Run test to verify failure**

```bash
uv run pytest ingredients/tests/test_mapping_resolve_pending_batch.py -v
```

Expected: FAIL — `submit_phase2_batch` / `ingest_phase2_batch` not defined.

- [ ] **Step 4: Add `submit_phase2_batch` and `ingest_phase2_batch` to `mapping/llm_resolver.py`**

Append to `ingredients/src/ingredients/mapping/llm_resolver.py` (alongside existing `run_phase2`):

```python
from common.llm.batch_provider import BatchProvider, BatchRequest
from common.llm.batch_runner import (
    BatchSubmitOutcome, ingest_batch, submit_batch,
)


def submit_phase2_batch(
    conn: psycopg.Connection,
    *,
    provider: BatchProvider,
    batches_dir,
    site: str | None = None,
    limit: int | None = None,
) -> BatchSubmitOutcome:
    """Submit pending names as an OpenAI batch. Returns the submission +
    sidecar path. Caller (CLI) prints the batch_id and exits."""
    names = fetch_pending_llm_names(conn, mapper_version=MAPPER_VERSION, limit=limit)
    if not names:
        raise RuntimeError("nothing pending; queue is empty")

    rows = []
    for n in names:
        cands = _candidates_with_parents(conn, n)
        user_prompt = build_user_prompt(
            normalized_name=n, parser_unit=None, site=site, candidates=cands,
        )
        rows.append((n, SYSTEM_PROMPT, user_prompt))

    return submit_batch(
        provider=provider, rows=rows,
        to_request=lambda i, r: BatchRequest(
            custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2],
        ),
        row_to_id=lambda r: r[0],
        flow="mapping.resolve_pending",
        version_constant=MAPPER_VERSION,
        batches_dir=batches_dir,
    )


def ingest_phase2_batch(
    conn: psycopg.Connection,
    *,
    provider: BatchProvider,
    batch_id: str,
    batches_dir,
) -> dict[str, int]:
    """Ingest a previously submitted batch's results. Per-row writes go
    through the same write_resolution / write_abstain / propose_brand
    paths as run_phase2."""

    def on_result(row_id: str, raw_text: str | None, error: str | None) -> None:
        if error or raw_text is None:
            log.warning("batch result error for %r: %s", row_id, error)
            return
        try:
            action_obj = parse_response(raw_text)
        except Exception as exc:
            log.warning("batch result parse failed for %r: %s", row_id, exc)
            return
        action = action_obj["action"]
        normalized = row_id

        if action == "chose":
            write_resolution(
                conn, normalized_name=normalized,
                taxonomy_node_id=int(action_obj["node_id"]),
                source="llm", mapper_version=MAPPER_VERSION,
            )
        elif action == "propose_brand":
            cands = _candidates_with_parents(conn, normalized)
            parent_id = _lookup_node_by_slug(conn, action_obj["parent_slug"])
            if parent_id is None:
                write_abstain(conn, normalized_name=normalized, mapper_version=MAPPER_VERSION)
                return
            try:
                new_id = _create_brand_node(
                    conn,
                    slug=action_obj["slug"],
                    display_name=action_obj["display_name"],
                    parent_id=parent_id,
                    node_kind=action_obj["node_kind"],
                    raw_string=normalized,
                    prompt_hash_value=prompt_hash(normalized, None, None, cands),
                    model_id=provider.model_id,
                )
                write_resolution(
                    conn, normalized_name=normalized, taxonomy_node_id=new_id,
                    source="llm", mapper_version=MAPPER_VERSION,
                )
            except Exception:
                conn.rollback()
                raise
        elif action == "propose_form":
            cands = _candidates_with_parents(conn, normalized)
            parent_id = _lookup_node_by_slug(conn, action_obj["parent_slug"])
            enqueue_form_proposal(
                conn,
                raw_string=normalized,
                proposed_slug=action_obj["slug"],
                proposed_display_name=action_obj["display_name"],
                proposed_parent_id=parent_id,
                candidates=cands,
                mapper_version=MAPPER_VERSION,
            )
        elif action == "abstain":
            write_abstain(conn, normalized_name=normalized, mapper_version=MAPPER_VERSION)

    return ingest_batch(
        provider=provider, batch_id=batch_id,
        flow="mapping.resolve_pending",
        version_constant=MAPPER_VERSION,
        on_result=on_result,
        batches_dir=batches_dir,
    )
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest ingredients/tests/test_mapping_resolve_pending_batch.py -v
```

Expected: 2 tests pass.

- [ ] **Step 6: Wire CLI to dispatch sync vs batch in `run_resolve_pending`**

Edit `ingredients/src/ingredients/cli.py` `run_resolve_pending`. Replace the body after the existing `if not args.yes:` confirmation prompt with a dispatch:

```python
def run_resolve_pending(args: argparse.Namespace) -> int:
    from ingredients.mapping.db import fetch_pending_llm_names
    from ingredients.mapping.llm_resolver import (
        run_phase2, submit_phase2_batch, ingest_phase2_batch,
    )
    from ingredients.mapping.mapper import MAPPER_VERSION
    from pathlib import Path

    BATCHES_DIR = Path("data/batches")

    # Validate flag combos
    if args.batch and args.provider != "openai":
        log.error("--batch requires --provider openai")
        return 2
    if args.ingest and not args.batch:
        # --ingest implies --batch
        args.batch = True
    if args.wait and args.ingest:
        log.error("--wait and --ingest are mutually exclusive")
        return 2

    db = IngredientsDatabase()
    try:
        # ---- Batch ingest path ----
        if args.batch and args.ingest:
            from common.llm.openai_batch import OpenAIBatchProvider
            provider = OpenAIBatchProvider.from_env(model_id=args.model or OpenAIBatchProvider.from_env().model_id)
            counts = ingest_phase2_batch(
                conn=db.conn, provider=provider,
                batch_id=args.ingest, batches_dir=BATCHES_DIR,
            )
            print_summary(
                f"Map resolve-pending ingest ({args.ingest})",
                {"all": Counter(counts)}, mode="applied",
            )
            return 0

        # ---- Pre-flight: count pending and confirm ----
        pending = fetch_pending_llm_names(db.conn, mapper_version=MAPPER_VERSION)
        if not pending:
            log.info("nothing pending; queue is empty")
            return 0

        log.info("%d distinct names pending Phase 2", len(pending))
        for n in pending[:20]:
            log.info("  %s", n)
        if len(pending) > 20:
            log.info("  ... and %d more", len(pending) - 20)

        if args.batch:
            mode = "OpenAI Batch API (50% off, ~24h SLA)"
        else:
            mode = f"--provider {args.provider}"
        if not args.yes:
            sys.stderr.write(f"Proceed with {mode}? [y/N]: ")
            sys.stderr.flush()
            answer = sys.stdin.readline().strip().lower()
            if answer not in ("y", "yes"):
                log.info("aborted by operator")
                return 1

        # ---- Batch submit (and optional --wait) path ----
        if args.batch:
            from common.llm.openai_batch import OpenAIBatchProvider
            provider = (
                OpenAIBatchProvider.from_env(model_id=args.model)
                if args.model else OpenAIBatchProvider.from_env()
            )
            outcome = submit_phase2_batch(
                db.conn, provider=provider,
                batches_dir=BATCHES_DIR, limit=args.limit,
            )
            print(
                f"submitted batch {outcome.submission.batch_id} "
                f"({outcome.submission.request_count} requests, model={outcome.submission.model_id})"
            )
            print(f"sidecar: {outcome.sidecar_path}")
            if args.wait:
                _wait_then_ingest_mapping(
                    db, provider, outcome.submission.batch_id,
                    BATCHES_DIR, args.poll_interval,
                )
            return 0

        # ---- Sync path (existing) ----
        if args.provider == "claude":
            from common.llm.claude import ClaudeProvider
            provider = ClaudeProvider.from_env(model_id=args.model) if args.model else ClaudeProvider.from_env()
        elif args.provider == "openai":
            from common.llm.openai import OpenAIProvider
            provider = OpenAIProvider.from_env(model_id=args.model) if args.model else OpenAIProvider.from_env()
        else:
            from common.llm.ollama import OllamaProvider
            provider = OllamaProvider.from_env(model_id=args.model) if args.model else OllamaProvider.from_env()

        summary = run_phase2(db.conn, provider=provider, limit=args.limit)
        changes = {"all": Counter(summary)}
        print_summary(
            f"Map resolve-pending ({args.provider}, {MAPPER_VERSION})",
            changes, mode="applied",
        )
        return 0
    finally:
        db.close()


def _wait_then_ingest_mapping(db, provider, batch_id, batches_dir, poll_interval):
    import time
    from ingredients.mapping.llm_resolver import ingest_phase2_batch
    from spiritolo_common.interrupt import InterruptHandler  # placeholder import — see note
    log.info("polling batch %s every %ds…", batch_id, poll_interval)
    with InterruptHandler() as interrupt:
        while True:
            if interrupt.requested:
                log.info("interrupted; batch %s remains submitted, run --ingest later", batch_id)
                return
            st = provider.status(batch_id)
            log.info("status=%s (%d/%d)", st.state, st.completed, st.total)
            if st.state == "completed":
                break
            if st.state in ("failed", "expired", "cancelled"):
                log.error("batch ended in state %s", st.state)
                return
            time.sleep(poll_interval)
    counts = ingest_phase2_batch(
        conn=db.conn, provider=provider,
        batch_id=batch_id, batches_dir=batches_dir,
    )
    print_summary(
        f"Map resolve-pending ingest ({batch_id})",
        {"all": Counter(counts)}, mode="applied",
    )
```

CRITICAL: the placeholder `from spiritolo_common.interrupt import InterruptHandler` is WRONG given the rename in Task 1. The correct import is `from common.interrupt import InterruptHandler`. Fix it inline:

```python
    from common.interrupt import InterruptHandler
```

- [ ] **Step 7: Verify CLI parses end-to-end**

```bash
uv run python -m ingredients.cli map resolve-pending --provider openai --batch --help
```

Expected: argparse output, no error.

- [ ] **Step 8: Run all mapping tests**

```bash
uv run pytest ingredients/tests/ -v -k mapping
```

Expected: passes (DB tests skip without `TEST_DB_URL`).

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Wire batch flags into mapping resolve-pending

--batch dispatches to OpenAIBatchProvider.submit (default), or --ingest
BATCH_ID to drain a previously submitted batch, or --wait to poll inline.
Sidecar at data/batches/<batch_id>.json keys results back to row identity.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 16: Add batch flag set to dedup `normalize-names resolve-pending`

**Files:**
- Modify: `ingredients/src/ingredients/cli.py`
- Modify: `ingredients/src/ingredients/dedup/normalizer_llm.py`
- Create: `ingredients/tests/test_normalize_names_resolve_pending_batch.py`

- [ ] **Step 1: Add the same batch flags to `_add_resolve_pending_norm_args`**

Locate the normalize-names resolve-pending arg parser in `ingredients/src/ingredients/cli.py` (around line 159). Append the same flag block as in Task 15 step 1: `--batch`, `--ingest`, `--wait`, `--poll-interval`, `--model`.

- [ ] **Step 2: Write the failing test**

Create `ingredients/tests/test_normalize_names_resolve_pending_batch.py`:

```python
from unittest.mock import MagicMock

from common.llm.batch_provider import BatchRequest, BatchResult, BatchStatus, BatchSubmission
from ingredients.dedup.normalizer_llm import (
    submit_normalize_names_batch, ingest_normalize_names_batch,
)
from ingredients.dedup.version import NORMALIZER_VERSION


def _stub_batch_provider(batch_id="batch_xyz"):
    p = MagicMock()
    p.model_id = "gpt-5-mini"
    p.submit.return_value = BatchSubmission(
        batch_id=batch_id, provider="openai",
        model_id="gpt-5-mini", request_count=2,
    )
    p.status.return_value = BatchStatus(
        batch_id=batch_id, state="completed", completed=2, total=2,
    )
    return p


def test_submit_writes_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ingredients.dedup.normalizer_llm.fetch_pending_canonical_names",
        lambda c, normalizer_version, limit=None: ["The Pegu Club", "negroni sbagliato"],
    )
    monkeypatch.setattr(
        "ingredients.dedup.normalizer_llm.lexical_candidates",
        lambda c, n, limit=20: [],
    )

    provider = _stub_batch_provider()
    outcome = submit_normalize_names_batch(
        MagicMock(), provider=provider, batches_dir=tmp_path,
    )
    assert outcome.submission.batch_id == "batch_xyz"
    assert (tmp_path / "batch_xyz.json").exists()


def test_ingest_dispatches_chose_and_propose(tmp_path, monkeypatch):
    from common.llm.batch_runner import submit_batch
    submit_batch(
        provider=_stub_batch_provider(),
        rows=[("Pegu Club", "s", "u0"), ("Negroni Sbagliato", "s", "u1")],
        to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
        row_to_id=lambda r: r[0],
        flow="dedup.normalize_names.resolve_pending",
        version_constant=NORMALIZER_VERSION,
        batches_dir=tmp_path,
    )

    provider = MagicMock()
    provider.status.return_value = BatchStatus(
        batch_id="batch_xyz", state="completed", completed=2, total=2,
    )
    provider.fetch_results.return_value = iter([
        BatchResult(custom_id="r0", raw_text='{"action": "chose", "canonical_name": "Pegu Club"}', error=None),
        BatchResult(custom_id="r1", raw_text='{"action": "propose", "canonical_name": "Negroni Sbagliato"}', error=None),
    ])

    writes_norm: list[tuple[str, str]] = []
    writes_alias: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "ingredients.dedup.normalizer_llm.write_normalization",
        lambda conn, raw_name, normalized, canonical_name, source, normalizer_version: writes_norm.append((raw_name, canonical_name)),
    )
    monkeypatch.setattr(
        "ingredients.dedup.normalizer_llm.add_cocktail_alias",
        lambda conn, alias, canonical_name, source: writes_alias.append((alias, canonical_name)),
    )

    counts = ingest_normalize_names_batch(
        conn=MagicMock(), provider=provider, batch_id="batch_xyz",
        batches_dir=tmp_path,
    )
    assert ("Pegu Club", "Pegu Club") in writes_norm
    assert ("Negroni Sbagliato", "Negroni Sbagliato") in writes_norm
    assert any(a == "negroni sbagliato" for a, _ in writes_alias)
    assert counts["ok"] == 2
```

- [ ] **Step 3: Run test to verify failure**

```bash
uv run pytest ingredients/tests/test_normalize_names_resolve_pending_batch.py -v
```

Expected: FAIL — functions not defined.

- [ ] **Step 4: Add `submit_normalize_names_batch` + `ingest_normalize_names_batch` to `dedup/normalizer_llm.py`**

Append to `ingredients/src/ingredients/dedup/normalizer_llm.py`:

```python
from common.llm.batch_provider import BatchProvider, BatchRequest
from common.llm.batch_runner import (
    BatchSubmitOutcome, ingest_batch, submit_batch,
)


def submit_normalize_names_batch(
    conn: psycopg.Connection,
    *,
    provider: BatchProvider,
    batches_dir,
    limit: int | None = None,
) -> BatchSubmitOutcome:
    """Submit pending canonical-name resolutions as an OpenAI batch."""
    raw_names = fetch_pending_canonical_names(
        conn, normalizer_version=NORMALIZER_VERSION, limit=limit,
    )
    if not raw_names:
        raise RuntimeError("nothing pending; queue is empty")

    rows = []
    for raw in raw_names:
        normalized = normalize_cocktail_name(raw)
        cands = lexical_candidates(conn, normalized, limit=20)
        user_prompt = build_user_prompt(
            raw_name=raw, normalized=normalized, candidates=cands,
        )
        rows.append((raw, SYSTEM_PROMPT, user_prompt))

    return submit_batch(
        provider=provider, rows=rows,
        to_request=lambda i, r: BatchRequest(
            custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2],
        ),
        row_to_id=lambda r: r[0],
        flow="dedup.normalize_names.resolve_pending",
        version_constant=NORMALIZER_VERSION,
        batches_dir=batches_dir,
    )


def ingest_normalize_names_batch(
    conn: psycopg.Connection,
    *,
    provider: BatchProvider,
    batch_id: str,
    batches_dir,
) -> dict[str, int]:
    """Ingest a previously submitted normalize-names batch."""

    def on_result(row_id: str, raw_text: str | None, error: str | None) -> None:
        if error or raw_text is None:
            log.warning("batch result error for %r: %s", row_id, error)
            return
        try:
            action_obj = _parse_response(raw_text)
        except Exception as exc:
            log.warning("batch result parse failed for %r: %s", row_id, exc)
            return
        action = action_obj["action"]
        raw = row_id
        normalized = normalize_cocktail_name(raw)

        if action == "chose":
            canonical = action_obj["canonical_name"]
            write_normalization(
                conn, raw_name=raw, normalized=normalized,
                canonical_name=canonical, source="llm",
                normalizer_version=NORMALIZER_VERSION,
            )
        elif action == "propose":
            canonical = action_obj["canonical_name"]
            add_cocktail_alias(
                conn, alias=normalized, canonical_name=canonical, source="llm",
            )
            write_normalization(
                conn, raw_name=raw, normalized=normalized,
                canonical_name=canonical, source="llm",
                normalizer_version=NORMALIZER_VERSION,
            )
        elif action == "abstain":
            write_normalize_abstain(
                conn, raw_name=raw, normalizer_version=NORMALIZER_VERSION,
            )

    return ingest_batch(
        provider=provider, batch_id=batch_id,
        flow="dedup.normalize_names.resolve_pending",
        version_constant=NORMALIZER_VERSION,
        on_result=on_result,
        batches_dir=batches_dir,
    )
```

- [ ] **Step 5: Run test**

```bash
uv run pytest ingredients/tests/test_normalize_names_resolve_pending_batch.py -v
```

Expected: 2 tests pass.

- [ ] **Step 6: Wire CLI dispatch for normalize-names resolve-pending**

In `ingredients/src/ingredients/cli.py`, locate the existing normalize-names resolve-pending handler (around line 510). Replace it with the same dispatch shape used in Task 15 step 6, but pointing at:

- `ingredients.dedup.normalizer_llm.run_phase2` (sync)
- `ingredients.dedup.normalizer_llm.submit_normalize_names_batch`
- `ingredients.dedup.normalizer_llm.ingest_normalize_names_batch`
- version constant: `NORMALIZER_VERSION` (`from ingredients.dedup.version import NORMALIZER_VERSION`)
- summary label: `f"normalize-names resolve-pending ({args.provider}, {NORMALIZER_VERSION})"`

(Mirror Task 15's structure exactly — same `--batch`/`--ingest`/`--wait` validation, same `_wait_then_ingest_*` helper but pointing at `ingest_normalize_names_batch`.)

- [ ] **Step 7: Verify CLI parses**

```bash
uv run python -m ingredients.cli normalize-names resolve-pending --provider openai --batch --help
```

Expected: argparse output, no error.

- [ ] **Step 8: Run all dedup tests**

```bash
uv run pytest ingredients/tests/ -v -k 'dedup or normalize'
```

Expected: passes.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Wire batch flags into dedup normalize-names resolve-pending

Same flag set + dispatch shape as mapping resolve-pending; sidecar tagged
flow=dedup.normalize_names.resolve_pending so cross-flow ingest is
refused.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F — Scraper classify refactor

### Task 17: Refactor `classify` + `ollama_client` to use `LLMProvider` Protocol

**Files:**
- Modify: `scraper/src/scraper/ollama_client.py`
- Modify: `scraper/src/scraper/classify.py`
- Modify: `scraper/tests/test_ollama_client.py` (update for new signature)
- Modify: `scraper/tests/test_classify.py` (update for new wiring)

- [ ] **Step 1: Read the existing async ollama_client.classify_url to confirm signature**

```bash
grep -n 'classify_url\|AsyncClient\|def \|class ' scraper/src/scraper/ollama_client.py
```

Note the current shape:
- async def classify_url(url, sitemap_source, model, host=None, client=None) -> ClassificationResult
- Uses `ollama.AsyncClient.chat(...)` with `format=RESPONSE_SCHEMA`.

Decision: keep `classify_url()` as the public sync function (drop async). The new Protocol is sync. Concurrency moves from `asyncio` to `concurrent.futures.ThreadPoolExecutor` in `run_classify_pool`.

- [ ] **Step 2: Rewrite `ollama_client.py` to use the Protocol**

Replace `scraper/src/scraper/ollama_client.py` with:

```python
"""Sync wrapper that asks an LLMProvider to classify one URL.

Prompt assembly stays here (in scraper, where the prompt module lives).
The LLM call itself goes through common.llm.LLMProvider, so any sync
provider — Ollama, Claude, OpenAI — can drive classify.
"""

import json
import time
from dataclasses import dataclass

from common.llm.provider import LLMProvider

from scraper.classify_prompt import (
    LABELS,
    SYSTEM_PROMPT,
    build_user_message,
)


@dataclass
class ClassificationResult:
    label: str
    raw_response: str
    latency_ms: int


def classify_url(
    *,
    url: str,
    sitemap_source: str | None,
    provider: LLMProvider,
) -> ClassificationResult:
    """Ask `provider` to classify one URL. Returns ClassificationResult or raises.

    Raises ValueError for malformed JSON or out-of-enum responses.
    Transport errors bubble up from the underlying provider unchanged so the
    caller can decide retry policy.
    """
    user = build_user_message(url, sitemap_source)
    start = time.monotonic()
    result = provider.resolve(system_prompt=SYSTEM_PROMPT, user_prompt=user)
    latency_ms = int((time.monotonic() - start) * 1000)
    raw = result.raw_text

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"malformed JSON from model: {raw!r}") from e

    label = payload.get("label")
    if label not in LABELS:
        raise ValueError(f"invalid label {label!r} (raw={raw!r})")

    return ClassificationResult(label=label, raw_response=raw, latency_ms=latency_ms)
```

- [ ] **Step 3: Update `scraper/tests/test_ollama_client.py` for the new signature**

Replace the existing test body with:

```python
from unittest.mock import MagicMock

import pytest

from common.llm.provider import ProviderResult
from scraper.ollama_client import ClassificationResult, classify_url


def _stub_provider(reply: str) -> MagicMock:
    p = MagicMock()
    p.resolve.return_value = ProviderResult(raw_text=reply, model_id="qwen3:14b")
    return p


def test_classify_url_returns_label():
    provider = _stub_provider('{"label": "recipe"}')
    out = classify_url(
        url="https://example.com/recipes/margarita",
        sitemap_source=None, provider=provider,
    )
    assert out.label == "recipe"
    assert out.raw_response == '{"label": "recipe"}'
    assert out.latency_ms >= 0
    provider.resolve.assert_called_once()


def test_classify_url_raises_on_malformed_json():
    provider = _stub_provider("not json")
    with pytest.raises(ValueError, match="malformed JSON"):
        classify_url(url="https://x", sitemap_source=None, provider=provider)


def test_classify_url_raises_on_unknown_label():
    provider = _stub_provider('{"label": "nonsense"}')
    with pytest.raises(ValueError, match="invalid label"):
        classify_url(url="https://x", sitemap_source=None, provider=provider)
```

- [ ] **Step 4: Refactor `scraper/src/scraper/classify.py` to thread a provider through**

In `scraper/src/scraper/classify.py`:

1. Drop `from ollama import AsyncClient`.
2. Drop the `async def classify_one` / `async def run_classify_pool` async machinery; replace with a sync threadpool variant. New signatures:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def classify_one(
    row: dict,
    provider,
    db: Database,
    prompt_version: str,
    run_id: int | None = None,
) -> bool:
    try:
        result = classify_url(
            url=row["url"],
            sitemap_source=row.get("sitemap_source"),
            provider=provider,
        )
    except Exception as e:
        log.warning("classify failed for id=%s url=%s: %s", row["id"], row["url"], e, exc_info=True)
        return False

    db.record_classify_url(
        page_id=row["id"],
        run_id=run_id,
        label=result.label,
        model=provider.model_id,
        prompt_version=prompt_version,
        raw_response=result.raw_response,
        latency_ms=result.latency_ms,
        pages_content_type_before=row.get("content_type"),
    )
    return True


def run_classify_pool(
    rows: list[dict],
    provider,
    db: Database,
    prompt_version: str,
    concurrency: int = 4,
    on_progress=None,
    run_id: int | None = None,
) -> int:
    total = len(rows)
    done = 0
    successes = 0
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {ex.submit(classify_one, r, provider, db, prompt_version, run_id): r for r in rows}
        for fut in as_completed(futures):
            ok = fut.result()
            if ok:
                successes += 1
            done += 1
            if on_progress:
                on_progress(done, total)
    return successes
```

3. Update `run_main` to instantiate a sync provider (default ollama) instead of `AsyncClient`. Replace the asyncio shim:

```python
async def run_main(args): ...
async def classify_with_shared(...): ...
```

with a sync version:

```python
def run_main(args: argparse.Namespace) -> int:
    db = Database(args.db)
    remaining = args.limit
    grand_total = 0
    exit_code = 0

    provider = _build_provider(args)

    overall_total = db.count_unclassified(site=args.site)
    if args.limit is not None:
        overall_total = min(overall_total, args.limit)

    progress = make_progress(total=overall_total)
    changes: dict[str, Counter] = {}

    def adapter(batch_done: int, _batch_total: int) -> None:
        progress(grand_total + batch_done)

    run_id = db.start_run(
        stage="classify_url",
        site=args.site,
        args={
            "limit": args.limit, "batch_size": args.batch_size,
            "model": provider.model_id, "concurrency": args.concurrency,
            "prompt_version": PROMPT_VERSION,
        },
    )

    try:
        while True:
            if remaining is not None and remaining <= 0:
                break
            batch_limit = args.batch_size if remaining is None else min(args.batch_size, remaining)
            rows = db.get_unclassified(site=args.site, limit=batch_limit)
            if not rows:
                break

            if grand_total == 0:
                scope = f"site={args.site}" if args.site else "all sites"
                log.info(
                    "classifying %s URLs (%s) via %s (concurrency=%d, batch_size=%d, prompt=%s)",
                    f"{overall_total:,}", scope, provider.model_id,
                    args.concurrency, args.batch_size, PROMPT_VERSION,
                )

            batch_urls = [r["url"] for r in rows]
            successes = run_classify_pool(
                rows=rows,
                provider=provider,
                db=db,
                prompt_version=PROMPT_VERSION,
                concurrency=args.concurrency,
                on_progress=adapter,
                run_id=run_id,
            )
            _accumulate_changes(db, batch_urls, changes)

            if successes == 0:
                print(
                    f"ERROR: batch of {len(rows)} produced zero classifications. "
                    "Check provider connectivity. Aborting to avoid an infinite loop.",
                    file=sys.stderr,
                )
                exit_code = 1
                break

            grand_total += len(rows)
            if remaining is not None:
                remaining -= len(rows)

        print_summary("Classify", changes)
        summary_dict = {site_key: dict(counter) for site_key, counter in changes.items()}
        db.finish_run(run_id, summary={
            "per_site": summary_dict, "total": grand_total, "exit_code": exit_code,
        })
    finally:
        db.close()
    return exit_code


def _build_provider(args: argparse.Namespace):
    """Instantiate the chosen sync LLM provider."""
    provider_name = getattr(args, "provider", "ollama") or "ollama"
    model = getattr(args, "model", None)
    if provider_name == "ollama":
        from common.llm.ollama import OllamaProvider
        return OllamaProvider.from_env(model_id=model) if model else OllamaProvider.from_env()
    if provider_name == "claude":
        from common.llm.claude import ClaudeProvider
        return ClaudeProvider.from_env(model_id=model) if model else ClaudeProvider.from_env()
    if provider_name == "openai":
        from common.llm.openai import OpenAIProvider
        return OpenAIProvider.from_env(model_id=model) if model else OpenAIProvider.from_env()
    raise ValueError(f"unknown provider {provider_name!r}")
```

4. Update `main()` to call `run_main(args)` directly (no `asyncio.run`):

```python
def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    args = build_arg_parser().parse_args(argv)

    if args.sample:
        return _run_sample(args)
    if args.review:
        return _run_review(args)    # now sync
    if args.reset:
        rc = _do_reset(args)
        if rc != 0:
            return rc
    return run_main(args)
```

5. Update `run_review`/`_run_review` to use the provider too:

```python
def run_review(eval_path: Path, provider) -> int:
    entries = load_eval_set(eval_path)
    correct = 0
    failures: list[tuple[dict, str]] = []
    for e in entries:
        try:
            result = classify_url(
                url=e["url"], sitemap_source=e.get("sitemap_source"),
                provider=provider,
            )
            predicted = result.label
        except Exception as err:
            predicted = f"ERROR: {err}"
        expected = e["expected"]
        if predicted == expected:
            correct += 1
        else:
            failures.append((e, predicted))

    total = len(entries)
    print(f"{correct}/{total} correct ({100*correct/total:.1f}%)")
    if failures:
        print("\nFailures:")
        for e, predicted in failures:
            print(f"  {e['url']}")
            print(f"    expected:  {e['expected']}")
            print(f"    predicted: {predicted}")
    return 0 if correct == total else 1


def _run_review(args: argparse.Namespace) -> int:
    return run_review(eval_path=DEFAULT_EVAL_PATH, provider=_build_provider(args))
```

6. Update `build_arg_parser()` — keep `--model qwen3:14b` as default but note it's now provider-specific (default applies for ollama; user must override for claude/openai). Add `--provider`:

```python
    p.add_argument(
        "--provider", choices=["ollama", "claude", "openai"], default="ollama",
        help="LLM provider for classification (default: ollama, free local).",
    )
    p.add_argument("--model", default="qwen3:14b",
                   help="Model id for the chosen provider (default: qwen3:14b for ollama). "
                        "For claude pass e.g. claude-haiku-4-5; for openai pass e.g. gpt-5-mini.")
```

(Drop the existing dedicated `--model qwen3:14b` arg — replaced by the line above.)

- [ ] **Step 5: Update `scraper/tests/test_classify.py`**

The existing test mocks an `AsyncClient`. Change strategy:

```bash
grep -n 'AsyncClient\|asyncio\|classify_with_shared\|run_classify_pool\|classify_url' scraper/tests/test_classify.py | head -30
```

For any test that constructs an AsyncClient or calls an async function, rewrite to:
- Build a stub provider returning canned `ProviderResult`.
- Call the new sync `run_classify_pool` / `classify_one` directly.
- Replace `asyncio.run(...)` with a direct call.

(Specific edits depend on the existing test shape. The hand-edit principle: every test that exercised the async ollama path now exercises a stub provider returning a `ProviderResult`. Use `MagicMock(spec=LLMProvider)` style stubs.)

- [ ] **Step 6: Drop `ollama` dep from `scraper/pyproject.toml`**

```diff
 dependencies = [
     "spiritolo-common",
     "requests>=2.31",
     "lxml>=5.0",
     "pyyaml>=6.0",
     "cssselect>=1.2",
     "python-dotenv>=1.0",
-    "ollama>=0.4",
     "psycopg[binary]>=3.2",
     "beautifulsoup4>=4.12",
     "extruct>=0.18.0",
 ]
```

- [ ] **Step 7: Reinstall**

```bash
cd /workspaces/spiritolo && uv sync --all-packages
```

- [ ] **Step 8: Run all scraper tests**

```bash
cd /workspaces/spiritolo && uv run pytest scraper/tests/ -v
```

Expected: passes (or, if classify-related tests need further hand-edits, fix them now and re-run).

- [ ] **Step 9: Smoke-test the CLI binary parses**

```bash
uv run python -m scraper.classify --help
```

Expected: shows `--provider {ollama,claude,openai}` in usage.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Refactor scraper.classify to use common.llm.LLMProvider

ollama_client now takes any sync LLMProvider. classify dropped asyncio
in favor of a ThreadPoolExecutor; gains --provider {ollama,claude,openai}.
Default stays ollama. ollama dep removed from scraper (unified through
common's httpx-based OllamaProvider).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 18: Add batch flags to scraper `classify`

**Files:**
- Modify: `scraper/src/scraper/classify.py`
- Create: `scraper/tests/test_classify_batch.py`

- [ ] **Step 1: Add batch flags to `build_arg_parser`**

In `scraper/src/scraper/classify.py` `build_arg_parser`, after the `--provider`/`--model` args, add:

```python
    p.add_argument(
        "--batch", action="store_true",
        help="Use OpenAI Batch API. Only valid with --provider openai.",
    )
    p.add_argument(
        "--ingest", metavar="BATCH_ID", default=None,
        help="Ingest a previously submitted classify batch.",
    )
    p.add_argument(
        "--wait", action="store_true",
        help="With --batch, poll until completed and ingest in one command.",
    )
    p.add_argument(
        "--poll-interval", type=int, default=600,
        help="With --wait, seconds between status polls (default: 600).",
    )
```

- [ ] **Step 2: Write failing test**

Create `scraper/tests/test_classify_batch.py`:

```python
from unittest.mock import MagicMock

import pytest

from common.llm.batch_provider import BatchRequest, BatchResult, BatchStatus, BatchSubmission
from scraper.classify import submit_classify_batch, ingest_classify_batch
from scraper.classify_prompt import PROMPT_VERSION


def _stub_batch_provider(batch_id="batch_cls"):
    p = MagicMock()
    p.model_id = "gpt-5-mini"
    p.submit.return_value = BatchSubmission(
        batch_id=batch_id, provider="openai",
        model_id="gpt-5-mini", request_count=2,
    )
    p.status.return_value = BatchStatus(
        batch_id=batch_id, state="completed", completed=2, total=2,
    )
    return p


def test_submit_writes_sidecar(tmp_db, tmp_path):
    from scraper.db import Database
    db = Database(tmp_db)
    try:
        # Insert two unclassified pages.
        db.conn.executemany(
            "INSERT INTO pages(site, url, content_type, sitemap_source) VALUES (?, ?, NULL, ?)",
            [("punch", "https://punch/a", None), ("punch", "https://punch/b", None)],
        )
        db.conn.commit()
        provider = _stub_batch_provider()
        outcome = submit_classify_batch(
            db, provider=provider, batches_dir=tmp_path,
            site="punch", limit=None,
        )
        assert outcome.submission.batch_id == "batch_cls"
        assert (tmp_path / "batch_cls.json").exists()
    finally:
        db.close()


def test_ingest_writes_classify_runs(tmp_db, tmp_path, monkeypatch):
    from common.llm.batch_runner import submit_batch
    from scraper.db import Database
    db = Database(tmp_db)
    try:
        db.conn.executemany(
            "INSERT INTO pages(site, url, content_type, sitemap_source) VALUES (?, ?, NULL, ?)",
            [("punch", "https://punch/a", None), ("punch", "https://punch/b", None)],
        )
        db.conn.commit()

        # Pre-populate sidecar by simulating a submit (use real submit_batch
        # so the request_map matches what ingest will look up).
        rows = [(r["url"], "s", "u") for r in db.get_unclassified(site="punch", limit=2)]
        submit_batch(
            provider=_stub_batch_provider(),
            rows=rows,
            to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
            row_to_id=lambda r: r[0],
            flow="scraper.classify.url",
            version_constant=PROMPT_VERSION,
            batches_dir=tmp_path,
        )

        provider = MagicMock()
        provider.status.return_value = BatchStatus(
            batch_id="batch_cls", state="completed", completed=2, total=2,
        )
        provider.fetch_results.return_value = iter([
            BatchResult(custom_id="r0", raw_text='{"label":"recipe"}', error=None),
            BatchResult(custom_id="r1", raw_text='{"label":"index"}', error=None),
        ])

        counts = ingest_classify_batch(
            db=db, provider=provider, batch_id="batch_cls",
            batches_dir=tmp_path,
        )
        # Both rows now have content_type set.
        labels = [r["content_type"] for r in db.conn.execute(
            "SELECT content_type FROM pages WHERE site='punch' ORDER BY url"
        ).fetchall()]
        assert labels == ["recipe", "index"]
        assert counts["ok"] == 2
    finally:
        db.close()
```

(Both tests use `tmp_db` fixture from `scraper/tests/conftest.py` — already migrates the schema.)

- [ ] **Step 3: Run tests to verify failure**

```bash
uv run pytest scraper/tests/test_classify_batch.py -v
```

Expected: FAIL — `submit_classify_batch` / `ingest_classify_batch` not defined.

- [ ] **Step 4: Add submit/ingest helpers + CLI dispatch to `scraper/src/scraper/classify.py`**

Append to `scraper/src/scraper/classify.py`:

```python
from common.llm.batch_provider import BatchProvider, BatchRequest
from common.llm.batch_runner import (
    BatchSubmitOutcome, ingest_batch, submit_batch,
)


def submit_classify_batch(
    db: Database,
    *,
    provider: BatchProvider,
    batches_dir: Path,
    site: str | None,
    limit: int | None,
) -> BatchSubmitOutcome:
    """Submit unclassified pages as an OpenAI batch."""
    rows = db.get_unclassified(site=site, limit=limit)
    if not rows:
        raise RuntimeError("nothing pending; queue is empty")

    payload = []
    for r in rows:
        user = build_user_message(r["url"], r.get("sitemap_source"))
        payload.append((r["url"], SYSTEM_PROMPT, user))

    return submit_batch(
        provider=provider, rows=payload,
        to_request=lambda i, p: BatchRequest(
            custom_id=f"r{i}", system_prompt=p[1], user_prompt=p[2],
        ),
        row_to_id=lambda p: p[0],     # the URL
        flow="scraper.classify.url",
        version_constant=PROMPT_VERSION,
        batches_dir=batches_dir,
    )


def ingest_classify_batch(
    *,
    db: Database,
    provider: BatchProvider,
    batch_id: str,
    batches_dir: Path,
    run_id: int | None = None,
) -> dict[str, int]:
    """Ingest results from a previously submitted classify batch."""
    def on_result(row_id: str, raw_text: str | None, error: str | None) -> None:
        url = row_id
        if error or raw_text is None:
            log.warning("classify batch error for %s: %s", url, error)
            return
        try:
            payload = json.loads(raw_text)
            label = payload.get("label")
            if label not in LABELS:
                log.warning("classify batch invalid label %r for %s", label, url)
                return
        except Exception as exc:
            log.warning("classify batch parse failed for %s: %s", url, exc)
            return

        page_row = db.conn.execute(
            "SELECT id, content_type FROM pages WHERE url = ?", (url,)
        ).fetchone()
        if page_row is None:
            log.warning("classify batch URL no longer in pages: %s", url)
            return
        db.record_classify_url(
            page_id=page_row["id"],
            run_id=run_id,
            label=label,
            model=provider.model_id,
            prompt_version=PROMPT_VERSION,
            raw_response=raw_text,
            latency_ms=0,    # batch path: latency not meaningful
            pages_content_type_before=page_row["content_type"],
        )

    return ingest_batch(
        provider=provider, batch_id=batch_id,
        flow="scraper.classify.url",
        version_constant=PROMPT_VERSION,
        on_result=on_result,
        batches_dir=batches_dir,
    )
```

Also add `from scraper.classify_prompt import LABELS` (next to the existing `from scraper.classify_prompt import PROMPT_VERSION` line).

- [ ] **Step 5: Wire CLI to dispatch sync vs batch in `main()`**

Replace the existing tail of `main()`:

```python
    return run_main(args)
```

with:

```python
    if args.batch and args.provider != "openai":
        print("ERROR: --batch requires --provider openai", file=sys.stderr)
        return 2
    if args.ingest and not args.batch:
        args.batch = True
    if args.wait and args.ingest:
        print("ERROR: --wait and --ingest are mutually exclusive", file=sys.stderr)
        return 2
    if args.batch and args.review:
        print("ERROR: --review is sync-only; cannot combine with --batch", file=sys.stderr)
        return 2

    if args.batch:
        return run_batch(args)
    return run_main(args)
```

And add a new `run_batch` function:

```python
def run_batch(args: argparse.Namespace) -> int:
    from common.llm.openai_batch import OpenAIBatchProvider
    from common.interrupt import InterruptHandler
    BATCHES_DIR = Path("data/batches")

    db = Database(args.db)
    try:
        provider_kwargs = {"model_id": args.model} if args.model and args.model != "qwen3:14b" else {}
        provider = OpenAIBatchProvider.from_env(**provider_kwargs)

        if args.ingest:
            counts = ingest_classify_batch(
                db=db, provider=provider, batch_id=args.ingest,
                batches_dir=BATCHES_DIR,
            )
            print_summary(f"Classify ingest ({args.ingest})", {"all": Counter(counts)})
            return 0

        outcome = submit_classify_batch(
            db, provider=provider, batches_dir=BATCHES_DIR,
            site=args.site, limit=args.limit,
        )
        print(
            f"submitted batch {outcome.submission.batch_id} "
            f"({outcome.submission.request_count} requests, model={outcome.submission.model_id})"
        )
        print(f"sidecar: {outcome.sidecar_path}")

        if args.wait:
            log.info("polling batch %s every %ds…", outcome.submission.batch_id, args.poll_interval)
            with InterruptHandler() as interrupt:
                while True:
                    if interrupt.requested:
                        log.info("interrupted; batch remains submitted, run --ingest later")
                        return 0
                    st = provider.status(outcome.submission.batch_id)
                    log.info("status=%s (%d/%d)", st.state, st.completed, st.total)
                    if st.state == "completed":
                        break
                    if st.state in ("failed", "expired", "cancelled"):
                        log.error("batch ended in state %s", st.state)
                        return 1
                    time.sleep(args.poll_interval)
            counts = ingest_classify_batch(
                db=db, provider=provider, batch_id=outcome.submission.batch_id,
                batches_dir=BATCHES_DIR,
            )
            print_summary(
                f"Classify ingest ({outcome.submission.batch_id})",
                {"all": Counter(counts)},
            )
        return 0
    finally:
        db.close()
```

Add `import time` at top of `scraper/src/scraper/classify.py` if not already there.

- [ ] **Step 6: Run tests**

```bash
uv run pytest scraper/tests/test_classify_batch.py -v
```

Expected: 2 tests pass.

- [ ] **Step 7: Smoke-test CLI**

```bash
uv run python -m scraper.classify --help
```

Expected: shows `--batch`, `--ingest`, `--wait`, `--poll-interval`.

- [ ] **Step 8: Run full scraper test suite**

```bash
uv run pytest scraper/tests/ -v
```

Expected: passes.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Wire batch flags into scraper.classify

submit_classify_batch / ingest_classify_batch use the same flow-agnostic
runner as mapping/dedup. Sidecar tagged flow=scraper.classify.url and
version_constant=PROMPT_VERSION so cross-flow ingest is refused.
PROMPT_VERSION bumps invalidate stale sidecars.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase G — Documentation

### Task 19: Update CLAUDE.md and docs/

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/pipeline.md` (if relevant)

- [ ] **Step 1: Update CLAUDE.md "Pipeline conventions" section**

In `CLAUDE.md`, locate the "Pipeline conventions" / "Pipeline stages" sections that document `--provider {claude,ollama}`. Update each to:

- Mention `--provider openai` as a third sync option requiring `OPENAI_API_KEY`.
- Add a "Batch mode" subsection under each affected stage describing:

```
**Batch mode (OpenAI only).** For bulk re-runs (after a version bump), use
the OpenAI Batch API: 50% off real-time, ~24h SLA. Submit once, ingest
later.

cd ingredients && uv run python -m ingredients.cli map resolve-pending \
  --provider openai --batch --yes
# prints batch_id and sidecar path; exits.

cd ingredients && uv run python -m ingredients.cli map resolve-pending \
  --provider openai --batch --ingest <batch_id>
# fetches results, writes through the same chose/propose/abstain paths.

# One-shot (blocks): submit + poll + ingest in one command.
cd ingredients && uv run python -m ingredients.cli map resolve-pending \
  --provider openai --batch --wait --yes

Sidecar lives at data/batches/<batch_id>.json (gitignored). Lose it and
you must re-derive from the OpenAI dashboard or re-submit.
```

Repeat the same block under the `normalize-names resolve-pending` section and the `classify` section. Adjust commands per flow.

- [ ] **Step 2: Update model section to mention gpt-5-mini default**

Add to `CLAUDE.md` near the existing provider docs:

```
**OpenAI:** `--provider openai` defaults to `gpt-5-mini`. Override with
`--model <id>` (e.g. `--model gpt-4o-mini`). Requires `OPENAI_API_KEY`
in `.env`.
```

- [ ] **Step 3: Update pipeline.md if it covers these flows**

```bash
grep -n 'provider\|claude\|ollama\|qwen3' docs/pipeline.md | head
```

For each match describing the LLM flows, add `openai` as a peer and reference batch mode where relevant.

- [ ] **Step 4: Verify import-path docs are clean**

```bash
grep -n 'spiritolo_common\|scraper\.src\.' CLAUDE.md docs/pipeline.md docs/backups.md docs/upload.md docs/spirits-taxonomy.md docs/deployment.md 2>/dev/null
```

Expected: empty (Task 3 already swept these; this is the safety net).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/
git commit -m "Docs: document --provider openai + --batch across flows

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Final verification

### Task 20: Full test sweep + lint

- [ ] **Step 1: Run the entire test suite**

```bash
cd /workspaces/spiritolo && uv run pytest common/tests scraper/tests ingredients/tests scripts/tests -v
```

Expected: same pass/skip counts as `main` plus the new tests added in Tasks 7, 9, 11, 12, 13, 14, 15, 16, 18.

- [ ] **Step 2: Verify CLI help across all four flows**

```bash
uv run python -m ingredients.cli map resolve-pending --help
uv run python -m ingredients.cli normalize-names resolve-pending --help
uv run python -m scraper.classify --help
```

Expected: each shows `--provider`, `--model`, `--batch`, `--ingest`, `--wait`, `--poll-interval` (and pre-existing flags).

- [ ] **Step 3: Verify no leftover stale-path references**

```bash
grep -rn 'spiritolo_common\|scraper\.src\.' --include='*.py' --include='*.toml' --include='*.md' . \
  | grep -v '.venv/' | grep -v 'egg-info' | grep -v 'docs/superpowers/'
```

Expected: empty (the only allowed matches are inside `docs/superpowers/specs/` and `docs/superpowers/plans/` historical docs, which are immutable).

- [ ] **Step 4: Push the branch**

```bash
git push -u origin "$(git branch --show-current)"
```

- [ ] **Step 5: Open PR**

```bash
gh pr create --title "Add OpenAI sync + Batch API providers across LLM flows; clean up workspace layout" --body "$(cat <<'EOF'
- Adds `--provider openai` (sync, default gpt-5-mini) to all three prompt-driven flows: ingredients map resolve-pending, ingredients normalize-names resolve-pending, scraper classify.
- Adds `--batch` mode (OpenAI Batch API: 50% off real-time, ~24h SLA) on the same three flows. Hybrid lifecycle: `--submit` exits immediately, `--ingest BATCH_ID` drains results later, `--wait` polls inline.
- Hoists the existing `LLMProvider` Protocol + Claude + Ollama providers + retry helper from `ingredients.mapping` to a shared `common.llm` subpackage so all three flows can share it.
- Folds in a workspace cleanup: renames `spiritolo_common` Python package to `common` (workspace dir was already `common/`), and wraps `scraper/src/*.py` in a `scraper/` package (drops the `package-dir = { "scraper.src" = "src" }` hack so imports become `from scraper.X import Y`).

Spec: docs/superpowers/specs/2026-05-05-llm-providers-batch-design.md
Plan: docs/superpowers/plans/2026-05-05-llm-providers-batch.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes (for the writer of this plan)

Coverage check vs spec:

- ✅ Module layout (Task 4–14)
- ✅ Sync Protocol kept as-is, hoisted (Task 4)
- ✅ Batch Protocol new (Task 11)
- ✅ Sidecar JSON + gitignore (Task 12)
- ✅ OpenAIProvider sync (Task 9)
- ✅ OpenAIBatchProvider (Task 13)
- ✅ Flow-agnostic batch_runner (Task 14)
- ✅ Mapping resolve-pending wiring (Task 15)
- ✅ Dedup normalize-names wiring (Task 16)
- ✅ Classify refactor + provider Protocol (Task 17)
- ✅ Classify batch wiring (Task 18)
- ✅ Workspace cleanup folded in (Tasks 1–3)
- ✅ Docs (Task 19)
- ✅ Failure modes — covered via SidecarMismatch, status check in ingest, error-counter in on_result
- ✅ Tests — Tasks 5, 6, 7, 9, 11, 12, 13, 14, 15, 16, 17 (test_ollama_client/test_classify updates), 18

Per-spec confirmation:
- `--review` refuses `--batch`: NOT explicitly enforced in CLI handlers. Worth adding a guard in the dispatch. → Add a one-liner in each affected handler: `if args.review and args.batch: error and exit 2`.

That refinement applies to Task 15 step 6, Task 16 step 6, and Task 17 step 4 (review flag is in classify already). Add the guard there.

Type/name consistency:
- `BatchRequest`, `BatchSubmission`, `BatchStatus`, `BatchResult`, `BatchSubmitOutcome` — used consistently across runner, providers, sidecar, tests.
- `submit_phase2_batch` / `ingest_phase2_batch` (mapping) vs `submit_normalize_names_batch` / `ingest_normalize_names_batch` (dedup) vs `submit_classify_batch` / `ingest_classify_batch` (scraper) — naming aligned by flow.
- `flow` string constants: `mapping.resolve_pending`, `dedup.normalize_names.resolve_pending`, `scraper.classify.url` — used identically in test assertions and impls.
- `version_constant` mapping: mapping → `MAPPER_VERSION`, dedup → `NORMALIZER_VERSION`, classify → `PROMPT_VERSION`. Used consistently.

No placeholders. No "TBD". Each step has either exact code or exact commands.
