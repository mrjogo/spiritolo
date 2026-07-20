"""Provider-chain primitives.

The shared building blocks a smart stage's provider chain is assembled from:
request packing (N items per LLM call, id-keyed re-mapping, per-item parking),
the per-provider cost table + metered flag, and the ``ChainResult`` /
``TierResult`` result shapes. ``FakeProvider`` is the hermetic LLM seam for
tests. The chain wiring itself (which provider a run uses, in what order) is
driven by the run's ``jobs.llm_provider`` / ``jobs.llm_model`` and lives in the
worker (``ingredients.worker.providers.ProviderChain``), not here.
"""

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
from .results import ChainResult, TierResult

__all__ = [
    "ChainResult",
    "FakeProvider",
    "Item",
    "TierResult",
    "UNIT_COST_CENTS",
    "call_cost_cents",
    "chunk",
    "decode_request",
    "decode_response",
    "encode_request",
    "encode_response",
    "is_metered",
    "run_packed",
]
