from scraper.src.classify_prompt import (
    LABELS,
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    build_user_message,
)


def test_labels_are_the_known_values():
    assert LABELS == (
        "likely_drink_recipe",
        "likely_food_recipe",
        "likely_drink_article",
        "likely_food_article",
        "likely_cocktail_adjacent",
        "likely_junk",
        "likely_user_generated",
    )


def test_prompt_version_is_a_non_empty_string():
    assert isinstance(PROMPT_VERSION, str) and PROMPT_VERSION


def test_response_schema_constrains_label_to_the_labels_enum():
    assert RESPONSE_SCHEMA["type"] == "object"
    assert RESPONSE_SCHEMA["required"] == ["label"]
    assert set(RESPONSE_SCHEMA["properties"]["label"]["enum"]) == set(LABELS)


def test_system_prompt_mentions_every_label_name():
    documented = set(LABELS) - {"likely_cocktail_adjacent"}
    for lbl in documented:
        assert lbl in SYSTEM_PROMPT


def test_system_prompt_contains_at_least_one_failure_mode_example():
    assert "household-uses-for-vodka" in SYSTEM_PROMPT
    assert "pineapple-upside-down-cake" in SYSTEM_PROMPT


def test_build_user_message_formats_url_and_sitemap():
    msg = build_user_message("https://example.com/recipe/1", "recipes.xml")
    assert "https://example.com/recipe/1" in msg
    assert "recipes.xml" in msg


def test_build_user_message_handles_null_sitemap():
    msg = build_user_message("https://example.com/recipe/1", None)
    assert "https://example.com/recipe/1" in msg
    assert "None" not in msg
