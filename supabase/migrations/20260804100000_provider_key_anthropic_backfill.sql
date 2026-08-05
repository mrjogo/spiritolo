-- 20260804100000_provider_key_anthropic_backfill.sql
-- Standardize the Anthropic provider key on the vendor name `anthropic`
-- (was split: UI/SQL used `anthropic`, worker used `claude`). Idempotent;
-- no-op when zero rows carry the old spelling.
update public.jobs set llm_provider = 'anthropic' where llm_provider = 'claude';
