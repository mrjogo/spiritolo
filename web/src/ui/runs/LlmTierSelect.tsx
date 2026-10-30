import { tierKey, useLlmTiers, type LlmTier } from './llmTiers';

interface Props {
  value: LlmTier | null;
  onChange: (tier: LlmTier) => void;
  disabled?: boolean;
}

function optionText(t: LlmTier): string {
  if (!t.available) return `${t.label} (no API key on the server)`;
  const w = t.price?.current_window;
  return w ? `${t.label} · ${w} rates now` : t.label;
}

function optionTitle(t: LlmTier): string | undefined {
  if (!t.price) return undefined;
  const p = t.price;
  const base = `$${p.input_per_mtok} in / $${p.output_per_mtok} out per MTok`;
  const windows = p.windows.map((w) => `${w.label}: ${w.start_utc}–${w.end_utc} UTC`).join('; ');
  return windows ? `${base} (${windows})` : base;
}

// The "LLM tier for this run" picker. Options come from GET /api/ops/llm-tiers
// (the server's price table), so the free-vs-metered labelling can never drift
// from what set_run_llm accepts. A tier whose key the server lacks is shown but
// can't be picked; a run's tier the server no longer lists stays visible as-is.
export function LlmTierSelect({ value, onChange, disabled }: Props) {
  const { tiers, status } = useLlmTiers();
  const listed = value == null || tiers.some((t) => tierKey(t) === tierKey(value));
  const options = listed || value == null ? tiers : [value, ...tiers];
  return (
    <select
      className="modelsel"
      aria-label="LLM tier for this run"
      disabled={disabled || options.length === 0}
      value={value ? tierKey(value) : ''}
      onChange={(e) => {
        const next = tiers.find((t) => tierKey(t) === e.target.value);
        if (next) onChange(next);
      }}
    >
      {value == null && (
        <option value="">{status === 'error' ? "Couldn't load LLM tiers" : 'Loading tiers…'}</option>
      )}
      {options.map((t) => (
        <option
          key={tierKey(t)}
          value={tierKey(t)}
          disabled={!t.available}
          title={optionTitle(t)}
        >
          {optionText(t)}
        </option>
      ))}
    </select>
  );
}
