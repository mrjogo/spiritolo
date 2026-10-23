import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const apiMock = vi.fn();
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: (...args: unknown[]) => apiMock(...args) };
});

import { ImportDatabase } from './ImportDatabase';
import { sha256Hex } from './importDb';

const staged = {
  bytes: 3 * 1024 * 1024,
  sha256: 'ab'.repeat(32),
  staged_at: '2026-10-23T01:00:00Z',
  migrations: ['0001_init.sql'],
  pending_migrations: [],
  counts: { recipes: 1234, recipe_ingredients: 9876 },
  operators_carried: 1,
};

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ImportDatabase />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMock.mockReset();
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe('sha256Hex', () => {
  it('hex-encodes the WebCrypto digest', async () => {
    const hex = await sha256Hex(new TextEncoder().encode('abc').buffer as ArrayBuffer);
    expect(hex).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  });
});

describe('<ImportDatabase>', () => {
  it('shows "Nothing staged" when no file is staged', async () => {
    apiMock.mockResolvedValue({ staged: null, restart_on_apply: false });
    renderPage();
    expect(await screen.findByText(/nothing staged/i)).toBeInTheDocument();
    expect(apiMock).toHaveBeenCalledWith('/api/ops/import-db');
  });

  it('renders the staged summary and applies on confirm', async () => {
    apiMock.mockImplementation((path: string, init?: { body?: unknown }) => {
      if (path === '/api/ops/import-db') return Promise.resolve({ staged, restart_on_apply: false });
      if (path === '/api/ops/import-db/apply' && init?.body) return Promise.resolve({ applied: true, restarting: false });
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderPage();

    expect(await screen.findByText('3.0 MB')).toBeInTheDocument();
    expect(screen.getByText('1,234')).toBeInTheDocument();
    expect(screen.getByText(/1 carried over/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /apply: replace/i }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/import applied/i));
    expect(apiMock).toHaveBeenCalledWith('/api/ops/import-db/apply', { body: {} });
  });

  it('does nothing when the apply confirm is declined', async () => {
    apiMock.mockResolvedValue({ staged, restart_on_apply: true });
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /apply: replace/i }));
    expect(apiMock).not.toHaveBeenCalledWith('/api/ops/import-db/apply', expect.anything());
    expect(screen.getByText(/applying restarts the service/i)).toBeInTheDocument();
  });

  it('stages a chosen file with its digest and refreshes the status', async () => {
    apiMock.mockResolvedValue({ staged: null, restart_on_apply: false });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ staged }),
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();
    await screen.findByText(/nothing staged/i);

    const file = new File([new Uint8Array([1, 2, 3])], 'spiritolo.db');
    fireEvent.change(screen.getByLabelText(/database file/i), { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: /upload and verify/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/ops/import-db');
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['x-content-sha256']).toBe(
      '039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81',
    );
    vi.unstubAllGlobals();
  });

  it('surfaces an upload rejection', async () => {
    apiMock.mockResolvedValue({ staged: null, restart_on_apply: false });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 422, statusText: 'Unprocessable',
      json: () => Promise.resolve({ detail: 'digest mismatch: nope' }),
    }));
    renderPage();
    await screen.findByText(/nothing staged/i);
    fireEvent.change(screen.getByLabelText(/database file/i), { target: { files: [new File([new Uint8Array([1])], 'x.db')] } });
    fireEvent.click(screen.getByRole('button', { name: /upload and verify/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('digest mismatch: nope');
    vi.unstubAllGlobals();
  });
});
