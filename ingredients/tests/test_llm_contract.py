"""The LLM contract, end to end: stage prompt -> ProviderChain -> a model -> stage.

Every other stage test drives a fake chain that hands back ``{id: answer}``
directly, and ``FakeProvider`` always speaks the packed envelope, so neither can
catch a prompt that never tells a real model about the envelope (the bug that
kept every Zone-2 LLM tier from resolving anything). ``_RealisticProvider``
behaves the way a real model does instead: it answers in the
``{"results": [{"id", "answer"}]}`` envelope only when its system prompt
describes that envelope, otherwise it replies with one bare answer object; it
can only read an item whose ``input`` is a JSON object; and it shapes each
answer to the ``response_schema`` it was given. Each LLM stage below runs
through a real ``ProviderChain`` over it and must resolve every item.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from common.llm.provider import ProviderResult

from ingredients.pipeline.corpus import CorpusMiss
from ingredients.pipeline.stages import extract
from ingredients.pipeline.stages.combine import combine_stage_fn
from ingredients.pipeline.stages.connect import connect_stage_fn
from ingredients.pipeline.stages.extract import extract_stage_fn
from ingredients.pipeline.stages.map import map_stage_fn
from ingredients.worker.providers import ProviderChain


@dataclass
class _RealisticProvider:
    """A scripted model: ``answer_for(input)`` is what it would say per item."""

    answer_for: Callable[[dict[str, Any]], dict[str, Any]]
    cost_per_call: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)
    model_id: str = "realistic"

    def resolve(
        self, *, system_prompt: str, user_prompt: str,
        response_schema: dict[str, Any] | None = None,
    ) -> ProviderResult:
        self.calls.append({"system_prompt": system_prompt, "response_schema": response_schema})
        items = json.loads(user_prompt)["items"]
        answers = [
            (it["id"], self._shaped(self.answer_for(it["input"]), response_schema))
            for it in items
            if isinstance(it.get("input"), dict)  # a Python repr is unreadable
        ]
        if '"results"' not in system_prompt:
            # Nobody asked for the envelope: answer the first item, bare.
            return ProviderResult(json.dumps(answers[0][1] if answers else {}), self.model_id)
        rows = [{"id": i, "answer": a} for i, a in answers]
        return ProviderResult(json.dumps({"results": rows}), self.model_id)

    @staticmethod
    def _shaped(answer: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any]:
        """Fill the keys a strict schema requires (as structured output would)."""
        if schema is None:
            return answer
        item_schema = schema["properties"]["results"]["items"]["properties"]["answer"]
        assert set(answer) <= set(item_schema["properties"]), answer
        defaults = {"array": [], "boolean": False}
        out = dict(answer)
        for key in item_schema["required"]:
            if key not in out:
                kind = item_schema["properties"][key].get("type")
                out[key] = defaults.get(kind if isinstance(kind, str) else "null")
        return out


def _chain(provider: _RealisticProvider, pack_size: int = 10) -> ProviderChain:
    return ProviderChain(tiers=[("ollama", provider)], pack_size=pack_size)


def _job():
    return {"id": None, "payload": {}}


def _node(conn, slug, name, *, status="live"):
    return conn.execute(
        "insert into taxonomy_nodes (slug, display_name, status) values (?, ?, ?) returning id",
        (slug, name, status),
    ).fetchone()[0]


def test_map_stage_resolves_through_the_envelope(db_conn):
    conn = db_conn
    _node(conn, "amaro", "Amaro")
    _node(conn, "gin", "Gin")
    rid = conn.execute(
        "insert into recipes (source_url, site, source) values ('https://ex/1', 'ex', '{}') "
        "returning id"
    ).fetchone()[0]
    for pos, name in enumerate(["Fancy Amaro", "Bathtub Gin"]):
        conn.execute(
            "insert into recipe_ingredients (recipe_id, position, name, raw_text) "
            "values (?, ?, ?, ?)",
            (rid, pos, name, name),
        )

    def answer(inp):
        return {"action": "chose_slug", "slug": inp["candidates"][0]["slug"]}

    provider = _RealisticProvider(answer)
    map_stage_fn(_job(), conn, _chain(provider))

    assert provider.calls, "the LLM tier was never reached"
    rows = dict(conn.execute(
        "select normalized_name, method from ingredient_resolutions"
    ).fetchall())
    assert rows == {"fancy amaro": "llm", "bathtub gin": "llm"}


class _Corpus:
    def __init__(self, mapping):
        self._m = {k: gzip.compress(v.encode()) for k, v in mapping.items()}

    def read_html(self, key):
        if key not in self._m:
            raise CorpusMiss(key)
        return gzip.decompress(self._m[key]).decode()


def test_extract_stage_resolves_through_the_envelope(db_conn):
    conn = db_conn
    conn.execute(
        "insert into pages (url, site, corpus_key, content_type) "
        "values ('https://ex/d', 'ex', 'k1', 'likely_drink_recipe')"
    )
    extract.set_corpus_reader(_Corpus({"k1": "<h1>Daiquiri</h1><li>2 oz rum</li>"}))
    try:
        def answer(inp):
            return {"found": True, "name": "Daiquiri", "recipeIngredient": ["2 oz rum"],
                    "recipeInstructions": ["Shake."]}

        provider = _RealisticProvider(answer)
        counts = extract_stage_fn(_job(), conn, _chain(provider, pack_size=1))
    finally:
        extract.set_corpus_reader(None)

    assert counts["extracted"] == 1
    assert conn.execute("select title from recipes").fetchone()[0] == "Daiquiri"


def test_combine_stage_resolves_through_the_envelope(db_conn):
    conn = db_conn
    _node(conn, "lime-juice", "Lime Juice")
    dup = _node(conn, "juice-of-a-lime", "juice of a lime", status="provisional")
    other = _node(conn, "lime-cordial", "lime cordial", status="provisional")

    def answer(inp):
        if inp["slug"] == "juice-of-a-lime":
            return {"action": "merge", "survivor_slug": "lime-juice"}
        return {"action": "distinct"}

    counts = combine_stage_fn(_job(), conn, _chain(_RealisticProvider(answer)))

    assert counts == {"merged": 1, "distinct": 1, "pending": 0}
    remaining = {r[0] for r in conn.execute("select id from taxonomy_nodes").fetchall()}
    assert dup not in remaining and other in remaining


def test_connect_stage_resolves_through_the_envelope(db_conn):
    conn = db_conn
    _node(conn, "citrus", "Citrus")
    _node(conn, "lime", "Lime")
    a = _node(conn, "lime-juice", "lime juice", status="provisional")
    b = _node(conn, "lime-wheel", "lime wheel", status="provisional")

    def answer(inp):
        return {"action": "place", "node_kind": None, "parent_slugs": ["lime"],
                "is_cluster_node": False}

    counts = connect_stage_fn(_job(), conn, _chain(_RealisticProvider(answer)))

    assert counts == {"connected": 2, "pending": 0}
    statuses = {r[0] for r in conn.execute(
        "select status from taxonomy_nodes where id in (?, ?)", (a, b)
    ).fetchall()}
    assert statuses == {"live"}


def test_realistic_provider_without_envelope_instructions_resolves_nothing():
    """The regression this file guards: a prompt that doesn't describe the
    envelope gets a bare object back, which decodes to nothing."""
    from common.providers.packing import Item

    provider = _RealisticProvider(lambda inp: {"action": "distinct"})
    chain = _chain(provider)
    # Bypass the chain's preamble to show what a stage prompt alone produced.
    raw = provider.resolve(
        system_prompt="Reply with a single JSON object.",
        user_prompt=json.dumps({"items": [{"id": "1", "input": {"x": 1}}]}),
    ).raw_text
    from common.providers.packing import decode_response

    assert decode_response(raw) == {}
    # Through the chain, the same item resolves.
    assert chain.resolve([Item("1", {"x": 1})]).resolved == {"1": {"action": "distinct"}}
