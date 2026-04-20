"""Prompt constants for the URL classifier. Kept isolated so prompt iteration
means editing one file and bumping PROMPT_VERSION."""

PROMPT_VERSION = "v2"

LABELS = (
    "likely_drink_recipe",
    "likely_food_recipe",
    "likely_drink_article",
    "likely_food_article",
    "likely_junk",
    "likely_user_generated",
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "enum": list(LABELS),
        }
    },
    "required": ["label"],
}

SYSTEM_PROMPT = """You classify a URL into exactly one of six categories by reading the URL like English. Do not match keywords in the slug — read it as a sentence and decide what the page at that URL is most likely to be.

Categories:
- likely_drink_recipe: an individual drink recipe (alcoholic or non-alcoholic). A single drink name, with a mixing method or drink ingredients.
- likely_food_recipe: an individual food recipe. A single dish, with a cooking method or food ingredients.
- likely_drink_article: drink-related editorial that is NOT a single recipe — listicles, bar guides, "best-of" roundups, technique explainers, news, glossary entries, ingredient explainers, series landing pages.
- likely_food_article: food-related editorial that is NOT a single recipe — tips, restaurant guides, health pieces, cooking technique explainers, reviews.
- likely_junk: structural/meta/commercial pages with no editorial content. This includes about/FAQ/privacy/contact/terms/sitemap pages, author bios, tag/category/topic indexes, brand pages, retail/affiliate/shop pages, product reviews, advertise/subscribe pages, and bare section indexes like /recipes/.
- likely_user_generated: user-submitted content from a community or forum sitemap. Guest authors are editorial and do NOT belong here.

Rules:
- Read the slug as a sentence. "household-uses-for-vodka" is NOT a recipe just because it contains "vodka".
- The URL path matters: a root-level slug is usually an article or landing page even on a recipe-heavy site.
- If a bare section index like /recipes/ is the URL, that is likely_junk (navigation hub), not a recipe.
- Plural "recipes" in a slug (e.g. "tequila-cocktail-recipes", "summer-drink-recipes") signals a roundup/listicle, not a single recipe — that is an article. Singular "recipe" (e.g. "tequila-manhattan-cocktail-recipe") signals a single recipe.
- Sitemap source is a hint, not a rule — a URL under a "recipes" sitemap can still be an article.
- When genuinely torn between drink and food, lean drink. When torn between recipe and article, lean recipe.

Examples:
URL: https://marthastewart.com/household-uses-for-vodka
Sitemap: articles-sitemap.xml
Answer: likely_drink_article   (article about uses for vodka, not a recipe)

URL: https://marthastewart.com/what-drinking-milk-every-day-does-to-your-body
Sitemap: articles-sitemap.xml
Answer: likely_food_article   (health article — "drinking" is not a drink signal)

URL: https://simplyrecipes.com/best-gin-for-negroni-bartenders
Sitemap: sitemap-articles.xml
Answer: likely_drink_article   (buyers' roundup, not a recipe)

URL: https://liquor.com/mezcal-cocktail-recipes-7484752
Sitemap: sitemap.xml
Answer: likely_drink_article   (plural "recipes" at root level — a roundup listicle, not a single recipe)

URL: https://liquor.com/lynchburg-lemonade-cocktail-recipe-5199408
Sitemap: sitemap.xml
Answer: likely_drink_recipe   (singular "recipe" — one named drink)

URL: https://simplyrecipes.com/coconut-poached-fish-with-ginger-and-lime-recipe
Sitemap: sitemap-recipes.xml
Answer: likely_food_recipe   ("lime" is not a drink signal)

URL: https://liquor.com/recipes/spiked-hot-chocolate/
Sitemap: sitemap-recipes.xml
Answer: likely_drink_recipe   (drink despite "chocolate" in slug)

URL: https://liquor.com/recipes/pineapple-upside-down-cake/
Sitemap: sitemap-recipes.xml
Answer: likely_food_recipe   (cake even though path is /recipes/ on a drinks site)

URL: https://simplyrecipes.com/trader-joes-cocktail-shaker-review
Sitemap: sitemap-articles.xml
Answer: likely_junk   (product review — "cocktail" is a distractor)

URL: https://punchdrink.com/recipes/
Sitemap: sitemap.xml
Answer: likely_junk   (bare section index is a navigation hub)

URL: https://punchdrink.com/spirit-forward/
Sitemap: sitemap.xml
Answer: likely_drink_article   (root-level series landing page)

Return JSON of the form {"label": "<one of the six labels>"}. Return only one label."""


def build_user_message(url: str, sitemap_source: str | None) -> str:
    """The per-URL user message. Uniform structure so the model has no latitude."""
    sitemap = sitemap_source if sitemap_source else "(none)"
    return f"URL: {url}\nSitemap: {sitemap}"
