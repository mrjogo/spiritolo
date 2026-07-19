import { LLM_TIERS, tierKey, type LlmTier } from './llmTiers';

interface Props {
  value: LlmTier;
  onChange: (tier: LlmTier) => void;
  disabled?: boolean;
}

// The "LLM tier for this run" picker. Options come straight from LLM_TIERS so
// the free-vs-metered labelling can never drift from what set_run_llm accepts.
export function LlmTierSelect({ value, onChange, disabled }: Props) {
  return (
    <select
      className="modelsel"
      aria-label="LLM tier for this run"
      disabled={disabled}
      value={tierKey(value)}
      onChange={(e) => {
        const next = LLM_TIERS.find((t) => tierKey(t) === e.target.value);
        if (next) onChange(next);
      }}
    >
      {LLM_TIERS.map((t) => (
        <option key={tierKey(t)} value={tierKey(t)}>
          {t.label}
        </option>
      ))}
    </select>
  );
}
