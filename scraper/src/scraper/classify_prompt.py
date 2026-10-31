"""Prompt constants for the URL classifier. Kept isolated so prompt iteration
means editing one file and bumping PROMPT_VERSION."""

# v5: the reply is schema-constrained to MODEL_LABELS, and the prompt no longer
# hardcodes a category count. v8: role sentence, XML-tagged sections and
# examples, descriptions shared with the Decisions API choices.
PROMPT_VERSION = "v8"

# The labels the model chooses from; SYSTEM_PROMPT documents exactly these.
MODEL_LABELS = (
    "likely_drink_recipe",
    "likely_food_recipe",
    "likely_drink_article",
    "likely_food_article",
    "likely_junk",
    "likely_user_generated",
)

# Every label a page can carry. The two extra ones are assigned only by the
# operator's rule-based relabelling (scripts/manual_reclassification.py), never
# by the model, so the prompt does not describe them.
LABELS = (
    "likely_drink_recipe",
    "likely_food_recipe",
    "likely_drink_article",
    "likely_food_article",
    "likely_cocktail_adjacent",
    "likely_unstructured_drink_recipe",
    "likely_junk",
    "likely_user_generated",
)

# Strict-mode shaped (OpenAI structured outputs needs additionalProperties).
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "description": "The one category that best describes the page at the URL.",
            "enum": list(MODEL_LABELS),
        }
    },
    "required": ["label"],
    "additionalProperties": False,
}

LABEL_DESCRIPTIONS: dict[str, str] = {
    'likely_drink_recipe': (
        'an individual drink recipe (alcoholic or non-alcoholic). A single drink name, with a mixing method or drink ingredients.'
    ),
    'likely_food_recipe': (
        'an individual food recipe. A single dish, with a cooking method or food ingredients.'
    ),
    'likely_drink_article': (
        'drink-related editorial other than a single recipe — listicles, bar guides, "best-of" roundups, technique explainers, news, glossary entries, ingredient explainers, series landing pages.'
    ),
    'likely_food_article': (
        'food-related editorial other than a single recipe — tips, restaurant guides, health pieces, cooking technique explainers, reviews.'
    ),
    'likely_junk': (
        'structural/meta/commercial pages with no editorial content. This includes about/FAQ/privacy/contact/terms/sitemap pages, author bios, tag/category/topic indexes, brand landing/marketing pages, retail/affiliate/shop pages, product reviews, advertise/subscribe pages, and bare section indexes like /recipes/. Also editorial with no food, drink or kitchen angle on a food site (home decor, paint colours, fabric care, crafts, weddings, gardening, flower arranging): it never leads to a recipe, so it is junk, not likely_food_article. Kitchen content stays editorial — cookware, knives, storage, stoves, cleaning with food (`white-bread-cleaning`), cooking tips — is likely_food_article. A URL with no readable words beyond the domain (a homepage, or an opaque id with no categorizing path) is also junk.'
    ),
    'likely_user_generated': (
        "user-submitted content — forum threads, community/member/reader recipes and galleries. A recipe-shaped URL under a member path (`/recipes/member/`, `/community/`, `/people/our-readers/`) is user_generated, not a recipe label, even when the slug reads like a single recipe; so is a cocktail-database recipe whose slug ends in a submitter's name plus `-recipe` (diffordsguide `/cocktails/recipe/<id>/singapore-sling-franks-recipe`). A possessive bartender or author name in an editorial site's recipe slug (`/recipes/jelani-johnsons-painkiller/`) is an attributed house recipe, NOT user-generated. Guest posts and guest authors (`guest-post-*`) are editorial: give them the article label."
    ),
}

_RULES: tuple[str, ...] = (
    'Read the slug as a sentence: "household-uses-for-vodka" is an article about vodka, not a recipe, even though it contains "vodka".',
    'Read the whole URL, not just the slug. Path segments between the domain and the slug (e.g. `/beer-wine-spirits/`, `/bars/`, `/forum/`, `/author/`, `/videos/`, `/encyclopedia/`) categorize the page and usually override food- or drink-sounding words in the slug. `/beer-wine-spirits/` specifically is a product catalog, not a recipe archive — every URL under it is a drink product (`likely_drink_article`) regardless of whether the slug reads like a dessert, a cocktail, or a single beer name. `/videos/` is a video page — usually `likely_junk` because there is no text recipe to extract; when the slug is clearly an editorial explainer (e.g. `/videos/what-actually-is-umami`, `/videos/channels/how-to-waste-less-food-tips-for-smarter-shopping`), `likely_food_article` / `likely_drink_article` is acceptable. `/encyclopedia/` (diffordsguide) is guide/explainer content — label `likely_drink_article` in the vast majority of cases, even when the slug reads like a single-drink recipe (`/encyclopedia/*/cocktails/espresso-martini`, `/encyclopedia/*/cocktails/diy-nut-and-rice-milk`). The main exceptions are bartender bios at `/encyclopedia/*/people/<name>`, company-info pages, and venue/bar pages, which are `likely_junk`. Note that some paths (e.g. diffordsguide `/producer/<id>/<brand>/<slug>`) are mixed — cocktails, brand articles, and products all live there — so fall back to the slug in those cases.',
    'A `-review-` token in the slug usually marks a review. Product reviews and recipe reviews are `likely_junk` (e.g. `azalea-cocktail-recipe-review-23778057`, `trader-joes-cocktail-shaker-review`). Book reviews, diet reviews, budget/strategy reviews, and restaurant reviews are editorial and belong in `likely_food_article` / `likely_drink_article`.',
    'A `drink-of-the-week-*` slug prefix is a weekly single-drink feature. Named cocktails with a method are `likely_drink_recipe`. Single-bottle spotlights — wines, beers, spirits, coffees, tonic waters, tasting sets — are product notes, `likely_drink_article`.',
    'A root-level slug is usually an article or landing page even on a recipe-heavy site.',
    'If a bare section index like /recipes/ is the URL, that is likely_junk (navigation hub), not a recipe.',
    'Plural "recipes" in a slug (e.g. "tequila-cocktail-recipes", "summer-drink-recipes") signals a roundup/listicle, not a single recipe — that is an article. Singular "recipe" (e.g. "tequila-manhattan-cocktail-recipe") signals a single recipe.',
    'Sitemap source is usually just a hint, but when a sitemap\'s name clearly denotes a single category (e.g. a products sitemap containing only drink products, a "bars" sitemap, a "forum" sitemap, a "user-generated" sitemap) treat it as effectively a ground-truth label and prefer it over slug semantics.',
    'When genuinely torn between drink and food, lean drink. When torn between recipe and article, lean recipe.',
)

# (url, sitemap, answer, why) — rendered as <example> blocks. Diverse on purpose:
# each one is a failure mode a model has actually shown.
_EXAMPLES: tuple[tuple[str, str, str, str], ...] = (
    ('https://marthastewart.com/household-uses-for-vodka', 'articles-sitemap.xml',
     'likely_drink_article', 'article about uses for vodka, not a recipe'),
    ('https://marthastewart.com/what-drinking-milk-every-day-does-to-your-body', 'articles-sitemap.xml',
     'likely_food_article', 'health article — "drinking" is not a drink signal'),
    ('https://simplyrecipes.com/best-gin-for-negroni-bartenders', 'sitemap-articles.xml',
     'likely_drink_article', "buyers' roundup, not a recipe"),
    ('https://liquor.com/mezcal-cocktail-recipes-7484752', 'sitemap.xml',
     'likely_drink_article', 'plural "recipes" at root level — a roundup listicle, not a single recipe'),
    ('https://liquor.com/lynchburg-lemonade-cocktail-recipe-5199408', 'sitemap.xml',
     'likely_drink_recipe', 'singular "recipe" — one named drink'),
    ('https://simplyrecipes.com/coconut-poached-fish-with-ginger-and-lime-recipe', 'sitemap-recipes.xml',
     'likely_food_recipe', '"lime" is not a drink signal'),
    ('https://liquor.com/recipes/spiked-hot-chocolate/', 'sitemap-recipes.xml',
     'likely_drink_recipe', 'drink despite "chocolate" in slug'),
    ('https://liquor.com/recipes/pineapple-upside-down-cake/', 'sitemap-recipes.xml',
     'likely_food_recipe', 'cake even though path is /recipes/ on a drinks site'),
    ('https://simplyrecipes.com/trader-joes-cocktail-shaker-review', 'sitemap-articles.xml',
     'likely_junk', 'product review — "cocktail" is a distractor'),
    ('https://www.thekitchn.com/azalea-cocktail-recipe-review-23778057', 'sitemap.xml',
     'likely_junk', '`-review-` in the slug forces junk even though "recipe" is present'),
    ('https://imbibemagazine.com/drink-of-the-week-mountain-rose-matcha/', 'sitemap.xml',
     'likely_drink_recipe', '`drink-of-the-week-*` is a weekly feature with one named drink'),
    ('https://punchdrink.com/recipes/', 'sitemap.xml',
     'likely_junk', 'bare section index is a navigation hub'),
    ('https://punchdrink.com/spirit-forward/', 'sitemap.xml',
     'likely_drink_article', 'root-level series landing page'),
    ('https://www.foodnetwork.com/videos/negroni-jack-o-lanterns-21804282', 'sitemap_food_10.xml.gz',
     'likely_junk', 'video page with a single-drink slug — `/videos/` means no extractable recipe text'),
    ('https://www.foodnetwork.com/videos/what-actually-is-umami-13997896', 'sitemap_food_8.xml.gz',
     'likely_food_article', 'video page but the slug is an editorial explainer, not a single recipe'),
    ('https://www.diffordsguide.com/beer-wine-spirits/6712/baileys-red-velvet-cupcake', 'https://www.diffordsguide.com/sitemap/gb.xml',
     'likely_drink_article', 'flavored liqueur — `/beer-wine-spirits/` path and products sitemap dominate "cupcake" in the slug'),
    ('https://www.diffordsguide.com/beer-wine-spirits/6614/three-legs-oatmeal-stout', 'https://www.diffordsguide.com/sitemap/gb.xml',
     'likely_drink_article', 'a beer product — `/beer-wine-spirits/` is a catalog, so even slugs that name a single drink resolve to drink_article, not drink_recipe'),
    ('https://www.diffordsguide.com/encyclopedia/393/cocktails/jamies-italian-bar-cocktails-how-to-make', 'https://www.diffordsguide.com/sitemap/gb.xml',
     'likely_drink_article', '`/encyclopedia/` is guide/explainer content — the strong prior is drink_article'),
    ('https://www.diffordsguide.com/encyclopedia/2842/people/lauren-shaw', 'https://www.diffordsguide.com/sitemap/gb.xml',
     'likely_junk', 'bartender bio under `/encyclopedia/*/people/` — author-bio-style page'),
    ('https://imbibemagazine.com/drink-of-the-week-montinore-estate-roulette-pinot-gris/', 'https://imbibemagazine.com/post-sitemap.xml',
     'likely_drink_article', '`drink-of-the-week-*` but the subject is a single wine bottle — a product spotlight, not a mixed drink'),
    ('https://www.thekitchn.com/book-review-local-breads-by-da-53854', 'https://www.thekitchn.com/sitemap-2022-05.xml',
     'likely_food_article', "`-review-` in slug but it's a book review — editorial, not a product/recipe review"),
    ('https://www.diffordsguide.com/bars/w9R86z/crescent-sausage-and-pie', 'https://www.diffordsguide.com/sitemap/bar.xml',
     'likely_junk', 'venue page — `/bars/` path and bar sitemap override the food-sounding slug'),
    ('https://www.diffordsguide.com/cocktails/recipe/228/black-forest-gateau', 'https://www.diffordsguide.com/sitemap/cocktail.xml',
     'likely_drink_recipe', 'cocktail named after a dessert — `/cocktails/recipe/` path is definitive'),
    ('https://www.diffordsguide.com/producer/1178/ramsbury/estate-snapper', 'https://www.diffordsguide.com/sitemap/gb.xml',
     'likely_drink_recipe', 'the final slug is a single cocktail name; `/producer/<id>/<brand>/<slug>` is a mixed path, so the slug wins'),
    ('https://www.diffordsguide.com/producer/1100/hendricks-gin-palace-distillery/story', 'https://www.diffordsguide.com/sitemap/gb.xml',
     'likely_drink_article', 'brand story under a producer path — substantive editorial, not a landing page'),
)

_ROLE = (
    "You are the URL classifier for a cocktail-recipe crawler. From a URL and the "
    "sitemap it came from, you decide what kind of page it most likely points to, "
    "so the crawler fetches recipes and skips everything else. Read the URL like "
    "English: read the slug as a sentence and decide what the page at that URL is "
    "most likely to be, rather than matching keywords in the slug. Choose exactly "
    "one of the categories below."
)

_ANSWER_INSTRUCTIONS = (
    'Reply with a JSON object with one key, "label", whose value is exactly one '
    'category name, for example {"label": "likely_drink_recipe"}.'
)


def render_example(url: str, sitemap: str, answer: str, why: str) -> str:
    return (
        f"<example>\nURL: {url}\nSitemap: {sitemap}\nAnswer: {answer}   ({why})\n</example>"
    )


def build_system_prompt() -> str:
    """The system prompt: role, then each content type in its own XML block
    (categories, rules, examples), then the answer format. One source for the
    category definitions (LABEL_DESCRIPTIONS) so the Decisions API choices and
    this prompt cannot drift apart."""
    categories = "\n".join(f"- {k}: {v}" for k, v in LABEL_DESCRIPTIONS.items())
    rules = "\n".join(f"- {r}" for r in _RULES)
    examples = "\n".join(render_example(*e) for e in _EXAMPLES)
    return (
        f"{_ROLE}\n\n<categories>\n{categories}\n</categories>\n\n"
        f"<rules>\n{rules}\n</rules>\n\n<examples>\n{examples}\n</examples>\n\n"
        f"{_ANSWER_INSTRUCTIONS}"
    )


SYSTEM_PROMPT = build_system_prompt()


def build_user_message(url: str, sitemap_source: str | None) -> str:
    """The per-URL user message. Uniform structure so the model has no latitude."""
    sitemap = sitemap_source if sitemap_source else "(none)"
    return f"URL: {url}\nSitemap: {sitemap}"
