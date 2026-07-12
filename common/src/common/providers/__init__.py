"""B7 — config-not-code provider-chain library.

Each smart stage is a rewireable chain of provider tiers
(deterministic -> local -> hosted) read from external config. The chain packs
N items per LLM call, short-circuits when a tier resolves, re-maps outputs to
inputs by id, parks per-item failures for re-submission, and reports cumulative
cost + metered flags. `FakeProvider` is the hermetic LLM seam for tests.
"""

from .chain import ChainResult, DeterministicProvider, TierResult, run_chain
from .config import (
    StageChainConfig,
    load_chain_configs,
    load_chain_configs_json,
    load_stage_config,
)
from .cost import UNIT_COST_CENTS, call_cost_cents, is_metered
from .fake import FakeProvider
from .packing import (
    Item,
    chunk,
    decode_request,
    decode_response,
    encode_request,
    encode_response,
    run_packed,
)

__all__ = [
    "ChainResult",
    "DeterministicProvider",
    "FakeProvider",
    "Item",
    "StageChainConfig",
    "TierResult",
    "UNIT_COST_CENTS",
    "call_cost_cents",
    "chunk",
    "decode_request",
    "decode_response",
    "encode_request",
    "encode_response",
    "is_metered",
    "load_chain_configs",
    "load_chain_configs_json",
    "load_stage_config",
    "run_chain",
    "run_packed",
]
