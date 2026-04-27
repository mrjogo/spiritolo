"""Per-recipe parsing logic. The CLI wires this into a Supabase loop."""

from __future__ import annotations

from typing import Any, Iterable

from ingredients.parser import parse


def build_rows_for_recipe(
    raw_ingredients: Iterable[Any], site: str | None = None,
) -> list[dict[str, Any]]:
    """Run the parser over every string in `raw_ingredients`. Non-string
    entries are skipped (their `position` is also skipped, so re-runs land at
    the same indexes).

    Returns a list of insertable dicts ready for IngredientsDatabase.write_recipe_parses.
    """
    rows: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_ingredients):
        if not isinstance(raw, str):
            continue
        result = parse(raw, site=site)
        rows.append({
            "position": idx,
            "raw_text": result.raw_text,
            "amount": result.amount,
            "amount_max": result.amount_max,
            "unit": result.unit,
            "name": result.name,
            "modifier": result.modifier,
            "parse_status": result.parse_status,
            "parser_rule": result.parser_rule,
        })
    return rows
