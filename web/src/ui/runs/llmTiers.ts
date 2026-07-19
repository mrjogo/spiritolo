// The LLM tiers a run may be pointed at. `provider`/`model` are exactly the
// two values set_run_llm(job_id, provider, model) takes; `label` is the human
// string shown in the picker and confirm modal. Only ollama is free (local);
// every other tier is metered and routes the run through the approval gate.
//
// Cost is NOT modelled here — the estimate is computed server-side by the
// `estimate_run_cents` RPC (the same `_estimate_cents` helper start_run stamps),
// so pricing lives in exactly one place (SQL). See useEstimatedRunCents.
export interface LlmTier {
  provider: string;
  model: string;
  /** Display name in the picker, e.g. "DeepSeek · deepseek-v4-flash — metered". */
  label: string;
  /** Short name for the confirm modal / run header, e.g. "DeepSeek · deepseek-v4-flash". */
  shortLabel: string;
  metered: boolean;
}

export const LLM_TIERS: LlmTier[] = [
  {
    provider: 'ollama',
    model: 'qwen3:14b',
    label: 'Ollama · qwen3:14b — free (local)',
    shortLabel: 'Ollama · qwen3:14b',
    metered: false,
  },
  {
    provider: 'deepseek',
    model: 'deepseek-v4-flash',
    label: 'DeepSeek · deepseek-v4-flash — metered',
    shortLabel: 'DeepSeek · deepseek-v4-flash',
    metered: true,
  },
  {
    provider: 'openai',
    model: 'gpt-5.4-mini',
    label: 'OpenAI · gpt-5.4-mini — metered',
    shortLabel: 'OpenAI · gpt-5.4-mini',
    metered: true,
  },
  {
    provider: 'anthropic',
    model: 'claude-haiku-4-5',
    label: 'Claude · claude-haiku-4-5 — metered',
    shortLabel: 'Claude · claude-haiku-4-5',
    metered: true,
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
