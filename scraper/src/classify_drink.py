"""Scored drink/food classifier using weighted labeling functions.

Each rule is an independent voter returning a signed weight. The score is the
sum of votes; the decision rule is score >= 2 -> confirmed_drink,
<= -2 -> confirmed_food, else abstain (None) so the LLM classifier can handle
ambiguous cases downstream.

Motivation: the prior single-keyword classifier in validate.py had ~20%
false-negative rate on sites with misleading metadata (e.g. Imbibe Magazine
labels every cocktail recipeCategory "Dessert"). Combining many weak signals
is robust to individual rule misfires.

Reference: Ratner et al. 2016, "Data Programming: Creating Large Training Sets,
Quickly".
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from scraper.src.structured import extract_structured, iter_recipes

DEFAULT_EVAL_PATH = (
    Path(__file__).resolve().parent.parent / "eval" / "classify-drink.jsonl"
)


GLASSWARE_WORDS = {
    "coupe", "highball", "collins", "julep", "snifter",
    "flute", "tumbler", "rocks", "coupette", "nick",
}
"""Single-token glassware words. Multi-word phrases like 'martini glass',
'rocks glass', 'martini cup' are covered by the presence of the word 'glass'
or 'cup' adjacent to 'strain'."""

GLASS_CONTAINER_WORDS = {"glass", "glasses", "cup", "mug", "stein"}


COCKTAIL_FAMILY_WORDS = {
    "negroni", "martini", "daiquiri", "fizz", "sour", "julep", "toddy",
    "spritz", "sangria", "mule", "margarita", "cocktail", "punch",
    "highball", "collins", "rickey", "smash", "swizzle", "flip",
    "cobbler", "bellini", "mimosa", "paloma",
}


PROXIMITY_TOKENS = 8
"""Window size (in word tokens) for proximity rules. 8 was chosen to cover
phrases like 'Add ice and shake vigorously for 10-15 seconds' without reaching
across sentence boundaries in step-separated instructions."""


def _words(text: str) -> list[str]:
    """Lowercase token list using word boundaries — avoids 'sour' matching
    'sour cream'."""
    return re.findall(r"[a-z]+", text.lower())


def _instructions_text(recipe: dict) -> str:
    """Collect recipeInstructions into a single string, handling the four
    common shapes: str, list[str], list[HowToStep dict], list[HowToSection]."""
    raw = recipe.get("recipeInstructions")
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                steps = item.get("itemListElement")
                if isinstance(steps, list):
                    parts.append(_instructions_text({"recipeInstructions": steps}))
        return " ".join(parts)
    return ""


COOKED_NOUNS = {
    "cake", "cakes", "pie", "pies", "bread", "breads",
    "cookie", "cookies", "pasta", "noodle", "noodles",
    "soup", "soups", "stew", "stews", "sauce", "sauces",
    "roast", "risotto", "salad", "salads", "casserole", "casseroles",
    "pizza", "tart", "tarts", "brownie", "brownies", "muffin", "muffins",
    "biscuit", "biscuits", "loaf", "loaves", "quiche", "souffle",
    "curry", "curries", "chili", "lasagna", "ravioli", "linguine",
    "fettuccine", "spaghetti", "burger", "burgers", "sandwich", "sandwiches",
    "frittata", "omelette", "omelet", "taco", "tacos",
}
"""Nouns that unambiguously identify a dish when present in a recipe name.
Singular + plural coverage because the name-rule tokenizes at word boundaries."""


METADATA_DRINK_TERMS = {
    # Direct drink-category words. Narrower than the legacy DRINK_TERMS set in
    # validate.py — we only match terms that unambiguously denote a drink
    # category when they appear in recipeCategory/keywords/breadcrumb. Family
    # words like 'sour' and 'punch' are deliberately excluded from metadata
    # matching (they catch too much food); the name-rule handles those.
    "cocktail", "cocktails", "drink", "drinks",
    "beverage", "beverages", "mixed drink",
    "aperitif", "aperitivo", "digestif", "nightcap",
    "spritz", "highball", "lowball",
    "martini", "margarita", "daiquiri", "mojito", "negroni",
    "mule", "julep", "bellini", "mimosa", "paloma",
}


BARTENDER_INGREDIENTS = {
    "bitters", "vermouth", "amaro", "amari",
    "campari", "aperol", "chartreuse", "fernet",
    "absinthe", "maraschino", "benedictine",
    "curacao", "orgeat", "falernum",
}
"""Ingredients that are overwhelmingly cocktail-specific. Kept narrow on
purpose — 'simple syrup', 'lime juice', 'egg white' all appear in food
recipes too, so they stay off the list."""


LIQUID_UNIT_WORDS = {
    "oz", "ounce", "ounces",
    "ml", "milliliter", "milliliters",
    "cl", "centiliter", "centiliters",
    "dash", "dashes",
    "barspoon", "barspoons",
    "splash", "splashes",
    "drop", "drops",
}
"""Bartender units. 'cup' deliberately excluded (ambiguous — cocktails use
'julep cup' meaning the vessel, while food recipes measure in cups)."""

DRY_UNIT_WORDS = {
    "cup", "cups",
    "tablespoon", "tablespoons", "tbsp", "tbsps",
    "teaspoon", "teaspoons", "tsp", "tsps",
    "pound", "pounds", "lb", "lbs",
    "kilogram", "kilograms", "kg",
}


_ISO8601_DURATION = re.compile(
    r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$"
)


def _iso8601_minutes(raw) -> int | None:
    """Parse an ISO-8601 duration like 'PT30M' or 'PT1H15M' into total minutes.
    Returns None for missing or unparseable values."""
    if not isinstance(raw, str):
        return None
    m = _ISO8601_DURATION.match(raw.strip())
    if not m:
        return None
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    return hours * 60 + minutes + seconds // 60


_OVEN_VERB_PATTERNS = (
    re.compile(r"\bpreheat\b[^.]*\boven\b"),
    re.compile(r"\bbake\b[^.]*\bat\b\s*\d"),
    re.compile(r"\broast\b[^.]*\bat\b\s*\d"),
    re.compile(r"\bbake\s+at\s+\d"),
    re.compile(r"\broast\s+at\s+\d"),
    re.compile(r"\boven\s+to\s+\d"),  # "set the oven to 350"
)


def _oven_verb_in(text: str) -> bool:
    """Text must be lowercased. Matches 'preheat ... oven', 'bake at N',
    'roast at N', or similar — not bare 'bake'/'roast' which can appear in
    cocktail garnishes ('toasted') and isn't specific."""
    return any(p.search(text) for p in _OVEN_VERB_PATTERNS)


def _metadata_drink_hit(value) -> bool:
    """True if any METADATA_DRINK_TERM appears as a whole word in a
    recipeCategory / keywords / breadcrumb-name value (which may be a string
    or a list of strings)."""
    if value is None:
        return False
    if isinstance(value, list):
        return any(_metadata_drink_hit(v) for v in value)
    if not isinstance(value, str):
        return False
    tokens = set(_words(value))
    return bool(tokens & METADATA_DRINK_TERMS)


def _breadcrumb_names(recipe: dict) -> list[str]:
    mep = recipe.get("mainEntityOfPage")
    if not isinstance(mep, dict):
        return []
    bc = mep.get("breadcrumb")
    if not isinstance(bc, dict):
        return []
    items = bc.get("itemListElement", [])
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        inner = item.get("item")
        if isinstance(inner, dict):
            name = inner.get("name")
            if isinstance(name, str):
                names.append(name)
        elif isinstance(inner, str):
            names.append(inner)
    return names


def _bartender_hits(raw) -> list[str]:
    """Return distinct bartender-specific ingredient words present in the list,
    in the order they first appear. Each hit fires once (not per occurrence)
    so a recipe with three kinds of bitters doesn't get +3."""
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for line in raw:
        if not isinstance(line, str):
            continue
        for tok in _words(line):
            if tok in BARTENDER_INGREDIENTS and tok not in seen:
                seen.append(tok)
    return seen


def _count_ingredient_units(raw) -> dict[str, int]:
    counts = {"liquid": 0, "dry": 0}
    if not isinstance(raw, list):
        return counts
    for line in raw:
        if not isinstance(line, str):
            continue
        cls = _unit_class(line)
        if cls:
            counts[cls] += 1
    return counts


def _unit_class(line: str) -> str | None:
    """Return 'liquid', 'dry', or None for an ingredient line."""
    tokens = _words(line)
    for tok in tokens:
        if tok in LIQUID_UNIT_WORDS:
            return "liquid"
        if tok in DRY_UNIT_WORDS:
            return "dry"
    return None


_YIELD_DRINK_WORDS = {"cocktail", "cocktails", "drink", "drinks"}


def _yield_is_drink_like(raw) -> bool:
    """True if recipeYield looks like a small drink serving.

    Schema.org allows recipeYield as a string ('2 drinks'), integer (2), or
    list. We accept numeric yields of 1 or 2 as drink-sized and any yield
    containing 'cocktail'/'drink'."""
    if raw is None:
        return False
    if isinstance(raw, list):
        return any(_yield_is_drink_like(v) for v in raw)
    if isinstance(raw, (int, float)):
        return 0 < raw <= 2
    if isinstance(raw, str):
        lowered = raw.lower()
        if any(w in _words(lowered) for w in _YIELD_DRINK_WORDS):
            return True
        match = re.search(r"\d+", lowered)
        if match:
            val = int(match.group())
            # Only infer drink-like from a bare number — 'Serves 2' is
            # ambiguous and should NOT fire. Require the integer to be the
            # entire string (after stripping).
            if lowered.strip() == match.group() and val <= 2:
                return True
    return False


def _word_near(tokens: list[str], target: str, others: set[str], window: int) -> bool:
    """True if `target` appears within `window` tokens of any word in `others`."""
    positions_target = [i for i, t in enumerate(tokens) if t == target]
    positions_others = [i for i, t in enumerate(tokens) if t in others]
    for i in positions_target:
        for j in positions_others:
            if abs(i - j) <= window:
                return True
    return False


@dataclass
class ScoreResult:
    score: int = 0
    rules: list[tuple[str, int]] = field(default_factory=list)

    def add(self, name: str, weight: int) -> None:
        self.rules.append((name, weight))
        self.score += weight


def score_recipe(recipe: dict) -> ScoreResult:
    """Score a Recipe dict. Returns total score and per-rule attribution."""
    result = ScoreResult()

    name = recipe.get("name") or ""
    if isinstance(name, list):
        name = " ".join(str(n) for n in name)
    name_words = set(_words(name))
    has_cooked_noun = bool(name_words & COOKED_NOUNS)
    if has_cooked_noun:
        result.add("name_cooked_noun", -4)
    elif name_words & COCKTAIL_FAMILY_WORDS:
        # Only fire the cocktail-family bump when no cooked noun is present in
        # the name. 'Cocktail Sauce' / 'Margarita Cake' are dishes; counting
        # both rules cancels the food signal and pushes the page to abstain.
        result.add("name_cocktail_family", 3)

    instr_tokens = _words(_instructions_text(recipe))
    if _word_near(instr_tokens, "shake", {"ice"}, PROXIMITY_TOKENS):
        result.add("instructions_shake_ice", 3)

    if _word_near(
        instr_tokens, "strain", GLASSWARE_WORDS | GLASS_CONTAINER_WORDS, PROXIMITY_TOKENS
    ):
        result.add("instructions_strain_glassware", 4)

    instr_text = _instructions_text(recipe).lower()
    if _oven_verb_in(instr_text):
        result.add("instructions_oven_verb", -3)

    if "muddle" in instr_tokens:
        result.add("instructions_muddle", 2)

    if "rim the glass" in instr_text or "rimmed with" in instr_text:
        result.add("instructions_rim_glass", 2)

    if _yield_is_drink_like(recipe.get("recipeYield")):
        result.add("yield_drink_like", 2)

    unit_counts = _count_ingredient_units(recipe.get("recipeIngredient"))
    classified = unit_counts["liquid"] + unit_counts["dry"]
    if classified and unit_counts["liquid"] / classified > 0.5:
        result.add("ingredients_liquid_units", 2)
    if classified and unit_counts["dry"] / classified > 0.5:
        result.add("ingredients_dry_units", -2)

    for hit in _bartender_hits(recipe.get("recipeIngredient")):
        result.add(f"ingredient_bartender:{hit}", 1)

    if _metadata_drink_hit(recipe.get("recipeCategory")):
        result.add("metadata_category_drink", 3)

    if _metadata_drink_hit(recipe.get("keywords")):
        result.add("metadata_keywords_drink", 3)

    if any(_metadata_drink_hit(name) for name in _breadcrumb_names(recipe)):
        result.add("metadata_breadcrumb_drink", 3)

    cook_minutes = _iso8601_minutes(recipe.get("cookTime"))
    if cook_minutes is not None and cook_minutes > 10:
        result.add("cook_time_long", -1)

    return result


@dataclass
class ReviewFailure:
    html_path: str
    expected: str
    predicted: str
    score: int
    rules: list[tuple[str, int]]
    note: str | None = None


@dataclass
class ReviewReport:
    total: int
    correct: int
    failures: list[ReviewFailure]


_ABSTAIN_LABEL = "abstain"


def _predicted_label(html: str) -> tuple[str, int, list[tuple[str, int]]]:
    """Classify and also return the score+rules from the best-scoring recipe
    so the review harness can attribute failures."""
    structured = extract_structured(html)
    recipes = list(iter_recipes(structured))
    if not recipes:
        return _ABSTAIN_LABEL, 0, []
    best = max((score_recipe(r) for r in recipes), key=lambda r: r.score)
    label = _label_for_score(best.score) or _ABSTAIN_LABEL
    return label, best.score, list(best.rules)


def _label_for_score(score: int) -> str | None:
    if score >= 2:
        return "confirmed_drink"
    if score <= -2:
        return "confirmed_food"
    return None


def run_review(entries: list[dict]) -> ReviewReport:
    """Run the classifier against a list of {html_path, expected, note?} entries.

    `expected` accepts the three labels 'confirmed_drink', 'confirmed_food',
    'abstain'. Returns a ReviewReport with totals and per-failure rule
    attribution, so the prompt-iterator can see exactly which rules fired on
    mispredictions."""
    correct = 0
    failures: list[ReviewFailure] = []
    for entry in entries:
        path = entry["html_path"]
        expected = entry["expected"]
        html = Path(path).read_text(encoding="utf-8")
        predicted, score, rules = _predicted_label(html)
        if predicted == expected:
            correct += 1
        else:
            failures.append(
                ReviewFailure(
                    html_path=path,
                    expected=expected,
                    predicted=predicted,
                    score=score,
                    rules=rules,
                    note=entry.get("note"),
                )
            )
    return ReviewReport(total=len(entries), correct=correct, failures=failures)


def _load_eval_entries(path: Path) -> list[dict]:
    """Load a jsonl eval file, resolving html_path relative to the eval file's
    parent directory (so the fixtures travel with the eval set)."""
    base = path.parent
    entries: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            data["html_path"] = str(base / data["html_path"])
            entries.append(data)
    return entries


def _print_report(report: ReviewReport) -> None:
    pct = 100 * report.correct / report.total if report.total else 0.0
    print(f"{report.correct}/{report.total} correct ({pct:.1f}%)")
    if not report.failures:
        return
    print("\nFailures:")
    for f in report.failures:
        rel = Path(f.html_path).name
        print(f"  {rel}")
        if f.note:
            print(f"    note: {f.note}")
        print(f"    expected:  {f.expected}")
        print(f"    predicted: {f.predicted}  (score={f.score})")
        if f.rules:
            rule_str = ", ".join(f"{n}{w:+d}" for n, w in f.rules)
            print(f"    rules: {rule_str}")
        else:
            print("    rules: (none fired)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="classify_drink",
        description="Scored drink/food classifier. Use --review to run against "
                    "the checked-in eval set and see per-rule attribution on failures.",
    )
    parser.add_argument("--review", action="store_true",
                        help="Run against the eval jsonl instead of the DB.")
    parser.add_argument("--eval-path", default=str(DEFAULT_EVAL_PATH),
                        help=f"Path to eval jsonl (default: {DEFAULT_EVAL_PATH}).")
    args = parser.parse_args(argv)

    if args.review:
        entries = _load_eval_entries(Path(args.eval_path))
        report = run_review(entries)
        _print_report(report)
        return 0 if report.correct == report.total else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())


def classify_drink(html: str) -> str | None:
    """Classify a page as confirmed_drink, confirmed_food, or None (abstain).

    Returns None when there is no Recipe or when the score is between -2 and 2
    (ambiguous — let the downstream LLM classifier handle it).
    """
    label, _, _ = _predicted_label(html)
    return None if label == _ABSTAIN_LABEL else label
