"""Technique inference + instruction flattening. Pure-Python (no DB)."""

from __future__ import annotations

import pytest

from ingredients.recipegf.technique import (
    Technique,
    flatten_instructions,
    infer_technique,
    mentions_muddle,
)


def _jsonld(instr):
    return {"recipeInstructions": instr}


@pytest.mark.parametrize(
    "instr, expected",
    [
        ("Stir with ice and strain.", Technique.STIR),
        ("Shake hard with ice, then strain.", Technique.SHAKE),
        ("Blend until smooth.", Technique.BLEND),
        ("Build over ice and top with soda.", Technique.BUILD),
        ("Pour over ice in a rocks glass.", Technique.BUILD),
        ("A lovely drink.", None),
    ],
)
def test_infer_technique(instr, expected):
    assert infer_technique(_jsonld(instr)) is expected


def test_blend_outranks_stir_and_shake():
    # A blended drink whose text also says "stir" resolves to BLEND (priority).
    assert infer_technique(_jsonld("Add and stir, then blend until smooth")) is Technique.BLEND


def test_shake_outranks_build():
    assert infer_technique(_jsonld("Build the base, then shake with ice")) is Technique.SHAKE


def test_flatten_string():
    assert flatten_instructions(_jsonld("Stir It")) == "stir it"


def test_flatten_list_of_strings():
    assert flatten_instructions(_jsonld(["Add gin.", "Stir well."])) == "add gin. stir well."


def test_flatten_howto_steps():
    doc = _jsonld([
        {"@type": "HowToStep", "text": "Add the gin."},
        {"@type": "HowToStep", "text": "Stir until chilled."},
    ])
    assert "stir until chilled" in flatten_instructions(doc)


def test_flatten_howto_section_recurses():
    doc = _jsonld([
        {"@type": "HowToSection", "itemListElement": [
            {"@type": "HowToStep", "text": "Shake with ice."},
        ]},
    ])
    assert infer_technique(doc) is Technique.SHAKE


def test_flatten_handles_missing_and_none():
    assert flatten_instructions(None) == ""
    assert flatten_instructions({}) == ""
    assert flatten_instructions({"recipeInstructions": None}) == ""


def test_mentions_muddle():
    assert mentions_muddle("muddle the mint")
    assert mentions_muddle("gently muddled with sugar")
    assert not mentions_muddle("stir and strain")
