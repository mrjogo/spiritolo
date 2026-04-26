"""Checked-in golden cases used by the `--review` CLI. Bumping
PARSER_VERSION should be paired with re-running --review until it passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ingredients.parser import parse


@dataclass
class EvalCase:
    raw: str
    site: str | None
    expect_status: str  # 'parsed' | 'unparseable'
    expect_rule: str | None = None
    expect_amount: float | None = None
    expect_amount_max: float | None = None
    expect_unit: str | None = None
    expect_name: str | None = None


# Should-parse-as-X cases.
_PARSE_CASES: list[EvalCase] = [
    EvalCase("2 oz gin", "punch",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=2.0, expect_unit="oz", expect_name="gin"),
    EvalCase("1 1/2 oz Tanqueray gin", "tastingtable",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.5, expect_unit="oz", expect_name="tanqueray gin"),
    EvalCase("0.25 cup honey", "marthastewart",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=0.25, expect_unit="cup", expect_name="honey"),
    EvalCase("3/4 ounce rum, such as Coruba", "punch",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=0.75, expect_unit="oz",
             expect_name="rum, such as coruba"),
    EvalCase("¾ ounce campari", "punch",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=0.75, expect_unit="oz", expect_name="campari"),
    EvalCase("45 ml Light gold rum 1-3yo", "diffordsguide",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=45.0, expect_unit="ml",
             expect_name="light gold rum 1-3yo"),
    EvalCase("1 dash Aromatic bitters", "diffordsguide",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="dash",
             expect_name="aromatic bitters"),
    EvalCase("3 drops Xocolatl mole bitters", "diffordsguide",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=3.0, expect_unit="drop",
             expect_name="xocolatl mole bitters"),
    EvalCase("1/2 to 3/4 oz simple syrup", None,
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=0.5, expect_amount_max=0.75,
             expect_unit="oz", expect_name="simple syrup"),
    EvalCase("Garnish: lemon wheel", "liquor",
             expect_status="parsed", expect_rule="garnish_prefix",
             expect_name="lemon wheel"),
    EvalCase("Garnish: orange twist", "liquor",
             expect_status="parsed", expect_rule="garnish_prefix",
             expect_name="orange twist"),
    EvalCase("Top up with Brut sparkling wine", "diffordsguide",
             expect_status="parsed", expect_rule="topup",
             expect_name="brut sparkling wine"),
    EvalCase("Top up with Soda (club soda) water", "diffordsguide",
             expect_status="parsed", expect_rule="topup",
             expect_name="soda (club soda) water"),
    EvalCase("3 fresh basil leaves", "liquor",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=3.0, expect_unit="leaf", expect_name="basil"),
    EvalCase("4 sugar cubes", "liquor",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=4.0, expect_unit="cube", expect_name="sugar"),
    EvalCase("1 fresh rosemary sprig", "thekitchn",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=1.0, expect_unit="sprig", expect_name="rosemary"),
    # v2: extended unit vocab.
    EvalCase("1 shot Counter Culture espresso", "punch",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="shot",
             expect_name="counter culture espresso"),
    EvalCase("1 pint Pilsner lager", "punch",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="pint", expect_name="pilsner lager"),
    EvalCase("1 quart tomato juice", "foodandwine",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="quart", expect_name="tomato juice"),
    EvalCase("1 pound granulated sugar", "seriouseats",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="lb", expect_name="granulated sugar"),
    EvalCase("5 grams citric acid powder", "seriouseats",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=5.0, expect_unit="g", expect_name="citric acid powder"),
    EvalCase("750 milliliters Smith & Cross rum", "punch",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=750.0, expect_unit="ml",
             expect_name="smith & cross rum"),
    EvalCase("1 bottle Prosecco or Cava, chilled", "foodandwine",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="bottle",
             expect_name="prosecco or cava, chilled"),
    EvalCase("2 bottles chilled Pinot Grigio", "foodnetwork",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=2.0, expect_unit="bottle",
             expect_name="chilled pinot grigio"),
    EvalCase("1 bunch fresh sage", "thekitchn",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="bunch", expect_name="fresh sage"),
]

# Should-abstain cases (kept in sync with test_rule_abstain.py).
_ABSTAIN_CASES: list[EvalCase] = [
    EvalCase("0.5 oz Santoni Amaro3 oz Lambrusco Del Emilia Rosé1 oz club soda",
             "foodandwine", expect_status="unparseable"),
    EvalCase("D'Usse VSOP: 30 ml", "foodandwine", expect_status="unparseable"),
    EvalCase("1 (375ml) bottle (1 1/2 cups) rye whiskey or blended scotch",
             "simplyrecipes", expect_status="unparseable"),
    EvalCase("Coconut ice sphere*", "liquor", expect_status="unparseable"),
    EvalCase("Ice", "thekitchn", expect_status="unparseable"),
    EvalCase("1 squeeze fresh lime juice", "liquor", expect_status="unparseable"),
    EvalCase("Few tablespoons honey (optional)", "marthastewart", expect_status="unparseable"),
]

EVAL_CASES: list[EvalCase] = _PARSE_CASES + _ABSTAIN_CASES


def run_eval() -> dict[str, Any]:
    """Run every eval case and return a pass/fail summary plus per-case detail."""
    cases = []
    passed = 0
    failed = 0
    for case in EVAL_CASES:
        result = parse(case.raw, site=case.site)
        ok = (
            result.parse_status == case.expect_status
            and (case.expect_rule is None or result.parser_rule == case.expect_rule)
            and (case.expect_amount is None or result.amount == case.expect_amount)
            and (case.expect_amount_max is None or result.amount_max == case.expect_amount_max)
            and (case.expect_unit is None or result.unit == case.expect_unit)
            and (case.expect_name is None or result.name == case.expect_name)
        )
        cases.append({"raw": case.raw, "ok": ok, "result": result})
        if ok:
            passed += 1
        else:
            failed += 1
    return {"passed": passed, "failed": failed, "cases": cases}
