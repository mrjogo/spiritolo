"""Tests for the scored classify_drink module.

Each rule is an independent voter returning a signed weight. The decision
rule (score >= 2 -> drink, <= -2 -> food, else abstain) is tested at the
classify_drink() level; individual rules are tested via score_recipe() so
failures attribute cleanly to a single rule.
"""

from scraper.src.classify_drink import (
    classify_drink,
    run_review,
    score_recipe,
)


def test_empty_recipe_abstains():
    result = score_recipe({})
    assert result.score == 0
    assert result.rules == []


def test_classify_drink_empty_html_returns_none():
    assert classify_drink("<html><body></body></html>") is None


def test_classify_drink_imbibe_pattern_dessert_category_but_is_drink():
    """Imbibe sets every cocktail's recipeCategory to 'Dessert' and leaves
    keywords empty — the old classifier called this food. With scored rules,
    name ('Negroni' +3), shake+ice (+3), strain+coupe (+4), bartender
    ingredient ('vermouth' +1, 'campari' +1), liquid-unit dominance (+2)
    should overwhelm the lack of metadata drink-terms."""
    html = """<!DOCTYPE html>
<html><body>""" + ("<p>content</p>" * 500) + """
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Classic Negroni",
    "recipeCategory": "Dessert",
    "recipeIngredient": [
        "1 oz gin",
        "1 oz sweet vermouth",
        "1 oz Campari"
    ],
    "recipeInstructions": "Shake with ice and strain into a chilled coupe."
}
</script></body></html>"""
    assert classify_drink(html) == "confirmed_drink"


def test_classify_drink_bourbon_cake_is_food_not_drink():
    """Spec adversarial case: a cake with bourbon in ingredients. Name 'cake'
    (-4) + dry-unit dominance (-2) + oven verbs (-3) must overwhelm the
    bartender-ingredient bump from 'bourbon' (which isn't on our narrow
    bartender list anyway)."""
    html = """<!DOCTYPE html>
<html><body>""" + ("<p>content</p>" * 500) + """
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Bourbon Pecan Pie",
    "recipeCategory": "Dessert",
    "recipeIngredient": [
        "2 cups pecans",
        "1 cup sugar",
        "3 tablespoons butter",
        "1/4 cup bourbon"
    ],
    "recipeInstructions": "Preheat oven to 350F. Bake for 50 minutes until set.",
    "cookTime": "PT50M"
}
</script></body></html>"""
    assert classify_drink(html) == "confirmed_food"


def test_classify_drink_ambiguous_abstains():
    """A recipe with no strong signals should abstain (return None) so the
    downstream LLM classifier can have a look."""
    html = """<!DOCTYPE html>
<html><body>""" + ("<p>content</p>" * 500) + """
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Strawberry Compote",
    "recipeIngredient": ["Strawberries", "Sugar"]
}
</script></body></html>"""
    assert classify_drink(html) is None


# -- Review harness --------------------------------------------------------


def _drink_html() -> str:
    return """<!DOCTYPE html><html><body>""" + ("<p>x</p>" * 200) + """
<script type="application/ld+json">
{"@type": "Recipe", "name": "Negroni", "recipeCategory": "Cocktail",
 "recipeIngredient": ["1 oz gin", "1 oz vermouth", "1 oz Campari"],
 "recipeInstructions": "Stir with ice and strain into a rocks glass."}
</script></body></html>"""


def _food_html() -> str:
    return """<!DOCTYPE html><html><body>""" + ("<p>x</p>" * 200) + """
<script type="application/ld+json">
{"@type": "Recipe", "name": "Bourbon Pecan Pie", "recipeCategory": "Dessert",
 "recipeIngredient": ["2 cups pecans", "1 cup sugar", "3 tbsp butter"],
 "recipeInstructions": "Preheat oven to 350F. Bake 50 minutes.",
 "cookTime": "PT50M"}
</script></body></html>"""


def test_run_review_counts_matches(tmp_path):
    drink_path = tmp_path / "drink.html"
    food_path = tmp_path / "food.html"
    drink_path.write_text(_drink_html())
    food_path.write_text(_food_html())
    entries = [
        {"html_path": str(drink_path), "expected": "confirmed_drink"},
        {"html_path": str(food_path), "expected": "confirmed_food"},
    ]
    report = run_review(entries)
    assert report.correct == 2
    assert report.total == 2
    assert report.failures == []


def test_run_review_records_failures_with_rules(tmp_path):
    food_path = tmp_path / "food.html"
    food_path.write_text(_food_html())
    entries = [
        {"html_path": str(food_path), "expected": "confirmed_drink", "note": "wrong-on-purpose"},
    ]
    report = run_review(entries)
    assert report.correct == 0
    assert len(report.failures) == 1
    f = report.failures[0]
    assert f.expected == "confirmed_drink"
    assert f.predicted == "confirmed_food"
    # Failure must surface the rules that fired so the user can see WHY.
    assert any(name == "name_cooked_noun" for name, _ in f.rules)


def test_run_review_treats_abstain_as_label(tmp_path):
    """The eval set can assert 'abstain' for genuinely ambiguous pages."""
    amb_path = tmp_path / "ambiguous.html"
    amb_path.write_text("<html><body>" + "<p>x</p>" * 200 + """
<script type="application/ld+json">
{"@type": "Recipe", "name": "Strawberry Compote",
 "recipeIngredient": ["Strawberries", "Sugar"]}
</script></body></html>""")
    entries = [{"html_path": str(amb_path), "expected": "abstain"}]
    report = run_review(entries)
    assert report.correct == 1


def test_classify_drink_picks_best_recipe_when_multiple():
    """If a page has multiple Recipe blocks, classification uses the
    highest-scoring one (most confident evidence wins)."""
    html = """<!DOCTYPE html>
<html><body>""" + ("<p>content</p>" * 500) + """
<script type="application/ld+json">
{"@type": "Recipe", "name": "Garnish", "recipeIngredient": ["1 orange peel"]}
</script>
<script type="application/ld+json">
{"@type": "Recipe", "name": "Negroni", "recipeCategory": "Cocktail",
 "recipeIngredient": ["1 oz gin", "1 oz vermouth", "1 oz Campari"],
 "recipeInstructions": "Stir with ice and strain into a rocks glass."}
</script></body></html>"""
    assert classify_drink(html) == "confirmed_drink"


# -- Positive rules --------------------------------------------------------


def test_name_cocktail_family_negroni():
    r = score_recipe({"name": "Classic Negroni"})
    assert ("name_cocktail_family", 3) in r.rules
    assert r.score == 3


def test_name_cocktail_family_whiskey_sour():
    r = score_recipe({"name": "Whiskey Sour"})
    assert ("name_cocktail_family", 3) in r.rules


def test_name_cocktail_family_case_insensitive():
    r = score_recipe({"name": "PALOMA"})
    assert ("name_cocktail_family", 3) in r.rules


def test_name_no_cocktail_family_word():
    r = score_recipe({"name": "Grilled Salmon"})
    assert all(rule != "name_cocktail_family" for rule, _ in r.rules)


def test_name_substring_does_not_match():
    """'smash' must not match 'smashed' — word boundaries required."""
    r = score_recipe({"name": "Smashed Potatoes"})
    assert all(rule != "name_cocktail_family" for rule, _ in r.rules)


def test_instructions_shake_near_ice():
    r = score_recipe({
        "recipeInstructions": "Combine ingredients, shake with ice, and pour.",
    })
    assert ("instructions_shake_ice", 3) in r.rules


def test_instructions_shake_far_from_ice_does_not_fire():
    text = "Shake the tree to loosen fruit. " + ("Then do lots of other prep. " * 30) + "Serve over ice cream."
    r = score_recipe({"recipeInstructions": text})
    assert all(rule != "instructions_shake_ice" for rule, _ in r.rules)


def test_instructions_shake_without_ice_does_not_fire():
    r = score_recipe({"recipeInstructions": "Shake flour onto the counter."})
    assert all(rule != "instructions_shake_ice" for rule, _ in r.rules)


def test_instructions_strain_near_glass():
    r = score_recipe({
        "recipeInstructions": "Shake hard, then strain into a chilled coupe.",
    })
    assert ("instructions_strain_glassware", 4) in r.rules


def test_instructions_strain_near_rocks_glass():
    r = score_recipe({
        "recipeInstructions": "Stir until cold, then strain over ice into a rocks glass.",
    })
    assert ("instructions_strain_glassware", 4) in r.rules


def test_instructions_strain_pasta_does_not_fire():
    r = score_recipe({
        "recipeInstructions": "Boil pasta until al dente. Strain and toss with sauce.",
    })
    assert all(rule != "instructions_strain_glassware" for rule, _ in r.rules)


def test_instructions_muddle():
    r = score_recipe({"recipeInstructions": "Muddle the mint leaves with sugar."})
    assert ("instructions_muddle", 2) in r.rules


def test_instructions_no_muddle():
    r = score_recipe({"recipeInstructions": "Combine dry ingredients and whisk."})
    assert all(rule != "instructions_muddle" for rule, _ in r.rules)


def test_instructions_rim_the_glass():
    r = score_recipe({"recipeInstructions": "Rim the glass with salt before pouring."})
    assert ("instructions_rim_glass", 2) in r.rules


def test_instructions_rimmed_with():
    r = score_recipe({"recipeInstructions": "Serve in a coupe rimmed with sugar."})
    assert ("instructions_rim_glass", 2) in r.rules


def test_yield_mentions_cocktail():
    r = score_recipe({"recipeYield": "1 cocktail"})
    assert ("yield_drink_like", 2) in r.rules


def test_yield_mentions_drink():
    r = score_recipe({"recipeYield": "2 drinks"})
    assert ("yield_drink_like", 2) in r.rules


def test_yield_small_numeric_servings():
    """Raw integer recipeYield of 1 or 2 is drink-sized. 4+ is family-sized food."""
    r = score_recipe({"recipeYield": 1})
    assert ("yield_drink_like", 2) in r.rules


def test_yield_large_numeric_servings_does_not_fire():
    r = score_recipe({"recipeYield": 8})
    assert all(rule != "yield_drink_like" for rule, _ in r.rules)


def test_yield_food_serving_does_not_fire():
    r = score_recipe({"recipeYield": "Serves 4"})
    assert all(rule != "yield_drink_like" for rule, _ in r.rules)


def test_ingredients_liquid_units_dominant():
    r = score_recipe({
        "recipeIngredient": [
            "2 oz tequila",
            "1 oz lime juice",
            "0.5 oz triple sec",
            "1 dash orange bitters",
            "Salt for the rim",
        ],
    })
    assert ("ingredients_liquid_units", 2) in r.rules


def test_ingredients_ml_units_dominant():
    r = score_recipe({
        "recipeIngredient": [
            "60 ml gin",
            "30 ml lemon juice",
            "15 ml simple syrup",
        ],
    })
    assert ("ingredients_liquid_units", 2) in r.rules


def test_ingredients_dry_units_do_not_fire():
    r = score_recipe({
        "recipeIngredient": [
            "2 cups flour",
            "1 tbsp sugar",
            "1 lb butter",
        ],
    })
    assert all(rule != "ingredients_liquid_units" for rule, _ in r.rules)


def test_ingredient_bitters():
    r = score_recipe({"recipeIngredient": ["2 dashes Angostura bitters"]})
    assert ("ingredient_bartender:bitters", 1) in r.rules


def test_ingredient_vermouth_and_campari_both_fire():
    """Each bartender-specific ingredient fires its own +1 vote."""
    r = score_recipe({
        "recipeIngredient": [
            "1 oz sweet vermouth",
            "1 oz Campari",
        ],
    })
    fired = {rule for rule, _ in r.rules if rule.startswith("ingredient_bartender:")}
    assert "ingredient_bartender:vermouth" in fired
    assert "ingredient_bartender:campari" in fired


def test_ingredient_no_bartender_items():
    r = score_recipe({"recipeIngredient": ["1 cup flour", "2 eggs"]})
    assert all(not rule.startswith("ingredient_bartender:") for rule, _ in r.rules)


def test_category_drink_term():
    r = score_recipe({"recipeCategory": "Cocktail"})
    assert ("metadata_category_drink", 3) in r.rules


def test_category_list_of_strings():
    r = score_recipe({"recipeCategory": ["Dinner", "Drinks"]})
    assert ("metadata_category_drink", 3) in r.rules


def test_category_no_drink_term():
    r = score_recipe({"recipeCategory": "Main Course"})
    assert all(rule != "metadata_category_drink" for rule, _ in r.rules)


def test_keywords_drink_term():
    r = score_recipe({"keywords": "spritz, aperitivo, easy"})
    assert ("metadata_keywords_drink", 3) in r.rules


def test_keywords_list():
    r = score_recipe({"keywords": ["beverages", "party"]})
    assert ("metadata_keywords_drink", 3) in r.rules


def test_breadcrumb_drink_term():
    r = score_recipe({
        "mainEntityOfPage": {
            "@type": "WebPage",
            "breadcrumb": {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"item": {"name": "Recipes"}},
                    {"item": {"name": "Cocktails"}},
                ],
            },
        },
    })
    assert ("metadata_breadcrumb_drink", 3) in r.rules


def test_breadcrumb_no_drink_term():
    r = score_recipe({
        "mainEntityOfPage": {
            "breadcrumb": {
                "itemListElement": [{"item": {"name": "Desserts"}}],
            },
        },
    })
    assert all(rule != "metadata_breadcrumb_drink" for rule, _ in r.rules)


# -- Negative rules --------------------------------------------------------


def test_name_cake_is_negative():
    r = score_recipe({"name": "Bourbon Pecan Pie"})
    assert ("name_cooked_noun", -4) in r.rules


def test_name_pasta_is_negative():
    r = score_recipe({"name": "Creamy Mushroom Pasta"})
    assert ("name_cooked_noun", -4) in r.rules


def test_name_salad_is_negative():
    r = score_recipe({"name": "Caesar Salad"})
    assert ("name_cooked_noun", -4) in r.rules


def test_name_without_cooked_noun_does_not_fire():
    r = score_recipe({"name": "Classic Negroni"})
    assert all(rule != "name_cooked_noun" for rule, _ in r.rules)


def test_cooked_noun_vetoes_cocktail_family_in_same_name():
    """A name like 'Cocktail Sauce' or 'Margarita Cake' matches both a cocktail
    family word and a cooked noun. When both are present the cooked noun wins:
    the page is describing a dish, and the cocktail-family bump would otherwise
    cancel the food signal and push the page into abstain."""
    r = score_recipe({"name": "Classic Cocktail Sauce"})
    assert ("name_cooked_noun", -4) in r.rules
    assert all(rule != "name_cocktail_family" for rule, _ in r.rules)


def test_cooked_noun_vetoes_margarita_in_cake_name():
    r = score_recipe({"name": "Margarita Lime Cake"})
    assert ("name_cooked_noun", -4) in r.rules
    assert all(rule != "name_cocktail_family" for rule, _ in r.rules)


def test_instructions_preheat_oven():
    r = score_recipe({"recipeInstructions": "Preheat oven to 350°F."})
    assert ("instructions_oven_verb", -3) in r.rules


def test_instructions_bake_at():
    r = score_recipe({"recipeInstructions": "Bake at 400 degrees for 25 minutes."})
    assert ("instructions_oven_verb", -3) in r.rules


def test_instructions_roast_at():
    r = score_recipe({"recipeInstructions": "Roast at 425°F until golden."})
    assert ("instructions_oven_verb", -3) in r.rules


def test_instructions_no_oven_verb():
    r = score_recipe({"recipeInstructions": "Shake with ice and strain."})
    assert all(rule != "instructions_oven_verb" for rule, _ in r.rules)


def test_ingredients_dry_units_dominant():
    r = score_recipe({
        "recipeIngredient": [
            "2 cups flour",
            "1 cup sugar",
            "4 tablespoons butter",
            "1 tsp salt",
        ],
    })
    assert ("ingredients_dry_units", -2) in r.rules


def test_ingredients_dry_units_do_not_fire_for_drinks():
    r = score_recipe({
        "recipeIngredient": [
            "2 oz tequila",
            "1 oz lime juice",
        ],
    })
    assert all(rule != "ingredients_dry_units" for rule, _ in r.rules)


def test_cook_time_over_10_minutes_iso8601():
    r = score_recipe({"cookTime": "PT30M"})
    assert ("cook_time_long", -1) in r.rules


def test_cook_time_under_10_minutes_does_not_fire():
    r = score_recipe({"cookTime": "PT5M"})
    assert all(rule != "cook_time_long" for rule, _ in r.rules)


def test_cook_time_absent_does_not_fire():
    r = score_recipe({})
    assert all(rule != "cook_time_long" for rule, _ in r.rules)


def test_cook_time_hours():
    r = score_recipe({"cookTime": "PT2H"})
    assert ("cook_time_long", -1) in r.rules


def test_instructions_as_list_of_howto_steps():
    """Schema.org allows recipeInstructions as a list of HowToStep dicts."""
    r = score_recipe({
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Combine ingredients."},
            {"@type": "HowToStep", "text": "Shake vigorously with ice."},
            {"@type": "HowToStep", "text": "Strain into glass."},
        ],
    })
    assert ("instructions_shake_ice", 3) in r.rules
