"""Pytest configuration for spiritolo-common tests."""
import os

# Defensive: see ingredients/tests/conftest.py for the rationale. Any
# test that accidentally falls back to SUPABASE_DB_URL must fail loudly
# instead of silently wiping the dev DB.
os.environ["SUPABASE_DB_URL"] = (
    "postgresql://invalid:invalid@127.0.0.1:1/SUPABASE_DB_URL_must_not_be_used_in_tests"
)
