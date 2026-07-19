// The LLM tiers a run may be pointed at. `provider`/`model` are exactly the
// two values set_run_llm(job_id, provider, model) takes; `label` is the human
// string shown in the picker and confirm modal. Only ollama is free (local);
// every other tier is metered and routes the run through the approval gate.
export interface LlmTier {
  provider: string;
  model: string;
  /** Display name in the picker, e.g. "DeepSeek · deepseek-chat — metered". */
  label: string;
  /** Short name for the confirm modal / run header, e.g. "DeepSeek · deepseek-chat". */
  shortLabel: string;
  metered: boolean;
  /** Published price in USD per 1M input / output tokens (2026-07). Drives the
   *  cost estimate; free/local tiers are 0. */
  inputPerMTok: number;
  outputPerMTok: number;
}

export const LLM_TIERS: LlmTier[] = [
  {
    provider: 'ollama',
    model: 'qwen3:14b',
    label: 'Ollama · qwen3:14b — free (local)',
    shortLabel: 'Ollama · qwen3:14b',
    metered: false,
    inputPerMTok: 0,
    outputPerMTok: 0,
  },
  {
    // deepseek-chat = v4-flash non-thinking; $0.14/$0.28 per 1M (api-docs.deepseek.com).
    provider: 'deepseek',
    model: 'deepseek-chat',
    label: 'DeepSeek · deepseek-chat — metered',
    shortLabel: 'DeepSeek · deepseek-chat',
    metered: true,
    inputPerMTok: 0.14,
    outputPerMTok: 0.28,
  },
  {
    // gpt-5-mini last-known list price $0.25/$2.00 per 1M.
    provider: 'openai',
    model: 'gpt-5-mini',
    label: 'OpenAI · gpt-5-mini — metered',
    shortLabel: 'OpenAI · gpt-5-mini',
    metered: true,
    inputPerMTok: 0.25,
    outputPerMTok: 2.0,
  },
  {
    // claude-haiku-4-5 $1.00/$5.00 per 1M.
    provider: 'anthropic',
    model: 'claude-haiku-4-5',
    label: 'Claude · claude-haiku-4-5 — metered',
    shortLabel: 'Claude · claude-haiku-4-5',
    metered: true,
    inputPerMTok: 1.0,
    outputPerMTok: 5.0,
  },
];

export const DEFAULT_LLM_TIER = LLM_TIERS[0];

/** A stable key for a tier (used as the <option> value + React key). */
export function tierKey(t: Pick<LlmTier, 'provider' | 'model'>): string {
  return `${t.provider}:${t.model}`;
}

export function findTier(provider: string | null | undefined, model: string | null | undefined): LlmTier | undefined {
  if (!provider || !model) return undefined;
  return LLM_TIERS.find((t) => t.provider === provider && t.model === model);
}

// Per-item token estimate for a hosted LLM call in the pipeline. This MUST stay
// in sync with the server's `_estimate_cents` (supabase/migrations/…_run_rpcs.sql)
// so the draft-side estimate agrees with what start_run stamps — no jump at
// confirm. Deliberately assumes every item reaches the LLM tier (the
// deterministic tier resolves most first), so it over-estimates.
const INPUT_TOKENS_PER_ITEM = 1200;
const OUTPUT_TOKENS_PER_ITEM = 200;

/** Estimated cents for running `taskCount` tasks on `tier`; null when the count
 *  isn't known yet. Token-based against the tier's published $/1M rates; free
 *  (ollama) tiers price to 0. */
export function estimateRunCents(tier: LlmTier, taskCount: number | null | undefined): number | null {
  if (taskCount == null) return null;
  // per-item cents = (in_tokens * in_$perM + out_tokens * out_$perM) / 1e4
  const perItemCents =
    (INPUT_TOKENS_PER_ITEM * tier.inputPerMTok + OUTPUT_TOKENS_PER_ITEM * tier.outputPerMTok) / 10000;
  return Math.round(taskCount * perItemCents);
}
