"""Phase 2 orchestrator. We exercise it with a stub provider so the test
covers cascade -> auto-create / queue / abstain branches without going
out to the network."""

from __future__ import annotations

import psycopg

from ingredients.mapping.db import write_pending
from common.llm.provider import ProviderResult
from ingredients.mapping.llm_resolver import run_phase2
from ingredients.mapping.mapper import MAPPER_VERSION


class StubProvider:
    """Returns a configurable response per (normalized_name, hit count)."""
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []
        self.model_id = "stub-1"

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        # Find which name this prompt is about by inspecting user_prompt.
        for name in self.responses:
            if f'"name": "{name}"' in user_prompt:
                self.calls.append((name, self.responses[name]))
                return ProviderResult(raw_text=self.responses[name], model_id=self.model_id)
        raise AssertionError(f"no stub response configured for prompt: {user_prompt[:200]}")


def _seed_pending(conn: psycopg.Connection, names: list[str]) -> None:
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld, fetched_at) "
        "values ('punch', 'https://example.com/x', '{}'::jsonb, now()) returning id"
    ).fetchone()[0]
    for pos, name in enumerate(names):
        conn.execute(
            "insert into recipe_ingredients "
            "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version) "
            "values (%s,%s,%s,%s,'parsed','qty_unit','v1')",
            (rid, pos, f"1 oz {name}", name),
        )
    conn.commit()
    for name in names:
        write_pending(conn, normalized_name=name.lower().strip(), mapper_version=MAPPER_VERSION)


def test_resolver_handles_chose_action(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_pending(conn, ["fancy gin variant"])
    provider = StubProvider({
        "fancy gin variant": '{"action": "chose", "node_id": ' + str(ids["gin"]) + '}',
    })
    summary = run_phase2(conn, provider=provider)
    row = conn.execute(
        "select taxonomy_node_id, mapper_source from recipe_ingredients "
        "where lower(trim(name)) = 'fancy gin variant'"
    ).fetchone()
    assert row == (ids["gin"], "llm")
    assert summary == {"chose": 1}


def test_resolver_auto_creates_brand_with_existing_parent(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_pending(conn, ["bombay sapphire"])
    provider = StubProvider({
        "bombay sapphire": (
            '{"action": "propose_brand", "slug": "bombay_sapphire", '
            '"display_name": "Bombay Sapphire", "parent_slug": "london_dry_gin", '
            '"node_kind": "brand"}'
        ),
    })
    summary = run_phase2(conn, provider=provider)
    new_node = conn.execute(
        "select id, node_kind from taxonomy_nodes where slug = 'bombay_sapphire'"
    ).fetchone()
    assert new_node is not None
    new_id, new_node_kind = new_node
    assert new_node_kind == "brand"

    # Edge to parent.
    parent_id_row = conn.execute(
        "select parent_id from taxonomy_edges where child_id = %s", (new_id,),
    ).fetchone()
    assert parent_id_row[0] == ids["london_dry_gin"]

    # Provenance row written.
    prov = conn.execute(
        "select source, model_id, raw_string from taxonomy_provenance where node_id = %s", (new_id,),
    ).fetchone()
    assert prov == ("llm-mapper", "stub-1", "bombay sapphire")

    # Recipe row got mapped.
    row = conn.execute(
        "select taxonomy_node_id, mapper_source from recipe_ingredients "
        "where lower(trim(name)) = 'bombay sapphire'"
    ).fetchone()
    assert row == (new_id, "llm")
    assert summary == {"propose_brand": 1}


def test_resolver_abstains_when_proposed_parent_missing(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    _seed_pending(conn, ["mystery liqueur"])
    provider = StubProvider({
        "mystery liqueur": (
            '{"action": "propose_brand", "slug": "mystery", "display_name": "Mystery", '
            '"parent_slug": "does_not_exist", "node_kind": "brand"}'
        ),
    })
    summary = run_phase2(conn, provider=provider)
    row = conn.execute(
        "select taxonomy_node_id, mapper_source from recipe_ingredients "
        "where lower(trim(name)) = 'mystery liqueur'"
    ).fetchone()
    assert row == (None, "abstain")
    assert summary == {"abstain": 1}


def test_resolver_enqueues_form_proposal_and_marks_pending(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_pending(conn, ["lemon zest"])
    provider = StubProvider({
        "lemon zest": (
            '{"action": "propose_form", "slug": "lemon_zest", '
            '"display_name": "Lemon Zest", "parent_slug": "lemon"}'
        ),
    })
    summary = run_phase2(conn, provider=provider)
    # Row stays pending_llm — form proposals require human review before mapping.
    row = conn.execute(
        "select taxonomy_node_id, mapper_source from recipe_ingredients "
        "where lower(trim(name)) = 'lemon zest'"
    ).fetchone()
    assert row == (None, "pending_llm")

    proposals = conn.execute(
        "select raw_string, proposed_slug, proposed_parent_id, status from taxonomy_proposals"
    ).fetchall()
    assert proposals == [("lemon zest", "lemon_zest", ids["lemon"], "pending")]
    assert summary == {"propose_form": 1}


def test_resolver_handles_explicit_abstain(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    _seed_pending(conn, ["truly unknown"])
    provider = StubProvider({"truly unknown": '{"action": "abstain"}'})
    summary = run_phase2(conn, provider=provider)
    row = conn.execute(
        "select taxonomy_node_id, mapper_source from recipe_ingredients "
        "where lower(trim(name)) = 'truly unknown'"
    ).fetchone()
    assert row == (None, "abstain")
    assert summary == {"abstain": 1}


def test_resolver_respects_limit(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_pending(conn, ["fancy gin variant", "another thing"])
    provider = StubProvider({
        "fancy gin variant": '{"action": "chose", "node_id": ' + str(ids["gin"]) + '}',
        "another thing":     '{"action": "abstain"}',
    })
    summary = run_phase2(conn, provider=provider, limit=1)
    assert sum(summary.values()) == 1
    # The remaining one is still pending_llm.
    pending = conn.execute(
        "select count(*) from recipe_ingredients where mapper_source = 'pending_llm'"
    ).fetchone()[0]
    assert pending == 1


def test_resolver_stops_after_interrupt_request(fixture_taxonomy):
    """First Ctrl-C lets the in-flight LLM call finish + write its result,
    then the loop exits before processing remaining names."""
    import os
    import signal
    from common.llm.provider import ProviderResult

    conn, ids = fixture_taxonomy
    _seed_pending(conn, ["fancy gin variant", "another thing", "third name"])

    class InterruptingProvider:
        def __init__(self) -> None:
            self.calls = 0
            self.model_id = "stub-1"
        def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
            self.calls += 1
            if self.calls == 1:
                # Simulate first Ctrl-C arriving during this LLM call.
                os.kill(os.getpid(), signal.SIGINT)
            return ProviderResult(
                raw_text='{"action": "abstain"}', model_id=self.model_id,
            )

    provider = InterruptingProvider()
    run_phase2(conn, provider=provider)
    # The first call's result must have been written; subsequent names skipped.
    assert provider.calls == 1, (
        f"expected loop to break after first interrupt; got {provider.calls} calls"
    )


def test_brand_auto_create_rolls_back_if_resolution_fails(fixture_taxonomy, monkeypatch):
    """If the rows-update step fails after the node-create step, the
    new node + edge + provenance must roll back so we don't leak an
    orphan taxonomy node."""
    from ingredients.mapping.db import write_pending
    from ingredients.mapping import llm_resolver

    conn, _ = fixture_taxonomy
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld, fetched_at) "
        "values ('punch', 'https://example.com/atomic', '{}'::jsonb, now()) returning id"
    ).fetchone()[0]
    conn.execute(
        "insert into recipe_ingredients "
        "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version) "
        "values (%s, 0, '1 oz beefeater', 'beefeater', 'parsed', 'qty_unit', 'v1')",
        (rid,),
    )
    conn.commit()
    write_pending(conn, normalized_name="beefeater", mapper_version="v1")

    provider = StubProvider({
        "beefeater": (
            '{"action": "propose_brand", "slug": "beefeater", '
            '"display_name": "Beefeater", "parent_slug": "london_dry_gin", '
            '"node_kind": "brand"}'
        ),
    })

    # Force write_resolution to raise after _create_brand_node has run.
    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash before resolution commit")
    monkeypatch.setattr(llm_resolver, "write_resolution", boom)

    import pytest
    with pytest.raises(RuntimeError):
        llm_resolver.run_phase2(conn, provider=provider)

    # The node must NOT exist if atomicity is preserved.
    row = conn.execute(
        "select id from taxonomy_nodes where slug = 'beefeater'"
    ).fetchone()
    assert row is None, "leaked taxonomy node from non-atomic auto-create"


def test_resolver_retries_on_provider_failure_then_continues_loop(fixture_taxonomy, monkeypatch):
    """A transient provider failure on one row must NOT abort the whole
    queue. The failed row stays at pending_llm; subsequent rows process."""
    from ingredients.mapping.db import write_pending
    from ingredients.mapping import llm_resolver

    conn, ids = fixture_taxonomy
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld, fetched_at) "
        "values ('punch', 'https://example.com/retry', '{}'::jsonb, now()) returning id"
    ).fetchone()[0]
    for pos, name in enumerate(["broken thing", "fancy gin variant"]):
        conn.execute(
            "insert into recipe_ingredients "
            "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version) "
            "values (%s,%s,%s,%s,'parsed','qty_unit','v1')",
            (rid, pos, f"1 oz {name}", name),
        )
    conn.commit()
    write_pending(conn, normalized_name="broken thing", mapper_version="v1")
    write_pending(conn, normalized_name="fancy gin variant", mapper_version="v1")

    # Provider raises on "broken thing", succeeds on "fancy gin variant".
    class FlakyProvider:
        model_id = "stub-flaky"
        def resolve(self, *, system_prompt, user_prompt):
            if '"name": "broken thing"' in user_prompt:
                raise RuntimeError("simulated transient failure")
            return ProviderResult(
                raw_text='{"action": "chose", "node_id": ' + str(ids["gin"]) + '}',
                model_id="stub-flaky",
            )

    # Skip the actual sleeping during the test.
    import common.llm.retry as _retry_mod
    monkeypatch.setattr(_retry_mod.time, "sleep", lambda _s: None)

    summary = llm_resolver.run_phase2(conn, provider=FlakyProvider())

    # Broken row stayed at pending_llm; gin variant got resolved.
    row1 = conn.execute(
        "select mapper_source from recipe_ingredients where lower(trim(name)) = 'broken thing'"
    ).fetchone()
    row2 = conn.execute(
        "select mapper_source, taxonomy_node_id from recipe_ingredients "
        "where lower(trim(name)) = 'fancy gin variant'"
    ).fetchone()
    assert row1[0] == "pending_llm"
    assert row2 == ("llm", ids["gin"])
    assert summary.get("chose") == 1
    assert summary.get("error", 0) == 1
