from scraper.classify_prompt import (
    LABELS,
    MODEL_LABELS,
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
        "likely_unstructured_drink_recipe",
        "likely_junk",
        "likely_user_generated",
    )


def test_prompt_version_is_a_non_empty_string():
    assert isinstance(PROMPT_VERSION, str) and PROMPT_VERSION


def test_response_schema_constrains_label_to_the_model_labels():
    assert RESPONSE_SCHEMA["type"] == "object"
    assert RESPONSE_SCHEMA["required"] == ["label"]
    assert RESPONSE_SCHEMA["additionalProperties"] is False
    assert RESPONSE_SCHEMA["properties"]["label"]["enum"] == list(MODEL_LABELS)


def test_model_labels_are_the_operator_labels_minus_the_rule_only_ones():
    assert set(LABELS) - set(MODEL_LABELS) == {
        "likely_cocktail_adjacent", "likely_unstructured_drink_recipe",
    }


def test_system_prompt_documents_exactly_the_model_labels():
    import re

    listed = re.findall(r"^- (likely_[a-z_]+):", SYSTEM_PROMPT, flags=re.MULTILINE)
    assert listed == list(MODEL_LABELS)
    # No hardcoded count that can drift from the list again.
    assert not re.search(r"\b(six|seven|eight)\b", SYSTEM_PROMPT.split("Rules:")[0])


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


def test_classify_url_sends_the_response_schema():
    from common.llm.provider import ProviderResult
    from scraper.classify_client import classify_url

    seen = {}

    class _Provider:
        model_id = "m"

        def resolve(self, *, system_prompt, user_prompt, response_schema=None):
            seen["schema"] = response_schema
            return ProviderResult('{"label": "likely_junk"}', "m")

    result = classify_url(url="https://x/y", sitemap_source=None, provider=_Provider())
    assert result.label == "likely_junk"
    assert seen["schema"] == RESPONSE_SCHEMA
