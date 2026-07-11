"""Slug minting for the RecipeGF export stage. Pure-Python (no DB)."""

from __future__ import annotations

import pytest
from recipegf import is_valid_recipe_id

from ingredients.recipegf.slug import is_valid_slug, mint_slug, slugify


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Old Fashioned", "old-fashioned"),
        ("Piña Colada", "pina-colada"),
        ("Corpse Reviver #2", "corpse-reviver-2"),
        ("  Gin & Tonic  ", "gin-tonic"),
        ("Aviation", "aviation"),
        ("Naked and Famous", "naked-and-famous"),
        ("El Diablo", "el-diablo"),
    ],
)
def test_mint_slug_common_names(name, expected):
    assert mint_slug(name) == expected


@pytest.mark.parametrize("name", [None, "", "   ", "#!@$", "—"])
def test_mint_slug_unminable_returns_none(name):
    assert mint_slug(name) is None


def test_slugify_is_idempotent():
    for name in ["Old Fashioned", "Piña Colada", "Corpse Reviver #2"]:
        once = slugify(name)
        assert slugify(once) == once


def test_minted_slugs_are_valid_kebab():
    for name in ["Old Fashioned", "Piña Colada", "Corpse Reviver #2", "El Diablo"]:
        slug = mint_slug(name)
        assert slug is not None
        assert is_valid_slug(slug)


def test_minted_slug_forms_valid_recipe_id():
    # The whole point of the slug: it must slot into a valid reverse-DNS id.
    slug = mint_slug("Old Fashioned")
    assert is_valid_recipe_id(f"com.spiritolo/{slug}:v1")


def test_slug_grammar_agrees_with_recipegf_id_grammar():
    """Our slug validator must agree with RecipeGF's id grammar on the slug
    segment, so the two can't silently drift."""
    for slug in ["old-fashioned", "a", "a1", "gin-and-tonic", "corpse-reviver-2"]:
        assert is_valid_slug(slug)
        assert is_valid_recipe_id(f"com.spiritolo/{slug}:v1")
    for bad in ["Old-Fashioned", "old_fashioned", "-lead", "trail-", "a--b", ""]:
        assert not is_valid_slug(bad)
        assert not is_valid_recipe_id(f"com.spiritolo/{bad}:v1")
