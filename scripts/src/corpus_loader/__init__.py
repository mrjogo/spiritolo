"""One-time HTML corpus loader (WS-B20): gzip + write-once upload to R2,
keyed sha256(url), plus the ``pages.r2_key`` backfill.

The corpus is one of the two clean-slate inputs the v2.1 rebuild preserves
(the other being the ``pages`` row itself — see supabase/migrations/
20260715090000_pages.sql). This package is operator-run, not a pipeline
stage: see docs/redesign.md WS-B20 and docs/upload.md-style runbooks for how
it's invoked against the real 16 GiB cache.
"""
