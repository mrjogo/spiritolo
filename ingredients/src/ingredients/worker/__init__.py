"""Pipeline run runtime: the stage registry, the provider chain and the cost
meter.

The always-on polling worker is gone — runs execute in-process inside the app
(see ``spiritolo.executor``), which claims a ``queued`` job, builds its
``ProviderChain`` from the job's ``llm_provider`` / ``llm_model``, dispatches to
the registered ``stage_fn``, and finalizes the job. This package owns the seams
that executor composes; the pipeline stages register their ``stage_fn`` bodies
into ``dispatch.STAGE_FNS``. Everything here is exercised with fake providers /
fake stage_fns — never a live model.
"""

from __future__ import annotations

from ingredients.worker.cost import CostCapExceeded, CostMeter
from ingredients.worker.dispatch import STAGE_FNS, UnknownStage, register, run
from ingredients.worker.providers import ProviderChain

__all__ = [
    "CostCapExceeded",
    "CostMeter",
    "ProviderChain",
    "STAGE_FNS",
    "UnknownStage",
    "register",
    "run",
]
