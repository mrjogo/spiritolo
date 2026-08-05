import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StartConfirmModal } from './StartConfirmModal';
import type { RunHeader } from './useRun';
import type { LlmTier } from './llmTiers';

// StartConfirmModal -> useEstimate/useEstimateSeconds -> supabase.ts, which
// throws at import if the Vite env vars are absent. The modal never touches
// supabase at runtime once the hooks are mocked, so a stub is enough — matches
// how the other /ops tests mock it.
vi.mock('../../supabase', () => ({ supabase: {} }));

vi.mock('./useEstimate', () => ({
  useEstimatedRunCents: () => 25,
}));

const estimateSeconds = vi.fn();
vi.mock('./useEstimateSeconds', () => ({
  useEstimatedRunSeconds: (...args: unknown[]) => estimateSeconds(...args),
}));

const tier: LlmTier = {
  provider: 'ollama',
  model: 'qwen3:14b',
  label: 'Ollama · qwen3:14b — free (local)',
  shortLabel: 'Ollama · qwen3:14b',
  metered: false,
};

function run(overrides: Partial<RunHeader> = {}): RunHeader {
  return {
    id: 7,
    stage: 'map-ingredient',
    state: 'draft',
    llm_provider: 'ollama',
    llm_model: 'qwen3:14b',
    task_count: 100,
    flagged_count: 0,
    never_run_count: 100,
    failed_count: 0,
    cost_estimate_cents: null,
    max_cost_cents: null,
    created_at: null,
    created_by: null,
    cost_actual_cents: null,
    error_code: null,
    error_detail: null,
    worker_id: null,
    last_heartbeat: null,
    started_at: null,
    finished_at: null,
    items_pending: 100,
    items_applied: 0,
    items_flagged: 0,
    items_failed: 0,
    ...overrides,
  };
}

describe('<StartConfirmModal> time estimate', () => {
  it('shows a bucketed time estimate qualified as rough for a seed source', () => {
    estimateSeconds.mockReturnValue({ seconds: 150, source: 'seed' });
    render(
      <StartConfirmModal run={run()} tier={tier} onCancel={vi.fn()} onStart={vi.fn()} />,
    );
    expect(screen.getByText(/about 5 minutes/)).toBeInTheDocument();
    expect(screen.getByText(/rough estimate/)).toBeInTheDocument();
  });

  it('drops the rough qualifier when the estimate is history-backed', () => {
    estimateSeconds.mockReturnValue({ seconds: 150, source: 'model' });
    render(
      <StartConfirmModal run={run()} tier={tier} onCancel={vi.fn()} onStart={vi.fn()} />,
    );
    expect(screen.getByText(/about 5 minutes/)).toBeInTheDocument();
    expect(screen.queryByText(/rough estimate/)).not.toBeInTheDocument();
  });

  it('passes the run/tier/task_count and enabled flag to the hook', () => {
    estimateSeconds.mockReturnValue(null);
    render(
      <StartConfirmModal run={run()} tier={tier} onCancel={vi.fn()} onStart={vi.fn()} />,
    );
    expect(estimateSeconds).toHaveBeenCalledWith(
      'map-ingredient', 'ollama', 'qwen3:14b', 100, true,
    );
  });
});
