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
}

# Surface form -> canonical count noun. Same lookup discipline.
COUNT_NOUN_ALIASES: dict[str, str] = {
    "leaf": "leaf", "leaves": "leaf",
    "slice": "slice", "slices": "slice",
    "wedge": "wedge", "wedges": "wedge",
    "wheel": "wheel", "wheels": "wheel",
    "stick": "stick", "sticks": "stick",
    "cube": "cube", "cubes": "cube",
    "sprig": "sprig", "sprigs": "sprig",
    "piece": "piece", "pieces": "piece",
    "egg white": "egg white", "egg whites": "egg white",
    "egg yolk": "egg yolk", "egg yolks": "egg yolk",
    "egg": "egg", "eggs": "egg",
    "twist": "twist", "twists": "twist",
    # citrus — `1 lemon, sliced` / `1 orange half-wheel` / etc.
    "lemon": "lemon", "lemons": "lemon",
    "lime": "lime", "limes": "lime",
    "orange": "orange", "oranges": "orange",
    # garlic / spice / produce count nouns (head: `4 cardamom pods`,
    # `1 vanilla bean`, `4 maraschino cherries`, `1.5 cloves garlic`).
    "clove": "clove", "cloves": "clove",
    "pod": "pod", "pods": "pod",
    "bean": "bean", "beans": "bean",
    "cherry": "cherry", "cherries": "cherry",
    "star anise": "star anise",
    # serving counts
    "scoop": "scoop", "scoops": "scoop",
    # bare-ingredient nouns (no separate count word). Recognized by the
    # qty_known_noun rule so `1 lemon` / `1 banana` / `1 star anise` parse
    # as amount=N, unit=None, name=<canonical>.
    "banana": "banana", "bananas": "banana",
    "pineapple": "pineapple", "pineapples": "pineapple",
    "apple": "apple", "apples": "apple",
    "pear": "pear", "pears": "pear",
    "peach": "peach", "peaches": "peach",
    "plum": "plum", "plums": "plum",
    "strawberry": "strawberry", "strawberries": "strawberry",
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
