"""Tests for pure helpers in common.supabase_client.

These don't open a Postgres connection; they exercise the URL-shape
heuristics the DB wrappers use to warn when SUPABASE_DB_URL looks like
the Supabase pooler.
"""

from __future__ import annotations

import logging

from common.supabase_client import (
    looks_like_supabase_pooler,
    warn_if_staging_url,
)


class TestLooksLikeSupabasePooler:
    def test_session_mode_pooler_matches(self):
        url = "postgresql://postgres.abc:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
        assert looks_like_supabase_pooler(url)

    def test_transaction_mode_pooler_matches(self):
        url = "postgresql://postgres.abc:pw@aws-0-eu-west-2.pooler.supabase.com:6543/postgres"
        assert looks_like_supabase_pooler(url)

    def test_local_supabase_does_not_match(self):
        url = "postgresql://postgres:postgres@host.docker.internal:54322/postgres"
        assert not looks_like_supabase_pooler(url)

    def test_test_db_does_not_match(self):
        url = "postgresql://postgres:postgres@host.docker.internal:54322/spiritolo_test"
        assert not looks_like_supabase_pooler(url)

    def test_direct_supabase_db_does_not_match(self):
        # The IPv6-only direct connection that backup-supabase.sh refuses.
        # Not a pooler, so the warning shouldn't fire even if you somehow
        # got one of these.
        url = "postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres"
        assert not looks_like_supabase_pooler(url)

    def test_unparseable_url_returns_false(self):
        # `urlparse` is permissive, so the only realistic failure mode is
        # an empty / non-URL string. Confirm we don't blow up.
        assert not looks_like_supabase_pooler("")
        assert not looks_like_supabase_pooler("not a url at all")


class TestWarnIfStagingUrl:
    def test_warns_on_pooler(self, caplog):
        url = "postgresql://postgres.abc:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
        with caplog.at_level(logging.WARNING, logger="common"):
            warn_if_staging_url(url)
        msgs = [r.message for r in caplog.records]
        assert any("pooler" in m.lower() for m in msgs), msgs
        assert any("upload.md" in m for m in msgs), msgs

    def test_silent_on_local(self, caplog):
        url = "postgresql://postgres:postgres@host.docker.internal:54322/postgres"
        with caplog.at_level(logging.WARNING, logger="common"):
            warn_if_staging_url(url)
        assert caplog.records == []
