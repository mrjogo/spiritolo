"""LEGACY: targets the retired Postgres schema via SUPABASE_DB_URL; kept as a
reference for a future scraper -> service page import (see docs/migration.md).

One-time HTML corpus loader: gzip + write-once upload to the object store,
keyed sha256(url), plus the ``pages.corpus_key`` backfill.

The corpus is one of two durable inputs (the other being the ``pages`` row
itself — see supabase/migrations/20260715090000_pages.sql). This package is
operator-run, not a pipeline stage — invoked by hand against the real 16 GiB
cache to populate the corpus bucket.
"""
