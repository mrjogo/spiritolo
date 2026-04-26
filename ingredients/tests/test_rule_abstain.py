"""Negative-case guard: strings the parser MUST NOT 'best-effort' parse.

Each entry here is something we observed in the corpus where any partial
parse would be wrong. Adding a new entry here is the way you record an
over-match bug: write the failing test, then tighten the rule that fired.
"""

import pytest

from ingredients.parser import parse


ABSTAIN_CASES = [
    # foodandwine concatenated bug — multiple ingredients glued together.
    "0.5 oz Santoni Amaro3 oz Lambrusco Del Emilia Rosé1 oz club soda",
    # Reverse format (name first, qty after) — too ambiguous for v1.
    "D'Usse VSOP: 30 ml",
    "Peychaud Bitters: 2 dashes",
    # Multiple parenthesized equivalent volumes — which to use?
    "1 (375ml) bottle (1 1/2 cups) rye whiskey or blended scotch",
    "3/4 ounce (1 1/2 tablespoons) St-Germain elderflower liqueur",
    # Footnote artifact — liquor.com convention.
    "Coconut ice sphere*",
    # Bare bottle/can phrasing — "1 12-oz. can ginger beer" has structure
    # we're not going to attempt in v1.
    "1 12-oz. can ginger beer",
    # No quantity, no recognized prefix.
    "Ice",
    "Float Whipping cream",
    "Hard apple cider, to top",
    "Salt, to rim (optional)",
    "Lemon wedge, for rimming",
    # Quantity but unrecognized unit and no count noun.
    "1 squeeze fresh lime juice",
    "Few tablespoons honey (optional)",  # 'few' isn't numeric
    "Large pinch salt",
    "Dash of Angostura bitters",  # leading word 'Dash' but no qty before it
    # Empty / whitespace.
    "",
    "   ",
]


@pytest.mark.parametrize("s", ABSTAIN_CASES)
def test_must_abstain(s):
    r = parse(s)
    assert r.parse_status == "unparseable", (
        f"expected unparseable for {s!r}, "
        f"got rule={r.parser_rule} amount={r.amount} unit={r.unit} name={r.name!r}"
    )
