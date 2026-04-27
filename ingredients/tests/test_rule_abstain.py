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
    # Reverse format (name first, qty after) — name doesn't anchor on a
    # known noun, no leading qty, no lexical qty word.
    "D'Usse VSOP: 30 ml",
    # Empty / whitespace.
    "",
    "   ",
    # v7 note: as the bare-ingredient vocab grew (bitters, honey, the
    # spirits family, juice, etc.), several previously-abstain rows now
    # parse via no_qty_known_noun. That's intentional — preserving the
    # full prep phrase as name is more useful than abstaining. Examples
    # that moved out of this list: `Peychaud Bitters: 2 dashes`,
    # `Few tablespoons honey (optional)`, `Ice`, `Coconut ice sphere*`.
]


@pytest.mark.parametrize("s", ABSTAIN_CASES)
def test_must_abstain(s):
    r = parse(s)
    assert r.parse_status == "unparseable", (
        f"expected unparseable for {s!r}, "
        f"got rule={r.parser_rule} amount={r.amount} unit={r.unit} name={r.name!r}"
    )
