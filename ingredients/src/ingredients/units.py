"""Vocabulary the ingredient parser matches on.

Unit recognition (measurement units and shape/form count nouns) is delegated to
**RecipeGF's registry** — the single unit authority. RecipeGF's ``UnitValidator``
decides validity and canonical spelling (``is_valid`` / ``normalize`` /
``get_approx_ml``); this module reads RecipeGF's ``bar-units`` and ``count-units``
registries to keep the parser's two recognition sets (measurement-unit surfaces
vs count-noun surfaces) and to canonicalize to RecipeGF's spelling — so a parsed
unit is emitted exactly as RecipeGF names it (``Tbs``, ``pnt``, ``qt``, ``gal``,
``each`` for a cube/piece), needing no downstream translation. A small
``_SPELLED_OUT`` bridge supplies the natural-language surface forms recipe text
uses that RecipeGF's convert-units snapshot does not carry (``ounce``,
``teaspoon``, ``milliliter``, ``gram``, ``pound``, ``liter``, …).

The two INGREDIENT tables below are *identity*, not units, so they stay here:

  INGREDIENT_COUNTABLES Whole-ingredient nouns that are countable but are NOT
                       measurement words: lemon, lime, orange, banana, cherry,
                       egg, star anise, … When these match, _try_qty_known_noun
                       emits unit="each" — count of whole items.

  BARE_INGREDIENT_ALIASES Mass-noun ingredients seen in no-qty rows: Ice,
                       Soda water, Vodka, Champagne, … Recognized only by
                       _try_no_qty_known_noun (unit=None).

Editing the INGREDIENT tables or the ``_SPELLED_OUT`` bridge is a parser logic
change — bump PARSER_VERSION in parser.py.

ParseResult.unit value space, by parser_rule:
  qty_unit            -> a RecipeGF measurement-unit canonical (oz, ml, dash, …).
  count_noun          -> a RecipeGF count-unit canonical (wedge, leaf, each, …).
  qty_known_noun      -> the literal string "each".
  qty_annotated_name  -> None (preserved annotation; unit unknown).
  lexical_qty         -> a RecipeGF measurement-unit canonical (Pinch X, Splash X).
  no_qty_known_noun   -> None (no qty → no unit).
  topup, garnish_prefix -> None (semantic role, no qty/unit).
"""

from __future__ import annotations

from recipegf import UnitValidator, spec

_UNITS = UnitValidator()


def _registry_surface_map(relpath: str) -> dict[str, str]:
    """Surface-form (lowercased) -> RecipeGF canonical name, for one registry
    unit file. Each unit contributes its own name plus every alias."""
    out: dict[str, str] = {}
    for unit in spec.load_yaml(relpath)["units"]:
        name = unit["name"]
        out[name.lower()] = name
        for alias in unit.get("aliases") or []:
            out[alias.lower()] = name
    return out


# Natural-language unit surfaces recipe text uses that RecipeGF's convert-units
# snapshot doesn't accept on its own (it carries abbreviations + the bar/count
# aliases, not the spelled-out standard words). Values are RecipeGF-canonical.
_SPELLED_OUT: dict[str, str] = {
    "oz.": "oz", "ounce": "oz", "ounces": "oz",
    "fl oz": "oz", "fl. oz.": "oz", "fl oz.": "oz",
    "fluid ounce": "oz", "fluid ounces": "oz",
    "ml.": "ml", "milliliter": "ml", "milliliters": "ml",
    "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "teaspoon": "tsp", "teaspoons": "tsp", "tsp.": "tsp",
    "tablespoons": "Tbs", "tbsp.": "Tbs", "tbs.": "Tbs",
    "cups": "cup", "cupful": "cup", "cupfuls": "cup",
    "gram": "g", "grams": "g", "g.": "g",
    "kilogram": "kg", "kilograms": "kg", "kg.": "kg",
    "pound": "lb", "pounds": "lb", "lbs": "lb", "lbs.": "lb", "lb.": "lb",
    "pt": "pnt", "pt.": "pnt", "pints": "pnt",
    "qt.": "qt", "gallons": "gal",
    "bar spoon": "barspoon", "bar spoons": "barspoon",
}

# RecipeGF standard (convert-units) abbreviations that are recipe-relevant. The
# full snapshot carries physics/computing noise (m, s, t, d, Hz, kW, …); the
# parser must not treat `1 m mint` as meters, so only this curated volume/weight
# set from the standard registry is admitted.
_STANDARD_ALLOW = {"cup", "l", "cl", "dl", "ml", "g", "kg", "mg", "lb", "oz", "tsp"}

# Measurement-unit surfaces (qty_unit / lexical_qty): RecipeGF bar-units +
# curated standard abbreviations + the spelled-out bridge.
_UNIT_SURFACE: dict[str, str] = {
    **_registry_surface_map("registry/units/bar-units.yaml"),
    **{u: u for u in _STANDARD_ALLOW},
    **_SPELLED_OUT,
}

# Count-noun surfaces (count_noun): RecipeGF count-units + the container words
# that dual-list as both a measure (bar-units) and a tail count noun, so
# `1 bottle wine` and `2 wine bottles` both parse.
_COUNT_SURFACE: dict[str, str] = {
    **_registry_surface_map("registry/units/count-units.yaml"),
    "bottle": "bottle", "bottles": "bottle",
    "can": "can", "cans": "can",
    "bunch": "bunch", "bunches": "bunch",
    "bag": "bag", "bags": "bag",
    # `springs` is a corpus typo for `sprigs` (`2 springs cilantro`).
    "spring": "sprig", "springs": "sprig",
}


def unit_surface_forms() -> list[str]:
    """Every measurement-unit surface form the parser recognizes. The parser
    builds its concatenated-row guard alternation from this set."""
    return list(_UNIT_SURFACE.keys())


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
    """RecipeGF canonical spelling of a measurement unit surface form, or None.
    RecipeGF is the authority; this only maps recipe-text surfaces onto it."""
    if not surface:
        return None
    return _UNIT_SURFACE.get(surface.lower())


def canonicalize_count_noun(surface: str) -> str | None:
    """RecipeGF canonical spelling of a shape/form count-noun surface, or None."""
    if not surface:
        return None
    return _COUNT_SURFACE.get(surface.lower())


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
    return _COUNT_SURFACE.get(key) or INGREDIENT_COUNTABLES.get(key)


def canonicalize_known_noun(surface: str) -> str | None:
    """Canonical form of any known noun — count nouns, countable
    ingredients, or mass-noun bare ingredients. Used by no_qty_known_noun
    so anchors like `Ice`, `Crushed ice`, `Soda water`, `Lemon wheels`,
    and `Pineapple chunks` all match."""
    if not surface:
        return None
    key = surface.lower()
    return (
        _COUNT_SURFACE.get(key)
        or INGREDIENT_COUNTABLES.get(key)
        or BARE_INGREDIENT_ALIASES.get(key)
    )
