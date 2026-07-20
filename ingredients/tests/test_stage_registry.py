"""Importing the stages package registers each stage_fn into STAGE_FNS."""

from __future__ import annotations


def test_stages_register_into_dispatch():
    import ingredients.pipeline.stages  # noqa: F401 -- import triggers registration
    from ingredients.worker.dispatch import STAGE_FNS

    for stage in ("parse-ingredients", "export-recipegf"):
        assert stage in STAGE_FNS
        assert callable(STAGE_FNS[stage])
