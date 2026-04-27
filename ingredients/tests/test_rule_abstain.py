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
    # Quantity but unrecognized unit and no recognized noun anchor.
    "Few tablespoons honey (optional)",  # 'few' isn't numeric
    # Empty / whitespace.
    "",
    "   ",
    # v5 note: rows like `Ice`, `Float Whipping cream`, `Salt, to rim`,
    # `Lemon wedge, for rimming`, `Coconut ice sphere*`, and
    # `Dash of Angostura bitters` parse via the new no_qty_known_noun /
    # lexical_qty rules. They moved to the parse cases.
]


@pytest.mark.parametrize("s", ABSTAIN_CASES)
def test_must_abstain(s):
    r = parse(s)
    assert r.parse_status == "unparseable", (
        f"expected unparseable for {s!r}, "
        f"got rule={r.parser_rule} amount={r.amount} unit={r.unit} name={r.name!r}"
    )
