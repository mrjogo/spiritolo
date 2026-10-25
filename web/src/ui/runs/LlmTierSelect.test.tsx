import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, renderHook, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const apiMock = vi.fn();
vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api')>()),
  api: (...args: unknown[]) => apiMock(...args),
}));
import { LlmTierSelect } from './LlmTierSelect';
import { defaultTier, findTier, rawTier, useLlmTiers, type LlmTier } from './llmTiers';

const TIERS = [
  { provider: 'local', model: 'qwen3:14b', label: 'Local · qwen3:14b — free (local)', short_label: 'Local · qwen3:14b', metered: false, available: true, price: null },
  {
    provider: 'deepseek', model: 'deepseek-v4-flash', label: 'DeepSeek · deepseek-v4-flash — metered', short_label: 'DeepSeek · deepseek-v4-flash',
    metered: true, available: false,
    price: { input_per_mtok: 0.14, output_per_mtok: 0.28, as_of: null, source: 's', current_window: null, windows: [] },
  },
  {
    provider: 'anthropic', model: 'claude-haiku-5-5', label: 'Claude · claude-haiku-5-5 — metered', short_label: 'Claude · claude-haiku-5-5',
    metered: true, available: true,
    price: { input_per_mtok: 0.1, output_per_mtok: 0.5, as_of: '2026-10-06', source: 's', current_window: null, windows: [] },
  },
];

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

async function loadTiers(): Promise<LlmTier[]> {
  const { result } = renderHook(() => useLlmTiers(), { wrapper });
  await waitFor(() => expect(result.current.status).toBe('loaded'));
  return result.current.tiers;
}

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockResolvedValue({ tiers: TIERS });
});

describe('llm tiers', () => {
  it('reads tiers from /api/ops/llm-tiers', async () => {
    const tiers = await loadTiers();
    expect(apiMock).toHaveBeenCalledWith('/api/ops/llm-tiers');
    expect(tiers.map((t) => t.shortLabel)).toEqual(['Local · qwen3:14b', 'DeepSeek · deepseek-v4-flash', 'Claude · claude-haiku-5-5']);
  });

  it('finds old run rows by their former provider ids', async () => {
    const tiers = await loadTiers();
    expect(findTier(tiers, 'ollama', 'qwen3:14b')?.provider).toBe('local');
    expect(findTier(tiers, 'claude', 'claude-haiku-5-5')?.provider).toBe('anthropic');
    expect(findTier(tiers, 'anthropic', 'claude-haiku-4-5')).toBeUndefined();
  });

  it('defaults to the first available tier', async () => {
    const tiers = await loadTiers();
    expect(defaultTier(tiers.slice(1))?.provider).toBe('anthropic');
    expect(defaultTier([])).toBeNull();
  });

  it('keeps an unlisted run tier as its raw provider · model', () => {
    const t = rawTier('anthropic', 'claude-haiku-4-5');
    expect(t.shortLabel).toBe('anthropic · claude-haiku-4-5');
    expect(t.metered).toBe(true);
    expect(rawTier('ollama', 'qwen3:14b').metered).toBe(false);
  });
});

describe('<LlmTierSelect>', () => {
  it('greys out tiers the server has no key for and picks available ones', async () => {
    const tiers = await loadTiers();
    const onChange = vi.fn();
    render(<LlmTierSelect value={tiers[0]} onChange={onChange} />, { wrapper });
    const ds = await screen.findByRole('option', { name: /DeepSeek/ });
    expect(ds).toBeDisabled();
    expect(ds).toHaveTextContent('no API key');
    await userEvent.selectOptions(screen.getByLabelText('LLM tier for this run'), 'anthropic:claude-haiku-5-5');
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ provider: 'anthropic', model: 'claude-haiku-5-5' }));
  });

  it("shows a run's unlisted tier as the selected raw option", async () => {
    render(<LlmTierSelect value={rawTier('anthropic', 'claude-haiku-4-5')} onChange={() => {}} />, { wrapper });
    await screen.findByRole('option', { name: /Claude · claude-haiku-5-5/ });
    const select = screen.getByLabelText('LLM tier for this run') as HTMLSelectElement;
    expect(select.value).toBe('anthropic:claude-haiku-4-5');
    expect(screen.getByRole('option', { name: /anthropic · claude-haiku-4-5/ })).toBeInTheDocument();
  });
});
