"""Closed vocabulary tables for the ingredient parser.

Editing these tables is a parser logic change — bump PARSER_VERSION in
parser.py whenever you add or remove an alias.
"""

from __future__ import annotations

# Surface form -> canonical unit. Keys are matched case-insensitively.
UNIT_ALIASES: dict[str, str] = {
    # volume
    "oz": "oz", "oz.": "oz", "ounce": "oz", "ounces": "oz",
    "fl oz": "oz", "fl. oz.": "oz", "fl oz.": "oz",
    "fluid ounce": "oz", "fluid ounces": "oz",
    "ml": "ml", "ml.": "ml", "milliliter": "ml", "milliliters": "ml",
    "cl": "cl",
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "tsp": "tsp", "tsp.": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "tbsp": "tbsp", "tbsp.": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "cup": "cup", "cups": "cup",
    "pint": "pint", "pints": "pint", "pt": "pint", "pt.": "pint",
    "quart": "quart", "quarts": "quart", "qt": "quart", "qt.": "quart",
    # weight
    "g": "g", "g.": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kg.": "kg", "kilogram": "kg", "kilograms": "kg",
    "lb": "lb", "lb.": "lb", "lbs": "lb", "lbs.": "lb",
    "pound": "lb", "pounds": "lb",
    # bartending counts treated as units
    "dash": "dash", "dashes": "dash",
    "drop": "drop", "drops": "drop",
    "splash": "splash", "splashes": "splash",
    "barspoon": "barspoon", "barspoons": "barspoon",
    "bar spoon": "barspoon", "bar spoons": "barspoon",
    "pinch": "pinch", "pinches": "pinch",
    "part": "part", "parts": "part",
    "jigger": "jigger", "jiggers": "jigger",
    "pony": "pony", "ponies": "pony",
    "shot": "shot", "shots": "shot",
    "squeeze": "squeeze", "squeezes": "squeeze",
    # container counts — volume is context-dependent (wine bottle ≠ beer
    # bottle); downstream consumers must resolve the canonical volume from
    # the name, not from the unit alone.
    "bottle": "bottle", "bottles": "bottle",
    "bunch": "bunch", "bunches": "bunch",
    "can": "can", "cans": "can",
    "bag": "bag", "bags": "bag",
    "gallon": "gallon", "gallons": "gallon",
    "swath": "swath", "swaths": "swath",
    # imprecise bartending counts (`2 grind black pepper`, `1 sprinkle salt`)
    "grind": "grind", "grinds": "grind",
    "sprinkle": "sprinkle", "sprinkles": "sprinkle",
}

# Surface form -> canonical count noun. Same lookup discipline.
# True measurement count nouns. The parser populates the `unit` field
# *only* with values from this dict (or UNIT_ALIASES). If a word doesn't
# describe a measurement of an ingredient — like `lemon` or `banana` —
# it does not belong here, even if it's countable. Bare-ingredient
# countables go in INGREDIENT_COUNTABLES below.
COUNT_NOUN_ALIASES: dict[str, str] = {
    "leaf": "leaf", "leaves": "leaf",
    "slice": "slice", "slices": "slice",
    "wedge": "wedge", "wedges": "wedge",
    "wheel": "wheel", "wheels": "wheel",
    "stick": "stick", "sticks": "stick",
    "cube": "cube", "cubes": "cube",
    "sprig": "sprig", "sprigs": "sprig",
    "piece": "piece", "pieces": "piece",
    "twist": "twist", "twists": "twist",
    "egg": "egg", "eggs": "egg",
    "egg white": "egg white", "egg whites": "egg white",
    "egg yolk": "egg yolk", "egg yolks": "egg yolk",
    # garlic / spice / produce count nouns (head: `4 cardamom pods`,
    # `1 vanilla bean`, `4 maraschino cherries`, `1.5 cloves garlic`).
    "clove": "clove", "cloves": "clove",
    "pod": "pod", "pods": "pod",
    "bean": "bean", "beans": "bean",
    "cherry": "cherry", "cherries": "cherry",
    # serving counts and forms
    "scoop": "scoop", "scoops": "scoop",
    "strip": "strip", "strips": "strip",
    # parts-of-fruit (`1 lemon zest`, `2 orange peels`, `1 lime seed`).
    "zest": "zest",
    "peel": "peel", "peels": "peel",
    "seed": "seed", "seeds": "seed",
    # containers — also in UNIT_ALIASES so `1 bottle wine` (head)
    # *and* `2 wine bottles` (tail) both parse.
    "bottle": "bottle", "bottles": "bottle",
    "can": "can", "cans": "can",
    "bunch": "bunch", "bunches": "bunch",
    "bag": "bag", "bags": "bag",
    # multi-word: `2 dried Star anise` parses as amount=2, name="star anise".
    "star anise": "star anise",
}


# Countable ingredient nouns — `1 lemon`, `2 limes`, `4 raspberries`,
# `1 jalapeño`. They stand alone as the ingredient: qty_known_noun emits
# them with unit="each" (the count is a count of whole items, not a
# measurement word like `oz` or `wedge`), name=<canonical>. Kept apart
# from COUNT_NOUN_ALIASES so count_noun's tail/head match doesn't
# mis-fire — e.g. `5 cubes pineapple` resolves to unit=cube,
# name=pineapple rather than the inverted unit=pineapple, name=cubes
# we'd get if pineapple were here.
INGREDIENT_COUNTABLES: dict[str, str] = {
    "banana": "banana", "bananas": "banana",
    "pineapple": "pineapple", "pineapples": "pineapple",
    "apple": "apple", "apples": "apple",
    "pear": "pear", "pears": "pear",
    "peach": "peach", "peaches": "peach",
    "plum": "plum", "plums": "plum",
    "strawberry": "strawberry", "strawberries": "strawberry",
    "raspberry": "raspberry", "raspberries": "raspberry",
    "blackberry": "blackberry", "blackberries": "blackberry",
    "berry": "berry", "berries": "berry",
    "lemon": "lemon", "lemons": "lemon",
    "lime": "lime", "limes": "lime",
    "orange": "orange", "oranges": "orange",
    "jalapeño": "jalapeño", "jalapeños": "jalapeño",
    "jalapeno": "jalapeño", "jalapenos": "jalapeño",
    "cardamom": "cardamom",
}


# Mass-noun bare ingredients — recognized only by no_qty_known_noun (they
# anchor `Ice`, `Crushed ice`, `Soda water`, `Lemon-lime soda`, etc.).
# Deliberately *not* in COUNT_NOUN_ALIASES because they'd mis-fire as
# tail-position count nouns (`3 scoop Vanilla ice cream` would resolve
# to unit=cream, name="scoop vanilla ice"; `… 1 oz club soda` at the
# end of a concat row would resolve to unit="club soda" and swallow
# the genuine multi-ingredient artifact).
BARE_INGREDIENT_ALIASES: dict[str, str] = {
    "ice": "ice",
    "salt": "salt",
    "sugar": "sugar",
    "pepper": "pepper",
    "mint": "mint",
    "nutmeg": "nutmeg",
    "cinnamon": "cinnamon",
    "cream": "cream",
    "milk": "milk",
    "syrup": "syrup",
    "soda water": "soda water",
    "club soda": "club soda",
    "tonic water": "tonic water",
    "ginger ale": "ginger ale",
    "ginger beer": "ginger beer",
    "sparkling water": "sparkling water",
    "simple syrup": "simple syrup",
    "lime juice": "lime juice",
    "lemon juice": "lemon juice",
    "orange juice": "orange juice",
    "lemon-lime soda": "lemon-lime soda",
}


def canonicalize_unit(surface: str) -> str | None:
    if not surface:
        return None
    return UNIT_ALIASES.get(surface.lower())


def canonicalize_count_noun(surface: str) -> str | None:
    if not surface:
        return None
    return COUNT_NOUN_ALIASES.get(surface.lower())


def is_unit_alias(surface: str) -> bool:
    return canonicalize_unit(surface) is not None


def is_count_noun_alias(surface: str) -> bool:
    return canonicalize_count_noun(surface) is not None


def canonicalize_qty_noun(surface: str) -> str | None:
    """Canonical form of any noun that can stand as the ingredient in a
    qty-bearing row — true count nouns plus countable ingredients
    (`1 lemon`, `2 cardamom pods`, `1 egg white`). Excludes mass-noun
    bare ingredients (`ice`, `salt`) which only appear in no-qty rows."""
    if not surface:
        return None
    key = surface.lower()
    return COUNT_NOUN_ALIASES.get(key) or INGREDIENT_COUNTABLES.get(key)


def canonicalize_known_noun(surface: str) -> str | None:
    """Canonical form of any known noun — count nouns, countable
    ingredients, or mass-noun bare ingredients. Used by no_qty_known_noun
    so anchors like `Ice`, `Crushed ice`, `Soda water`, `Lemon wheels`,
    and `Pineapple chunks` all match."""
    if not surface:
        return None
    key = surface.lower()
    return (
        COUNT_NOUN_ALIASES.get(key)
        or INGREDIENT_COUNTABLES.get(key)
        or BARE_INGREDIENT_ALIASES.get(key)
    )
