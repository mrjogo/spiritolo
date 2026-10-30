"""Checked-in settings for the local models the ``local`` tier runs.

LM Studio's defaults (context length, sampling) are server-wide and can change
under us, so a model spiritolo uses gets a profile here: the load settings the
client applies through LM Studio's ``POST /api/v1/models/load``, and the
sampling it sends on every request. A model with no profile runs on the
server's defaults (and the client logs that).

What LM Studio (llmster 0.0.25, tested on barbot 2026-10-30) can and cannot
take over HTTP:

- ``/api/v1/models/load`` accepts ``context_length``, ``flash_attention``,
  ``parallel``, ``offload_kv_cache_to_gpu``, ``eval_batch_size``,
  ``physical_batch_size``, ``ttl_seconds`` (among others) and rejects unknown
  keys. KV-cache quantization and GPU layer count are not settable; they stay at
  LM Studio's defaults (F16 KV, full offload for a model that fits).
- ``/v1/chat/completions`` honours ``temperature``, ``top_p``, ``top_k``,
  ``min_p``, ``repeat_penalty``, ``frequency_penalty`` and ``seed``, and silently
  ignores ``presence_penalty`` and the HF name ``repetition_penalty``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LocalModelProfile:
    # Body for POST /api/v1/models/load (minus "model"); also what a loaded
    # instance's config must match.
    load: dict[str, Any] = field(default_factory=dict)
    # Sampling fields sent on every /v1/chat/completions request.
    sampling: dict[str, Any] = field(default_factory=dict)


# Keyed by the runtime's model id (LOCAL_LLM_MODEL / jobs.llm_model).
LOCAL_MODEL_PROFILES: dict[str, LocalModelProfile] = {
    # Qwen3.5 9B, Q8_0 GGUF from lmstudio-community. Sampling is the model
    # card's "Instruct (or non-thinking) mode for general tasks" set; thinking
    # itself is turned off per request (reasoning_effort, see providers_local).
    # presence_penalty is sent as the card recommends but LM Studio ignores it;
    # repeat_penalty 1.0 (off) matches the card's repetition_penalty and
    # overrides LM Studio's 1.1 default.
    "qwen3.5-9b": LocalModelProfile(
        load={
            # Prompt + a 10-item pack, or one page of extract text (~12K chars),
            # with room for the answer; the model's native max is 262144.
            "context_length": 16384,
            "flash_attention": True,
            "offload_kv_cache_to_gpu": True,
            "parallel": 4,
        },
        sampling={
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 20,
            "min_p": 0.0,
            "presence_penalty": 1.5,
            "repeat_penalty": 1.0,
        },
    ),
}


def profile_for(model_id: str) -> LocalModelProfile | None:
    return LOCAL_MODEL_PROFILES.get(model_id)
