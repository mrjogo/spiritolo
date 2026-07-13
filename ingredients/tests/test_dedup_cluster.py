"""Pure cluster/variant key functions — now keyed on taxonomy slugs."""

from ingredients.dedup.cluster import (
    INCLUDED_ROLES,
    compute_cluster_key,
    compute_variant_key,
    in_cluster_key,
    ingredient_set_json,
)


def _ing(role, antichain_slug="gin", taxonomy_slug="gin", amount=1.0,
         amount_max=None, unit="oz", is_defining_garnish=False):
    return {
        "role": role,
        "antichain_slug": antichain_slug,
        "taxonomy_slug": taxonomy_slug,
        "amount": amount,
        "amount_max": amount_max,
        "unit": unit,
        "is_defining_garnish": is_defining_garnish,
    }


def test_in_cluster_key_includes_default_roles():
    for role in INCLUDED_ROLES:
        assert in_cluster_key(_ing(role=role))


def test_in_cluster_key_excludes_ice():
    assert not in_cluster_key(_ing(role="ice"))


def test_in_cluster_key_garnish_uses_defining_flag():
    assert not in_cluster_key(_ing(role="garnish", is_defining_garnish=False))
    assert in_cluster_key(_ing(role="garnish", is_defining_garnish=True))


def test_in_cluster_key_unknown_role_excluded_by_default():
    assert not in_cluster_key(_ing(role="high_abv"))


def test_in_cluster_key_excludes_unresolved_ingredient():
    # No antichain slug (unresolved) -> excluded, so sorted() never sees None.
    assert not in_cluster_key(_ing(role="other", antichain_slug=None))
    assert not in_cluster_key(_ing(role="base_spirit", antichain_slug=None))


def test_compute_cluster_key_skips_unresolved_ingredients():
    resolved = _ing(role="base_spirit", antichain_slug="gin")
    unresolved = _ing(role="other", antichain_slug=None, taxonomy_slug=None)
    assert compute_cluster_key("negroni", [resolved, unresolved]) == \
        compute_cluster_key("negroni", [resolved])


def test_compute_cluster_key_independent_of_ingredient_ordering():
    a = [_ing(role="base_spirit", antichain_slug="gin"),
         _ing(role="modifier", antichain_slug="campari")]
    b = list(reversed(a))
    assert compute_cluster_key("negroni", a) == compute_cluster_key("negroni", b)


def test_compute_cluster_key_independent_of_amount():
    a = [_ing(role="base_spirit", antichain_slug="gin", amount=1.0)]
    b = [_ing(role="base_spirit", antichain_slug="gin", amount=2.0)]
    assert compute_cluster_key("negroni", a) == compute_cluster_key("negroni", b)


def test_compute_variant_key_distinguishes_amounts():
    a = [_ing(role="base_spirit", antichain_slug="gin", amount=1.0, unit="oz")]
    b = [_ing(role="base_spirit", antichain_slug="gin", amount=2.0, unit="oz")]
    ck = compute_cluster_key("negroni", a)
    assert compute_variant_key(ck, a) != compute_variant_key(ck, b)


def test_compute_variant_key_distinguishes_specific_slug():
    base = _ing(role="base_spirit", antichain_slug="gin", taxonomy_slug="gin")
    branded = {**base, "taxonomy_slug": "tanqueray"}
    ck = compute_cluster_key("negroni", [base])
    assert compute_variant_key(ck, [base]) != compute_variant_key(ck, [branded])


def test_compute_cluster_key_excludes_ice():
    no_ice = [_ing(role="base_spirit", antichain_slug="gin")]
    with_ice = no_ice + [_ing(role="ice", antichain_slug="ice")]
    assert compute_cluster_key("negroni", no_ice) == \
        compute_cluster_key("negroni", with_ice)


def test_compute_variant_key_handles_mixed_none_and_concrete_amounts():
    ingredients = [
        _ing(role="base_spirit", antichain_slug="gin", amount=2.0, unit="oz"),
        _ing(role="modifier", antichain_slug="campari", amount=None, amount_max=None, unit=None),
        _ing(role="citrus", antichain_slug="lemon", amount=0.75, unit="oz"),
    ]
    ck = compute_cluster_key("negroni", ingredients)
    vk = compute_variant_key(ck, ingredients)
    assert isinstance(vk, str) and len(vk) == 64
    assert compute_variant_key(ck, list(reversed(ingredients))) == vk


def test_ingredient_set_json_snapshots_included_members():
    ings = [
        _ing(role="base_spirit", antichain_slug="gin"),
        _ing(role="ice", antichain_slug="ice"),
    ]
    snapshot = ingredient_set_json(ings)
    assert snapshot == [{"role": "base_spirit", "antichain_slug": "gin"}]
