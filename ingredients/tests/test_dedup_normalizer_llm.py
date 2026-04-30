"""Phase-2 LLM normalizer orchestrator. Tested with a stub provider that
yields scripted ProviderResult objects; the real Claude/Ollama providers
are exercised in mapping/'s tests already and don't need re-testing here."""

from dataclasses import dataclass
from typing import Iterator

from ingredients.dedup.normalizer_llm import run_phase2
from ingredients.dedup.version import NORMALIZER_VERSION
from ingredients.mapping.llm_provider import ProviderResult


@dataclass
class StubProvider:
    scripted: Iterator[str]
    model_id: str = "stub-1.0"

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        return ProviderResult(raw_text=next(self.scripted), model_id=self.model_id)


def test_phase2_chose_writes_canonical(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version, normalized_at)
        values (4001, 'http://x/a', 'punch', 'Some Wild House Drink',
                '{}'::jsonb, now(),
                null, 'pending_llm', %s, now())
        on conflict (source_url) do nothing
    """, (NORMALIZER_VERSION,))
    provider = StubProvider(iter(['{"action":"chose","canonical_name":"old fashioned"}']))
    counts = run_phase2(db_conn, provider=provider)
    assert counts["chose"] == 1
    row = db_conn.execute(
        "select canonical_name, canonical_name_source from recipes where id = 4001"
    ).fetchone()
    assert row == ("old fashioned", "llm")


def test_phase2_propose_adds_alias(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version, normalized_at)
        values (4002, 'http://x/b', 'punch', 'Bee''s Knees',
                '{}'::jsonb, now(),
                null, 'pending_llm', %s, now())
        on conflict (source_url) do nothing
    """, (NORMALIZER_VERSION,))
    provider = StubProvider(iter(['{"action":"propose","canonical_name":"bees knees"}']))
    counts = run_phase2(db_conn, provider=provider)
    assert counts["propose"] == 1
    row = db_conn.execute(
        "select canonical_name, canonical_name_source from recipes where id = 4002"
    ).fetchone()
    assert row == ("bees knees", "llm")
    alias = db_conn.execute(
        "select source from cocktail_aliases where alias = %s and canonical_name = 'bees knees'",
        ("bee s knees",),  # post-normalize_cocktail_name form (apostrophe → space, then collapsed)
    ).fetchone()
    assert alias is not None
    assert alias[0] == "llm"


def test_phase2_stops_after_interrupt_request(dedup_fixture, db_conn):
    """First Ctrl-C lets the in-flight LLM call finish + write its result,
    then the loop exits before processing remaining names."""
    import os
    import signal

    conn, _ = dedup_fixture
    for rid, source in (
        (4101, 'http://x/i1'),
        (4102, 'http://x/i2'),
        (4103, 'http://x/i3'),
    ):
        db_conn.execute("""
            insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                                 canonical_name, canonical_name_source, normalizer_version, normalized_at)
            values (%s, %s, 'punch', 'Some Drink',
                    '{}'::jsonb, now(),
                    null, 'pending_llm', %s, now())
            on conflict (source_url) do nothing
        """, (rid, source, NORMALIZER_VERSION))

    class InterruptingProvider:
        def __init__(self) -> None:
            self.calls = 0
            self.model_id = "stub-1.0"
        def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
            self.calls += 1
            if self.calls == 1:
                os.kill(os.getpid(), signal.SIGINT)
            return ProviderResult(
                raw_text='{"action":"abstain"}', model_id=self.model_id,
            )

    provider = InterruptingProvider()
    run_phase2(db_conn, provider=provider)
    assert provider.calls == 1, (
        f"expected loop to break after first interrupt; got {provider.calls} calls"
    )


def test_phase2_abstain(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version, normalized_at)
        values (4003, 'http://x/c', 'punch', '5 Cocktail Recipes For Summer',
                '{}'::jsonb, now(),
                null, 'pending_llm', %s, now())
        on conflict (source_url) do nothing
    """, (NORMALIZER_VERSION,))
    provider = StubProvider(iter(['{"action":"abstain"}']))
    counts = run_phase2(db_conn, provider=provider)
    assert counts["abstain"] == 1
    row = db_conn.execute(
        "select canonical_name, canonical_name_source from recipes where id = 4003"
    ).fetchone()
    assert row == (None, "abstain")
