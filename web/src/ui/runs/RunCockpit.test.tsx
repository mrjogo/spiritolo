import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RunCockpit } from './RunCockpit';
import { isActiveRun, isFinishedRun, type RunHeader } from './useRun';

vi.mock('./useWorkerHealth', () => ({
  useWorkerHealth: () => ({
    freshest: { worker_id: 'w1', last_seen: new Date().toISOString(), providers: ['deepseek'], stages: [] },
    ageSeconds: 2,
    stale: false,
    liveProviders: ['deepseek'],
    loading: false,
  }),
}));

function run(overrides: Partial<RunHeader> = {}): RunHeader {
  return {
    id: 7,
    stage: 'extract-recipe',
    state: 'running',
    llm_provider: 'deepseek',
    llm_model: 'deepseek-v4-flash',
    task_count: 100,
    flagged_count: 0,
    never_run_count: 0,
    failed_count: 0,
    cost_estimate_cents: 50,
    max_cost_cents: 1000,
    created_at: null,
    created_by: null,
    cost_actual_cents: 42,
    error_code: null,
    error_detail: null,
    worker_id: 'w1',
    last_heartbeat: new Date().toISOString(),
    started_at: null,
    finished_at: null,
    items_pending: 40,
    items_applied: 55,
    items_flagged: 3,
    items_failed: 2,
    ...overrides,
  };
}

describe('run state helpers', () => {
  it('classifies active vs finished', () => {
    expect(isActiveRun('queued')).toBe(true);
    expect(isActiveRun('running')).toBe(true);
    expect(isActiveRun('cancelling')).toBe(true);
    expect(isActiveRun('done')).toBe(false);
    expect(isFinishedRun('failed')).toBe(true);
    expect(isFinishedRun('cancelled')).toBe(true);
    expect(isFinishedRun('running')).toBe(false);
  });
});

describe('<RunCockpit>', () => {
  it('running: progress + cost + worker health + Cancel (no Retry)', () => {
    render(<RunCockpit run={run({ state: 'running' })} onCancel={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByText(/Worker active/)).toBeInTheDocument();
    expect(screen.getByText(/60 \/ 100 items/)).toBeInTheDocument(); // 55+3+2 done
    expect(screen.getByText(/55 applied/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel run/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument();
  });

  it('failed: surfaces error_detail and offers Retry (no Cancel)', () => {
    render(
      <RunCockpit
        run={run({
          state: 'failed',
          error_code: 'provider_unavailable',
          error_detail: 'deepseek error 402: Insufficient Balance',
          items_pending: 100,
          items_applied: 0,
          items_flagged: 0,
          items_failed: 0,
        })}
        onCancel={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText(/Insufficient Balance/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry residue/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /cancel run/i })).not.toBeInTheDocument();
  });

  it('fires onCancel from the Cancel button', async () => {
    const onCancel = vi.fn();
    render(<RunCockpit run={run({ state: 'queued' })} onCancel={onCancel} onRetry={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /cancel run/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
