import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const apiMock = vi.fn();
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: (...args: unknown[]) => apiMock(...args) };
});

import { Operators } from './Operators';
import { inviteUrl } from './operators';

const rows = [
  { id: 1, handle: 'ruddick', display_name: 'Ruddick', is_admin: true, created_at: '2026-10-23T00:00:00Z', last_login_at: '2026-10-24T17:00:00Z', passkeys: 1, pending_invites: 0 },
  { id: 2, handle: 'dana', display_name: 'Dana', is_admin: false, created_at: '2026-10-24T00:00:00Z', last_login_at: null, passkeys: 0, pending_invites: 1 },
];

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Operators />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMock.mockReset();
});

describe('<Operators>', () => {
  it('lists operators with passkey and pending-link counts', async () => {
    apiMock.mockImplementation(async (path: string) => (path === '/api/auth/passkeys' ? [] : rows));
    renderPage();
    const dana = (await screen.findByText('dana')).closest('tr')!;
    expect(dana).toHaveTextContent('never');
    expect(screen.getByRole('button', { name: /revoke links/i })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /registration link/i })).toHaveLength(2);
  });

  it('mints a registration link and shows the full URL once', async () => {
    const user = userEvent.setup();
    apiMock.mockImplementation(async (path: string, init?: { body?: unknown; method?: string }) => {
      if (path === '/api/ops/operators') return rows;
      if (path === '/api/auth/passkeys') return [];
      if (path === '/api/ops/operators/2/invites' && init?.body) {
        return { token: 'tok', path: '/login?invite=tok', expires_at: '2026-10-31T00:00:00Z', operator_id: 2 };
      }
      throw new Error(`unexpected ${path}`);
    });
    renderPage();
    const dana = (await screen.findByText('dana')).closest('tr')!;
    await user.click(dana.querySelector('button')!);

    const region = await screen.findByRole('region', { name: /registration link/i });
    expect(region).toHaveTextContent('Dana (dana)');
    expect(region).toHaveTextContent(`${window.location.origin}/login?invite=tok`);
  });

  it('creates an operator from the form', async () => {
    const user = userEvent.setup();
    apiMock.mockImplementation(async (path: string, init?: { body?: unknown }) => {
      if (path === '/api/ops/operators' && init?.body) return { id: 3 };
      if (path === '/api/ops/operators') return rows;
      if (path === '/api/auth/passkeys') return [];
      throw new Error(`unexpected ${path}`);
    });
    renderPage();
    await screen.findByText('dana');
    await user.type(screen.getByLabelText(/^handle/i), 'sam');
    await user.type(screen.getByLabelText(/display name/i), 'Sam');
    await user.click(screen.getByLabelText(/admin/i));
    await user.click(screen.getByRole('button', { name: /create operator/i }));
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith('/api/ops/operators', { body: { handle: 'sam', display_name: 'Sam', is_admin: true } }));
  });

  it('removes an old passkey after confirming, but never the last one', async () => {
    const user = userEvent.setup();
    let keys = [
      { credential_id: 'old', label: null, transports: [], created_at: '2026-10-23T00:00:00Z', last_used_at: '2026-10-24T17:00:00Z' },
      { credential_id: 'new', label: 'MacBook', transports: [], created_at: '2026-10-24T22:20:00Z', last_used_at: '2026-10-24T22:21:00Z' },
    ];
    apiMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/ops/operators') return rows;
      if (path === '/api/auth/passkeys') return keys;
      if (path === '/api/auth/passkeys/old' && init?.method === 'DELETE') {
        keys = keys.filter((k) => k.credential_id !== 'old');
        return { ok: true };
      }
      throw new Error(`unexpected ${path}`);
    });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderPage();
    const section = await screen.findByRole('region', { name: /your passkeys/i });
    const oldRow = (await within(section).findByText('unlabelled')).closest('tr')!;
    await user.click(within(oldRow).getByRole('button', { name: /remove/i }));
    expect(confirm).toHaveBeenCalled();
    await waitFor(() => expect(within(section).queryByText('unlabelled')).not.toBeInTheDocument());
    expect(within(section).getByRole('button', { name: /remove/i })).toBeDisabled();
    confirm.mockRestore();
  });

  it('builds the link from the given origin', () => {
    expect(inviteUrl('/login?invite=x', 'https://spiritolo.example')).toBe('https://spiritolo.example/login?invite=x');
  });
});
