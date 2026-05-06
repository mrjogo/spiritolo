"""Sidecar JSON files persist batch submissions so --ingest can fan results
back to the right writers.

Path: data/batches/<batch_id>.json (configurable per-call).
On successful ingest, file is renamed <batch_id>.json.ingested so re-runs
noisily skip; remove the suffix to force re-ingest.
On terminal failure (state in failed/expired/cancelled), file is renamed
<batch_id>.json.<state> so the operator can see at a glance which batches
are live and which are dead. To retry against a re-submitted batch, the
operator just removes the suffix.
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


# Terminal suffixes a sidecar may carry. `.ingested` = success.
# `.failed` / `.expired` / `.cancelled` = batch ended in that state on the
# provider side; no results to ingest.
_TERMINAL_SUFFIXES = ("ingested", "failed", "expired", "cancelled")


def load_sidecar(
    batch_id: str, *, batches_dir: Path,
    expected_flow: str | None = None,
    expected_version: str | None = None,
) -> Sidecar:
    """Load sidecar by batch_id. Optionally enforce flow + version match."""
    path = batches_dir / f"{batch_id}.json"
    if not path.exists():
        for suffix in _TERMINAL_SUFFIXES:
            terminal = batches_dir / f"{batch_id}.json.{suffix}"
            if terminal.exists():
                if suffix == "ingested":
                    raise SidecarMismatch(
                        f"sidecar for {batch_id} already ingested "
                        f"(at {terminal}). Remove the .ingested suffix to "
                        "force re-ingest."
                    )
                raise SidecarMismatch(
                    f"sidecar for {batch_id} previously marked {suffix!r} "
                    f"(batch ended in that state on the provider side; at "
                    f"{terminal}). Submit a new batch — there are no results "
                    "to ingest from this one."
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


def force_unmark_ingested(batch_id: str, *, batches_dir: Path) -> Path:
    """Rename <batch_id>.json.ingested → <batch_id>.json so the next
    load_sidecar call accepts it. No-op if the unsuffixed path is already
    present. Raises FileNotFoundError if neither exists.

    Used by `--ingest BATCH_ID --force`. Does NOT touch .failed/.expired/
    .cancelled sidecars — those batches have no results on the provider
    side, re-ingesting them would just re-mark them.
    """
    unsuffixed = batches_dir / f"{batch_id}.json"
    ingested = batches_dir / f"{batch_id}.json.ingested"
    if unsuffixed.exists():
        return unsuffixed
    if ingested.exists():
        ingested.rename(unsuffixed)
        return unsuffixed
    raise FileNotFoundError(
        f"no sidecar at {unsuffixed} or {ingested}"
    )


def mark_failed(sidecar_path: Path, *, state: str = "failed") -> Path:
    """Rename <batch_id>.json → <batch_id>.json.<state> for a batch that
    ended in a non-recoverable state on the provider (failed/expired/cancelled).
    Returns the new path."""
    if state not in ("failed", "expired", "cancelled"):
        raise ValueError(f"unknown terminal state {state!r}")
    new_path = sidecar_path.with_suffix(sidecar_path.suffix + f".{state}")
    sidecar_path.rename(new_path)
    return new_path
