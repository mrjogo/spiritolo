"""Closed vocabulary tables for the ingredient parser.

Editing these tables is a parser logic change — bump PARSER_VERSION in
parser.py whenever you add or remove an alias.

Four tables, four roles. Together they govern what shows up in
ParseResult.unit and ParseResult.name:

  UNIT_ALIASES         Words the parser will populate ParseResult.unit
                       with via _try_qty_unit / _try_lexical_qty. Three
                       sub-categories live here:
                         * volume / weight measurements: oz, ml, cup,
                           tsp, tbsp, pint, quart, gallon, lb, g, kg, …
                         * imprecise bartending counts: dash, splash,
                           pinch, drop, jigger, shot, squeeze, barspoon,
                           grind, sprinkle, handful, knob, dropper, …
                         * containers: bottle, can, bag, bunch (also
                           dual-listed in COUNT_NOUN_ALIASES so they can
                           match at the tail position too).

  COUNT_NOUN_ALIASES   Form / piece / shape words. Populate
                       ParseResult.unit via _try_count_noun (head or
                       tail position). Examples: wedge, slice, leaf,
                       sprig, cube, wheel, twist, peel, zest, stick,
                       clove, pod, bean, chunk, quarter, half, coin,
                       disc, ring, segment, spear, stalk, sheet, strip,
                       scoop, piece. These describe how the ingredient
                       has been *shaped*, not the ingredient itself.

  INGREDIENT_COUNTABLES Whole-ingredient nouns that are countable but
                       are NOT measurement words: lemon, lime, orange,
                       banana, raspberry, jalapeño, cherry, berry, egg,
                       peppercorn, star anise, … When these match,
                       _try_qty_known_noun emits unit="each" — the
                       sentinel for "count of whole items," distinct
                       from any volume measurement. Whole-ingredient
                       nouns never populate the unit field directly.

  BARE_INGREDIENT_ALIASES Mass-noun ingredients seen in no-qty rows:
                       Ice, Crushed ice, Soda water, Worcestershire,
                       Vodka, Champagne, … Recognized only by
                       _try_no_qty_known_noun, which emits unit=None
                       (no qty → no unit). Never affects qty-bearing
                       parses; deliberately separate so that mass nouns
                       like `cream` or `club soda` don't mis-fire as
                       tail-position count nouns.

ParseResult.unit value space, by parser_rule:
  qty_unit            -> a UNIT_ALIASES canonical (oz, ml, dash, bottle, …).
  count_noun          -> a COUNT_NOUN_ALIASES canonical (wedge, leaf, …).
  qty_known_noun      -> the literal string "each".
  qty_annotated_name  -> None (preserved annotation; unit unknown).
  lexical_qty         -> a UNIT_ALIASES canonical (Pinch X, Splash X).
  no_qty_known_noun   -> None (no qty → no unit).
  topup, garnish_prefix -> None (semantic role, no qty/unit).
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
    "tbs": "tbsp", "tbs.": "tbsp",
    "cup": "cup", "cups": "cup", "cupful": "cup", "cupfuls": "cup",
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
    "handful": "handful", "handfuls": "handful",
    "knob": "knob", "knobs": "knob",
    "dropper": "dropper", "droppers": "dropper",
    "dropperful": "dropper", "dropperfuls": "dropper",
    "packet": "packet", "packets": "packet",
    "package": "package", "packages": "package",
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
    # plant-part count nouns (head: `4 cardamom pods`, `1 vanilla bean`,
    # `1.5 cloves garlic`). These describe a *part* of the ingredient
    # (clove, pod, bean = structural pieces) so they ARE measurement-shaped.
    # Whole-fruit names (cherry, berry, peppercorn, egg) are different —
    # they live in INGREDIENT_COUNTABLES and emit unit="each".
    "clove": "clove", "cloves": "clove",
    "pod": "pod", "pods": "pod",
    "bean": "bean", "beans": "bean",
    # serving counts and forms
    "scoop": "scoop", "scoops": "scoop",
    "strip": "strip", "strips": "strip",
    "stalk": "stalk", "stalks": "stalk",
    "sheet": "sheet", "sheets": "sheet",
    "disc": "disc", "discs": "disc", "disk": "disc", "disks": "disc",
    "coin": "coin", "coins": "coin",
    "quarter": "quarter", "quarters": "quarter",
    "chunk": "chunk", "chunks": "chunk",
    "ring": "ring", "rings": "ring",
    "segment": "segment", "segments": "segment",
    "spear": "spear", "spears": "spear",
    "half": "half", "halves": "half",
    # `springs` is a corpus typo for `sprigs` (`2 springs cilantro`).
    "spring": "sprig", "springs": "sprig",
    # NOTE: `cherry`, `berry`, `egg`, `egg white`, `egg yolk`, `peppercorn`,
    # and `star anise` are *whole-ingredient names* and live in
    # INGREDIENT_COUNTABLES, not here. Keeping them out of COUNT_NOUN
    # ensures count_noun's tail/head match never emits `unit=cherry` or
    # `unit=egg` — qty_known_noun handles them with unit="each".
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
    "lemon": "lemon", "lemons": "lemon",
    "lime": "lime", "limes": "lime",
    "orange": "orange", "oranges": "orange",
    "jalapeño": "jalapeño", "jalapeños": "jalapeño",
    "jalapeno": "jalapeño", "jalapenos": "jalapeño",
    "cardamom": "cardamom",
    # countable produce
    "olive": "olive", "olives": "olive",
    "grape": "grape", "grapes": "grape",
    "blueberry": "blueberry", "blueberries": "blueberry",
    "cranberry": "cranberry", "cranberries": "cranberry",
    "cherry": "cherry", "cherries": "cherry",
    "berry": "berry", "berries": "berry",
    "egg": "egg", "eggs": "egg",
    "egg white": "egg white", "egg whites": "egg white",
    "egg yolk": "egg yolk", "egg yolks": "egg yolk",
    "peppercorn": "peppercorn", "peppercorns": "peppercorn",
    "star anise": "star anise",
    "raisin": "raisin", "raisins": "raisin",
    "chile": "chile", "chiles": "chile",
    "chili": "chile", "chilis": "chile", "chilies": "chile",
    "habanero": "habanero", "habaneros": "habanero",
    "serrano": "serrano", "serranos": "serrano",
    "kumquat": "kumquat", "kumquats": "kumquat",
    "apricot": "apricot", "apricots": "apricot",
    "nectarine": "nectarine", "nectarines": "nectarine",
    "mango": "mango", "mangoes": "mango", "mangos": "mango",
    "watermelon": "watermelon", "watermelons": "watermelon",
    "cantaloupe": "cantaloupe", "cantaloupes": "cantaloupe",
    "honeydew": "honeydew", "honeydews": "honeydew",
    "cucumber": "cucumber", "cucumbers": "cucumber",
    "beet": "beet", "beets": "beet",
    "clementine": "clementine", "clementines": "clementine",
    "pomegranate": "pomegranate", "pomegranates": "pomegranate",
    "lemongrass": "lemongrass",
    "fig": "fig", "figs": "fig",
    "grapefruit": "grapefruit", "grapefruits": "grapefruit",
    # multi-word fruit varieties / compound ingredient names.
    "passion fruit": "passion fruit", "passion fruits": "passion fruit",
    "blood orange": "blood orange", "blood oranges": "blood orange",
    "navel orange": "navel orange", "navel oranges": "navel orange",
    "granny smith": "granny smith", "granny smiths": "granny smith",
    "honeycrisp": "honeycrisp", "honeycrisps": "honeycrisp",
    "honeydew melon": "honeydew",
}


# Mass-noun bare ingredients — recognized only by no_qty_known_noun (they
# anchor `Ice`, `Crushed ice`, `Soda water`, `Lemon-lime soda`, etc.).
# Deliberately *not* in COUNT_NOUN_ALIASES because they'd mis-fire as
# tail-position count nouns (`3 scoop Vanilla ice cream` would resolve
# to unit=cream, name="scoop vanilla ice"; `… 1 oz club soda` at the
# end of a concat row would resolve to unit="club soda" and swallow
# the genuine multi-ingredient artifact).
BARE_INGREDIENT_ALIASES: dict[str, str] = {
    # spices, herbs, baking aromatics
    "salt": "salt",
    "sugar": "sugar",
    "pepper": "pepper",
    "nutmeg": "nutmeg",
    "cinnamon": "cinnamon",
    "saffron": "saffron",
    "vanilla": "vanilla",
    "mint": "mint",
    "basil": "basil",
    "cilantro": "cilantro",
    "thyme": "thyme",
    "rosemary": "rosemary",
    "sage": "sage",
    # dairy and core mass-noun ingredients
    "ice": "ice",
    "cream": "cream",
    "milk": "milk",
    "butter": "butter",
    "honey": "honey",
    "chocolate": "chocolate",
    "cocoa": "cocoa",
    "syrup": "syrup",
    "juice": "juice",
    "bitters": "bitters",
    # generic descriptors that name a beverage/spirit category
    "water": "water",
    "tonic": "tonic",
    "soda": "soda",
    "wine": "wine",
    "beer": "beer",
    "lager": "lager",
    "ale": "ale",
    "stout": "stout",
    "cider": "cider",
    "lemonade": "lemonade",
    "cola": "cola",
    "coffee": "coffee",
    "espresso": "espresso",
    "tea": "tea",
    "chai": "chai",
    "liqueur": "liqueur",
    "absinthe": "absinthe",
    # spirits
    "vodka": "vodka",
    "gin": "gin",
    "rum": "rum",
    "whiskey": "whiskey", "whisky": "whiskey",
    "bourbon": "bourbon",
    "brandy": "brandy",
    "cognac": "cognac",
    "vermouth": "vermouth",
    "scotch": "scotch",
    "tequila": "tequila",
    "mezcal": "mezcal",
    "sake": "sake",
    # sparkling / wines
    "champagne": "champagne",
    "prosecco": "prosecco",
    "cava": "cava",
    "crémant": "crémant", "cremant": "crémant",
    "rosé": "rosé", "rose": "rosé",
    "seltzer": "seltzer",
    # condiments and sauces
    "worcestershire": "worcestershire",
    # multi-word mass-noun ingredients
    "soda water": "soda water",
    "club soda": "club soda",
    "tonic water": "tonic water",
    "ginger ale": "ginger ale",
    "ginger beer": "ginger beer",
    "sparkling water": "sparkling water",
    "seltzer water": "seltzer water",
    "sparkling wine": "sparkling wine",
    "white wine": "white wine",
    "red wine": "red wine",
    "iced tea": "iced tea",
    "hot water": "hot water",
    "cold water": "cold water",
    "boiling water": "boiling water",
    "simple syrup": "simple syrup",
    "lime juice": "lime juice",
    "lemon juice": "lemon juice",
    "orange juice": "orange juice",
    "lemon-lime soda": "lemon-lime soda",
    "worcestershire sauce": "worcestershire sauce",
    "whipping cream": "whipping cream",
    "heavy cream": "heavy cream",
    "half and half": "half and half",
    "half-and-half": "half and half",
    "maple syrup": "maple syrup",
    "agave syrup": "agave syrup",
    "agave nectar": "agave nectar",
    "horseradish": "horseradish",
    "agave": "agave",
    "ginger": "ginger",
    "ginger root": "ginger",
    "gingerroot": "ginger",
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
