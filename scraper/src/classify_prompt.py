"""Prompt constants for the URL classifier. Kept isolated so prompt iteration
means editing one file and bumping PROMPT_VERSION."""

PROMPT_VERSION = "v4"

LABELS = (
    "likely_drink_recipe",
    "likely_food_recipe",
    "likely_drink_article",
    "likely_food_article",
    "likely_cocktail_adjacent",
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
- likely_junk: structural/meta/commercial pages with no editorial content. This includes about/FAQ/privacy/contact/terms/sitemap pages, author bios, tag/category/topic indexes, brand landing/marketing pages, retail/affiliate/shop pages, product reviews, advertise/subscribe pages, and bare section indexes like /recipes/.
- likely_user_generated: user-submitted content from a community or forum sitemap. Guest authors are editorial and do NOT belong here.

Rules:
- Read the slug as a sentence. "household-uses-for-vodka" is NOT a recipe just because it contains "vodka".
- Read the whole URL, not just the slug. Path segments between the domain and the slug (e.g. `/beer-wine-spirits/`, `/bars/`, `/forum/`, `/author/`, `/videos/`, `/encyclopedia/`) categorize the page and usually override food- or drink-sounding words in the slug. `/beer-wine-spirits/` specifically is a product catalog, not a recipe archive — every URL under it is a drink product (`likely_drink_article`) regardless of whether the slug reads like a dessert, a cocktail, or a single beer name. `/videos/` is a video page — usually `likely_junk` because there is no text recipe to extract; when the slug is clearly an editorial explainer (e.g. `/videos/what-actually-is-umami`, `/videos/channels/how-to-waste-less-food-tips-for-smarter-shopping`), `likely_food_article` / `likely_drink_article` is acceptable. `/encyclopedia/` (diffordsguide) is guide/explainer content — label `likely_drink_article` in the vast majority of cases, even when the slug reads like a single-drink recipe (`/encyclopedia/*/cocktails/espresso-martini`, `/encyclopedia/*/cocktails/diy-nut-and-rice-milk`). The main exceptions are bartender bios at `/encyclopedia/*/people/<name>`, company-info pages, and venue/bar pages, which are `likely_junk`. Note that some paths (e.g. diffordsguide `/producer/<id>/<brand>/<slug>`) are mixed — cocktails, brand articles, and products all live there — so fall back to the slug in those cases.
- A `-review-` token in the slug usually marks a review. Product reviews and recipe reviews are `likely_junk` (e.g. `azalea-cocktail-recipe-review-23778057`, `trader-joes-cocktail-shaker-review`). Book reviews, diet reviews, budget/strategy reviews, and restaurant reviews are editorial and belong in `likely_food_article` / `likely_drink_article`.
- A `drink-of-the-week-*` slug prefix is a weekly single-drink feature. Named cocktails with a method are `likely_drink_recipe`. Single-bottle spotlights — wines, beers, spirits, coffees, tonic waters, tasting sets — are product notes, `likely_drink_article`.
- A root-level slug is usually an article or landing page even on a recipe-heavy site.
- If a bare section index like /recipes/ is the URL, that is likely_junk (navigation hub), not a recipe.
- Plural "recipes" in a slug (e.g. "tequila-cocktail-recipes", "summer-drink-recipes") signals a roundup/listicle, not a single recipe — that is an article. Singular "recipe" (e.g. "tequila-manhattan-cocktail-recipe") signals a single recipe.
- Sitemap source is usually just a hint, but when a sitemap's name clearly denotes a single category (e.g. a products sitemap containing only drink products, a "bars" sitemap, a "forum" sitemap, a "user-generated" sitemap) treat it as effectively a ground-truth label and prefer it over slug semantics.
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

URL: https://www.thekitchn.com/azalea-cocktail-recipe-review-23778057
Sitemap: sitemap.xml
Answer: likely_junk   (`-review-` in the slug forces junk even though "recipe" is present)

URL: https://imbibemagazine.com/drink-of-the-week-mountain-rose-matcha/
Sitemap: sitemap.xml
Answer: likely_drink_recipe   (`drink-of-the-week-*` is a weekly feature with one named drink)

URL: https://punchdrink.com/recipes/
Sitemap: sitemap.xml
Answer: likely_junk   (bare section index is a navigation hub)

URL: https://punchdrink.com/spirit-forward/
Sitemap: sitemap.xml
Answer: likely_drink_article   (root-level series landing page)

URL: https://www.foodnetwork.com/videos/negroni-jack-o-lanterns-21804282
Sitemap: sitemap_food_10.xml.gz
Answer: likely_junk   (video page with a single-drink slug — `/videos/` means no extractable recipe text)

URL: https://www.foodnetwork.com/videos/what-actually-is-umami-13997896
Sitemap: sitemap_food_8.xml.gz
Answer: likely_food_article   (video page but the slug is an editorial explainer, not a single recipe)

URL: https://www.diffordsguide.com/beer-wine-spirits/6712/baileys-red-velvet-cupcake
Sitemap: https://www.diffordsguide.com/sitemap/gb.xml
Answer: likely_drink_article   (flavored liqueur — `/beer-wine-spirits/` path and products sitemap dominate "cupcake" in the slug)

URL: https://www.diffordsguide.com/beer-wine-spirits/6614/three-legs-oatmeal-stout
Sitemap: https://www.diffordsguide.com/sitemap/gb.xml
Answer: likely_drink_article   (a beer product — `/beer-wine-spirits/` is a catalog, so even slugs that name a single drink resolve to drink_article, not drink_recipe)

URL: https://www.diffordsguide.com/encyclopedia/393/cocktails/jamies-italian-bar-cocktails-how-to-make
Sitemap: https://www.diffordsguide.com/sitemap/gb.xml
Answer: likely_drink_article   (`/encyclopedia/` is guide/explainer content — the strong prior is drink_article)

URL: https://www.diffordsguide.com/encyclopedia/2842/people/lauren-shaw
Sitemap: https://www.diffordsguide.com/sitemap/gb.xml
Answer: likely_junk   (bartender bio under `/encyclopedia/*/people/` — author-bio-style page)

URL: https://imbibemagazine.com/drink-of-the-week-montinore-estate-roulette-pinot-gris/
Sitemap: https://imbibemagazine.com/post-sitemap.xml
Answer: likely_drink_article   (`drink-of-the-week-*` but the subject is a single wine bottle — a product spotlight, not a mixed drink)

URL: https://www.thekitchn.com/book-review-local-breads-by-da-53854
Sitemap: https://www.thekitchn.com/sitemap-2022-05.xml
Answer: likely_food_article   (`-review-` in slug but it's a book review — editorial, not a product/recipe review)

URL: https://www.diffordsguide.com/bars/w9R86z/crescent-sausage-and-pie
Sitemap: https://www.diffordsguide.com/sitemap/bar.xml
Answer: likely_junk   (venue page — `/bars/` path and bar sitemap override the food-sounding slug)

URL: https://www.diffordsguide.com/cocktails/recipe/228/black-forest-gateau
Sitemap: https://www.diffordsguide.com/sitemap/cocktail.xml
Answer: likely_drink_recipe   (cocktail named after a dessert — `/cocktails/recipe/` path is definitive)

URL: https://www.diffordsguide.com/producer/1178/ramsbury/estate-snapper
Sitemap: https://www.diffordsguide.com/sitemap/gb.xml
Answer: likely_drink_recipe   (the final slug is a single cocktail name; `/producer/<id>/<brand>/<slug>` is a mixed path, so the slug wins)

URL: https://www.diffordsguide.com/producer/1100/hendricks-gin-palace-distillery/story
Sitemap: https://www.diffordsguide.com/sitemap/gb.xml
Answer: likely_drink_article   (brand story under a producer path — substantive editorial, not a landing page)

Return JSON of the form {"label": "<one of the six labels>"}. Return only one label."""


def build_user_message(url: str, sitemap_source: str | None) -> str:
    """The per-URL user message. Uniform structure so the model has no latitude."""
    sitemap = sitemap_source if sitemap_source else "(none)"
    return f"URL: {url}\nSitemap: {sitemap}"
