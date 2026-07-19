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
    model: 'deepseek-chat',
    label: 'DeepSeek · deepseek-chat — metered',
    shortLabel: 'DeepSeek · deepseek-chat',
    metered: true,
  },
  {
    provider: 'openai',
    model: 'gpt-5-mini',
    label: 'OpenAI · gpt-5-mini — metered',
    shortLabel: 'OpenAI · gpt-5-mini',
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

// A deliberately naive per-item cost heuristic — the pre-start stand-in for the
// worker-computed estimate. Free tiers cost nothing; metered tiers use a flat
// cent per task. This intentionally MATCHES the server's `_estimate_cents`
// (1¢/pending item, stamped onto `cost_estimate_cents` by start_run) so the
// draft-side estimate agrees with what Start will charge — no jump at confirm.
const METERED_CENTS_PER_ITEM = 1;

/** Estimated cents for running `taskCount` tasks on `tier`; null when the
 *  count isn't known yet. Free tiers return 0. */
export function estimateRunCents(tier: LlmTier, taskCount: number | null | undefined): number | null {
  if (taskCount == null) return null;
  if (!tier.metered) return 0;
  return Math.round(taskCount * METERED_CENTS_PER_ITEM);
}
