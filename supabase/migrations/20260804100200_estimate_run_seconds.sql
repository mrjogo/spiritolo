-- 20260804100200_estimate_run_seconds.sql

-- Average wall-clock seconds-per-item per (stage, provider, model), over
-- SUCCEEDED runs in a rolling 90-day window. Ratio of sums (total elapsed ÷
-- total items) — assumption-free, robust to a few odd runs. Item count comes
-- from job_items (jobs has no task_count column). Powers estimate_run_seconds.
create or replace view public.job_duration_avg as
select j.stage, j.llm_provider, j.llm_model,
       sum(extract(epoch from j.finished_at - j.started_at))
         / nullif(sum(ic.n), 0)             as avg_seconds_per_item,
       count(*)                              as run_count,
       sum(ic.n)                             as item_count
from public.jobs j
join lateral (select count(*)::numeric as n from public.job_items ji
              where ji.job_id = j.id) ic on true
where j.state = 'succeeded'
  and j.started_at is not null and j.finished_at is not null
  and j.finished_at > now() - interval '90 days'
  and ic.n > 0
group by j.stage, j.llm_provider, j.llm_model;

-- Rough run-duration estimate: seconds-per-item (from history, else a seed
-- constant) × item count. Hierarchical backoff widens the sample when a precise
-- bucket is thin: (stage,provider,model) → (stage,provider) → (stage) → seed.
-- Returns {seconds, source}; the UI snaps `seconds` to a coarse bucket. Seeds
-- are post-`think:false` measurements, overridden once history accrues.
create or replace function public.estimate_run_seconds(
  p_stage text, p_provider text, p_model text, p_items int
) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
declare v_spi numeric; v_src text;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  select avg_seconds_per_item into v_spi from public.job_duration_avg
   where stage = p_stage
     and llm_provider is not distinct from p_provider
     and llm_model    is not distinct from p_model
     and run_count >= 3;
  if v_spi is not null then v_src := 'model'; end if;

  if v_spi is null then
    select sum(avg_seconds_per_item * item_count) / nullif(sum(item_count), 0)
      into v_spi from public.job_duration_avg
     where stage = p_stage and llm_provider is not distinct from p_provider;
    if v_spi is not null then v_src := 'provider'; end if;
  end if;

  if v_spi is null then
    select sum(avg_seconds_per_item * item_count) / nullif(sum(item_count), 0)
      into v_spi from public.job_duration_avg where stage = p_stage;
    if v_spi is not null then v_src := 'stage'; end if;
  end if;

  if v_spi is null then
    v_spi := case
      when p_stage = 'extract-recipe' then 4.0
      when p_provider = 'ollama' and p_model = 'qwen3:8b' then 0.7
      when p_provider = 'ollama' then 1.5
      when p_provider in ('deepseek', 'openai', 'anthropic') then 0.5
      else 0.3
    end;
    v_src := 'seed';
  end if;

  return jsonb_build_object(
    'seconds', round((coalesce(p_items, 0) * v_spi)::numeric, 1),
    'source', v_src
  );
end;
$$;
