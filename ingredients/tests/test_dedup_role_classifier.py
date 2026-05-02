import pytest

from ingredients.dedup.role_classifier import classify_role


def make_ing(*, default_role=None, slug="x", amount=None, unit=None, position=1, raw_text=""):
    """Test helper — builds the dict shape classify_role consumes."""
    return {
        "taxonomy_node_slug": slug,
        "default_role": default_role,
        "amount": amount,
        "unit": unit,
        "position": position,
        "raw_text": raw_text,
    }


@pytest.mark.parametrize("default_role", [
    "base_spirit", "modifier", "citrus", "sweetener",
    "bitters", "dilution", "ice", "garnish",
])
def test_taxonomy_default_used_when_present(default_role):
    role, source = classify_role(make_ing(default_role=default_role))
    assert role == default_role
    assert source == "default"


def test_bitters_with_large_amount_promotes_to_base_spirit():
    # Trinidad Sour: 1.5oz Angostura as the base
    role, source = classify_role(
        make_ing(default_role="bitters", amount=1.5, unit="oz", position=1),
    )
    assert role == "base_spirit"
    assert source == "rule"


def test_bitters_with_dash_amount_stays_bitters():
    role, source = classify_role(
        make_ing(default_role="bitters", amount=2.0, unit="dash", position=4),
    )
    assert role == "bitters"
    assert source == "default"


def test_modifier_with_position_one_and_large_amount_promotes_to_base():
    # Reverse Manhattan: 1.5oz sweet vermouth as the base
    role, source = classify_role(
        make_ing(default_role="modifier", amount=1.5, unit="oz", position=1),
    )
    assert role == "base_spirit"
    assert source == "rule"


def test_modifier_in_modifier_position_stays_modifier():
    role, source = classify_role(
        make_ing(default_role="modifier", amount=1.0, unit="oz", position=2),
    )
    assert role == "modifier"
    assert source == "default"


def test_wash_hint_in_raw_text_with_tiny_amount():
    role, source = classify_role(
        make_ing(default_role=None, slug="absinthe", amount=0.0625, unit="oz",
                 raw_text="absinthe rinse", position=1),
    )
    assert role == "wash"
    assert source == "rule"


def test_unknown_substance_position_one_with_base_amount_defaults_to_base_spirit():
    role, source = classify_role(
        make_ing(default_role=None, amount=2.0, unit="oz", position=1),
    )
    assert role == "base_spirit"
    assert source == "rule"


def test_unknown_substance_no_amount_falls_back_to_other():
    role, source = classify_role(
        make_ing(default_role=None, amount=None, unit=None, position=3),
    )
    assert role == "other"
    assert source == "default"
