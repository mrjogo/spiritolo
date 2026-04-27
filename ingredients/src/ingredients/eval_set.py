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
    # v3: extended qualifier list and new count-noun heads.
    EvalCase("2 small basil leaves", "thekitchn",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=2.0, expect_unit="leaf", expect_name="basil"),
    EvalCase("4 maraschino cherries", "punch",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=4.0, expect_unit="cherry", expect_name="maraschino"),
    EvalCase("1 vanilla bean", "seriouseats",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=1.0, expect_unit="bean", expect_name="vanilla"),
    EvalCase("2 cardamom pods", "thekitchn",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=2.0, expect_unit="pod", expect_name="cardamom"),
    EvalCase("2 garlic cloves", "punch",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=2.0, expect_unit="clove", expect_name="garlic"),
    EvalCase("2 ice cream scoops", "foodandwine",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=2.0, expect_unit="scoop", expect_name="ice cream"),
    EvalCase("1 bar spoon Salers gentian liqueur", "punch",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="barspoon",
             expect_name="salers gentian liqueur"),
    # HTML entity decode in pre_clean (`&frasl;` is the fraction-slash entity).
    EvalCase("1&frasl;2 oz gin", "diffordsguide",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=0.5, expect_unit="oz", expect_name="gin"),
    # v3: head-position count noun (`<qty> <count_noun> <name>`).
    EvalCase("1.5 cloves garlic", "seriouseats",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=1.5, expect_unit="clove", expect_name="garlic"),
    EvalCase("3 scoop Vanilla ice cream", "diffordsguide",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=3.0, expect_unit="scoop",
             expect_name="vanilla ice cream"),
    EvalCase("1 orange half-wheel", "punch",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=1.0, expect_unit="orange", expect_name="half-wheel"),
    # v3: qty + known noun (no separate unit). COUNT_NOUN_ALIASES = single
    # source of truth. Qualifier strip applies (`1 large lemon` → name=lemon).
    EvalCase("1 lemon", "thekitchn",
             expect_status="parsed", expect_rule="qty_known_noun",
             expect_amount=1.0, expect_unit=None, expect_name="lemon"),
    EvalCase("2 limes", "thekitchn",
             expect_status="parsed", expect_rule="qty_known_noun",
             expect_amount=2.0, expect_unit=None, expect_name="lime"),
    EvalCase("1 banana", "punch",
             expect_status="parsed", expect_rule="qty_known_noun",
             expect_amount=1.0, expect_unit=None, expect_name="banana"),
    EvalCase("1 large lemon", "foodandwine",
             expect_status="parsed", expect_rule="qty_known_noun",
             expect_amount=1.0, expect_unit=None, expect_name="lemon"),
    EvalCase("2 ripe peaches", "seriouseats",
             expect_status="parsed", expect_rule="qty_known_noun",
             expect_amount=2.0, expect_unit=None, expect_name="peach"),
    EvalCase("4 whole star anise", "diffordsguide",
             expect_status="parsed", expect_rule="qty_known_noun",
             expect_amount=4.0, expect_unit=None, expect_name="star anise"),
    # v3: qty + annotated phrase preserves the full annotation in name.
    EvalCase("1 lime, juiced", "punch",
             expect_status="parsed", expect_rule="qty_annotated_name",
             expect_amount=1.0, expect_unit=None, expect_name="lime, juiced"),
    EvalCase("1 lemon, thinly sliced", "foodandwine",
             expect_status="parsed", expect_rule="qty_annotated_name",
             expect_amount=1.0, expect_unit=None,
             expect_name="lemon, thinly sliced"),
    EvalCase("1 (12-ounce) can club soda or seltzer water, chilled",
             "marthastewart",
             expect_status="parsed", expect_rule="qty_annotated_name",
             expect_amount=1.0, expect_unit=None,
             expect_name="(12-ounce) can club soda or seltzer water, chilled"),
    EvalCase("1 750-ml bottle Chilean Pisco", "foodnetwork",
             expect_status="parsed", expect_rule="qty_annotated_name",
             expect_amount=1.0, expect_unit=None,
             expect_name="750-ml bottle chilean pisco"),
    # v3: 'squeeze' is a real (if rare) bartending unit (14 corpus rows).
    EvalCase("1 squeeze fresh lime juice", "liquor",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="squeeze",
             expect_name="fresh lime juice"),
    # v4: qty_unit's concat guard now ignores parenthesized text — recipe
    # ratios inside parens (`(3 parts sugar to 4 parts ginger juice)`) used
    # to false-trip the digit+unit pattern.
    EvalCase("3/4 ounce rich ginger syrup (3 parts sugar to 4 parts ginger juice)",
             "punch",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=0.75, expect_unit="oz",
             expect_name="rich ginger syrup (3 parts sugar to 4 parts ginger juice)"),
    EvalCase("8 ounces crushed ice (about 1 cup)", "seriouseats",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=8.0, expect_unit="oz",
             expect_name="crushed ice (about 1 cup)"),
    EvalCase("3/4 ounce (1 1/2 tablespoons) St-Germain elderflower liqueur",
             "foodandwine",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=0.75, expect_unit="oz",
             expect_name="(1 1/2 tablespoons) st-germain elderflower liqueur"),
    # v5: hyphen-attached qty+unit normalized in pre_clean.
    EvalCase("1/2-ounce dry vermouth", "thekitchn",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=0.5, expect_unit="oz", expect_name="dry vermouth"),
    EvalCase("1-ounce vodka", "punch",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="oz", expect_name="vodka"),
    # v5: `or` range separator.
    EvalCase("3 or 4 dashes hot sauce", "foodandwine",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=3.0, expect_amount_max=4.0,
             expect_unit="dash", expect_name="hot sauce"),
    # v5: heaping/scant/mounded qualifier between qty and unit.
    EvalCase("1 heaping tablespoon instant coffee granules", "seriouseats",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="tbsp",
             expect_name="instant coffee granules"),
    EvalCase("1 mounded teaspoon sweet barbecue sauce", "foodnetwork",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="tsp",
             expect_name="sweet barbecue sauce"),
    # v5: vocab additions — berries, jalapeño, units bag/gallon/swath/grind.
    EvalCase("4 fresh raspberries", "foodandwine",
             expect_status="parsed", expect_rule="qty_known_noun",
             expect_amount=4.0, expect_unit=None, expect_name="raspberry"),
    EvalCase("12 small jalapeños", "seriouseats",
             expect_status="parsed", expect_rule="qty_known_noun",
             expect_amount=12.0, expect_unit=None, expect_name="jalapeño"),
    EvalCase("3 bags green tea", "thekitchn",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=3.0, expect_unit="bag", expect_name="green tea"),
    EvalCase("1 gallon apple cider", "foodandwine",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="gallon", expect_name="apple cider"),
    EvalCase("2 grind black pepper", "diffordsguide",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=2.0, expect_unit="grind", expect_name="black pepper"),
    EvalCase("1 swath Lemon peel", "diffordsguide",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="swath", expect_name="lemon peel"),
    EvalCase("12 strips crisp cooked bacon", "foodnetwork",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=12.0, expect_unit="strip",
             expect_name="crisp cooked bacon"),
    # v5: rule A — no_qty_known_noun preserves cleaned phrase as name.
    EvalCase("Ice", "thekitchn",
             expect_status="parsed", expect_rule="no_qty_known_noun",
             expect_amount=None, expect_unit=None, expect_name="ice"),
    EvalCase("Crushed ice", "punch",
             expect_status="parsed", expect_rule="no_qty_known_noun",
             expect_amount=None, expect_unit=None, expect_name="crushed ice"),
    EvalCase("Lemon wheels, for garnish", "foodandwine",
             expect_status="parsed", expect_rule="no_qty_known_noun",
             expect_amount=None, expect_unit=None,
             expect_name="lemon wheels, for garnish"),
    EvalCase("Soda water", "punch",
             expect_status="parsed", expect_rule="no_qty_known_noun",
             expect_amount=None, expect_unit=None, expect_name="soda water"),
    EvalCase("Fresh mint sprigs, for garnish", "thekitchn",
             expect_status="parsed", expect_rule="no_qty_known_noun",
             expect_amount=None, expect_unit=None,
             expect_name="fresh mint sprigs, for garnish"),
    # v5: rule C — lexical-qty heads (`Pinch X`, `Splash X`, `Dash X`).
    EvalCase("Pinch ground cinnamon", "punch",
             expect_status="parsed", expect_rule="lexical_qty",
             expect_amount=None, expect_unit="pinch",
             expect_name="ground cinnamon"),
    EvalCase("Pinch of salt", "marthastewart",
             expect_status="parsed", expect_rule="lexical_qty",
             expect_amount=None, expect_unit="pinch", expect_name="salt"),
    EvalCase("Splash lemon-lime soda", "diffordsguide",
             expect_status="parsed", expect_rule="lexical_qty",
             expect_amount=None, expect_unit="splash",
             expect_name="lemon-lime soda"),
    EvalCase("Dash pure vanilla extract", "seriouseats",
             expect_status="parsed", expect_rule="lexical_qty",
             expect_amount=None, expect_unit="dash",
             expect_name="pure vanilla extract"),
]

# Should-abstain cases (kept in sync with test_rule_abstain.py).
_ABSTAIN_CASES: list[EvalCase] = [
    EvalCase("0.5 oz Santoni Amaro3 oz Lambrusco Del Emilia Rosé1 oz club soda",
             "foodandwine", expect_status="unparseable"),
    EvalCase("D'Usse VSOP: 30 ml", "foodandwine", expect_status="unparseable"),
    # v5: most no-qty rows that anchor on a known noun (Ice, Coconut ice
    # sphere*, etc.) are picked up by the no_qty_known_noun rule and moved
    # to the parse cases above. The remaining abstains here are rows with
    # neither a leading qty nor a recognized noun anchor.
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
