import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const fromMock = vi.fn();
vi.mock('../supabase', () => ({ supabase: { from: (table: string) => fromMock(table) } }));

import { isMetered, requiresApproval, useStageConfig, PIPELINE_STAGES, type StageConfigRow } from './stageConfig';

function wrapperWith(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  fromMock.mockReset();
});

describe('isMetered / requiresApproval', () => {
  // The pipeline's actual current split: fetch (ScraperAPI) is metered,
  // everything else defaults to a free deterministic/local provider chain.
  const rows: StageConfigRow[] = [
    { stage: 'fetch', metered: true, requires_approval: true },
    { stage: 'parse', metered: false, requires_approval: false },
  ];

  it('is driven by the fetched config, not a literal stage name', () => {
    expect(isMetered(rows, 'fetch')).toBe(true);
    expect(isMetered(rows, 'parse')).toBe(false);

    // Flip the config and the lookup flips with it — proves there's no
    // hardcoded 'fetch' branch inside isMetered itself.
    const flipped: StageConfigRow[] = [
      { stage: 'fetch', metered: false, requires_approval: false },
      { stage: 'parse', metered: true, requires_approval: true },
    ];
    expect(isMetered(flipped, 'fetch')).toBe(false);
    expect(isMetered(flipped, 'parse')).toBe(true);
  });

  it('defaults to false for a stage missing from the config rather than throwing', () => {
    expect(isMetered(rows, 'unknown-stage')).toBe(false);
    expect(requiresApproval(rows, 'unknown-stage')).toBe(false);
  });

  it('requiresApproval mirrors the row, independently of metered', () => {
    expect(requiresApproval(rows, 'fetch')).toBe(true);
    expect(requiresApproval(rows, 'parse')).toBe(false);
  });
});

describe('PIPELINE_STAGES', () => {
  it('lists the unified pipeline in discover -> ... -> export order', () => {
    expect(PIPELINE_STAGES).toEqual([
      'discover', 'classify', 'fetch', 'extract', 'parse', 'map', 'role', 'cluster', 'export',
    ]);
  });
});

describe('useStageConfig', () => {
  it('fetches stage_config and exposes the rows', async () => {
    const select = vi.fn().mockResolvedValue({
      data: [
        { stage: 'fetch', metered: true, requires_approval: true },
        { stage: 'parse', metered: false, requires_approval: false },
      ],
      error: null,
    });
    fromMock.mockReturnValue({ select });

    const { result } = renderHook(() => useStageConfig(), { wrapper: wrapperWith(makeClient()) });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(fromMock).toHaveBeenCalledWith('stage_config');
    expect(result.current.rows).toEqual([
      { stage: 'fetch', metered: true, requires_approval: true },
      { stage: 'parse', metered: false, requires_approval: false },
    ]);
  });

  it('surfaces an empty list (not a throw) while loading', () => {
    fromMock.mockReturnValue({ select: vi.fn().mockReturnValue(new Promise(() => {})) });
    const { result } = renderHook(() => useStageConfig(), { wrapper: wrapperWith(makeClient()) });
    expect(result.current.rows).toEqual([]);
    expect(result.current.isLoading).toBe(true);
  });
});
