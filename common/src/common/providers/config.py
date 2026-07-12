"""Config-not-code seam for the provider chain.

A stage's chain is an *ordered* list of provider ids plus a pack size, read from
external config (a YAML/JSON file or a config row) — never hardcoded and never a
DB schema. Reordering the config reorders the chain with no code change; that
property is the whole point of this module and is pinned by
test_chain_order_from_config.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StageChainConfig:
    """The chain wiring for one smart stage.

    provider_ids is ordered: the chain attempts tiers left-to-right and
    short-circuits when everything resolves. pack_size governs how many items
    an LLM tier bundles per call.
    """

    stage: str
    provider_ids: tuple[str, ...]
    pack_size: int = 1

    def __post_init__(self) -> None:
        if not self.provider_ids:
            raise ValueError(f"stage {self.stage!r} has no providers configured")
        if self.pack_size < 1:
            raise ValueError(f"stage {self.stage!r} pack_size must be >= 1")


def load_stage_config(stage: str, raw: dict[str, Any]) -> StageChainConfig:
    """Build one StageChainConfig from a parsed config mapping
    ({"providers": [...], "pack_size": k})."""
    return StageChainConfig(
        stage=stage,
        provider_ids=tuple(raw["providers"]),
        pack_size=int(raw.get("pack_size", 1)),
    )


def load_chain_configs(raw: dict[str, dict[str, Any]]) -> dict[str, StageChainConfig]:
    """Build the full {stage -> StageChainConfig} map from external config."""
    return {stage: load_stage_config(stage, spec) for stage, spec in raw.items()}


def load_chain_configs_json(text: str) -> dict[str, StageChainConfig]:
    """Parse chain configs straight from a JSON config-file body."""
    return load_chain_configs(json.loads(text))
