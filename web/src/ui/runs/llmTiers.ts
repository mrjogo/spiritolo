import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';

// The LLM tiers a run may be pointed at, served by GET /api/ops/llm-tiers from
// the one Python price table (common.providers.pricing), which also feeds the
// executor's cost cap and the Start-confirm estimate — so the picker, the
// estimate and the cap can't drift. `provider`/`model` are exactly the two
// values set_run_llm(job_id, provider, model) takes; `available` is whether the
// server holds the key to run that provider.

/** A UTC time-of-week window billed at its own rates (DeepSeek peak hours). */
export interface RateWindow {
  label: string;
  /** Days the window starts on, 0 = Monday. */
  weekdays: number[];
  start_utc: string;
  end_utc: string;
  input_per_mtok: number;
  output_per_mtok: number;
}

export interface LlmTierPrice {
  /** USD per million tokens, at the rate in force when the list was fetched. */
  input_per_mtok: number;
  output_per_mtok: number;
  as_of: string | null;
  source: string;
  current_window: string | null;
  windows: RateWindow[];
}

export interface LlmTier {
  provider: string;
  model: string;
  /** Display name in the picker, e.g. "DeepSeek · deepseek-flash — metered". */
  label: string;
  /** Short name for the confirm modal / run header, e.g. "DeepSeek · deepseek-flash". */
  shortLabel: string;
  metered: boolean;
  available: boolean;
  /** Null for a free tier, or a run's tier the server no longer lists. */
  price: LlmTierPrice | null;
}

interface ApiTier {
  provider: string;
  model: string;
  label: string;
  short_label: string;
  metered: boolean;
  available: boolean;
  price: LlmTierPrice | null;
}

// Old run rows carry the former ids.
const PROVIDER_ALIASES: Record<string, string> = { claude: 'anthropic', ollama: 'local' };
const LOCAL_PROVIDERS = ['local'];

function canonical(provider: string): string {
  return PROVIDER_ALIASES[provider] ?? provider;
}

/** A stable key for a tier (used as the <option> value + React key). */
export function tierKey(t: Pick<LlmTier, 'provider' | 'model'>): string {
  return `${canonical(t.provider)}:${t.model}`;
}

export function findTier(
  tiers: readonly LlmTier[],
  provider: string | null | undefined,
  model: string | null | undefined,
): LlmTier | undefined {
  if (!provider || !model) return undefined;
  const key = tierKey({ provider, model });
  return tiers.find((t) => tierKey(t) === key);
}

/** The tier for a run whose provider/model the server no longer lists (an old
 *  run's model): shown as the raw `provider · model`, not selectable. */
export function rawTier(provider: string, model: string): LlmTier {
  const metered = !LOCAL_PROVIDERS.includes(canonical(provider));
  const shortLabel = `${provider} · ${model}`;
  return {
    provider,
    model,
    label: `${shortLabel} — not offered`,
    shortLabel,
    metered,
    available: false,
    price: null,
  };
}

/** The picker's default: the first tier the server can run. */
export function defaultTier(tiers: readonly LlmTier[]): LlmTier | null {
  return tiers.find((t) => t.available) ?? tiers[0] ?? null;
}

export function useLlmTiers(): { tiers: LlmTier[]; status: 'loading' | 'error' | 'loaded' } {
  const q = useQuery({
    queryKey: ['llmTiers'],
    queryFn: async () => (await api<{ tiers: ApiTier[] }>('/api/ops/llm-tiers')).tiers,
    // The rate in force moves with the time of day (peak windows): refetch often.
    staleTime: 5 * 60_000,
  });
  const tiers = (q.data ?? []).map(
    (t): LlmTier => ({
      provider: t.provider,
      model: t.model,
      label: t.label,
      shortLabel: t.short_label,
      metered: t.metered,
      available: t.available,
      price: t.price,
    }),
  );
  return { tiers, status: q.isError ? 'error' : q.isPending ? 'loading' : 'loaded' };
}
