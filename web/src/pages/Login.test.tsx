import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { Login } from './Login';

const signInMock = vi.fn();
vi.mock('../supabase', () => ({
  supabase: { auth: { signInWithOtp: (args: unknown) => signInMock(args) } },
}));

beforeEach(() => {
  signInMock.mockReset();
  signInMock.mockResolvedValue({ data: {}, error: null });
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Login />
    </MemoryRouter>,
  );
}

describe('Login', () => {
  it('calls signInWithOtp with the typed email and a callback URL preserving ?next=', async () => {
    const user = userEvent.setup();
    renderAt('/login?next=%2Frecipes%2Fabc');

    await user.type(screen.getByLabelText(/email/i), 'me@example.com');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    expect(signInMock).toHaveBeenCalledTimes(1);
    const call = signInMock.mock.calls[0][0] as {
      email: string;
      options: { emailRedirectTo: string; shouldCreateUser: boolean };
    };
    expect(call.email).toBe('me@example.com');
    expect(call.options.emailRedirectTo).toMatch(
      /\/auth\/callback\?next=%2Frecipes%2Fabc$/,
    );
    // Login-only: do not auto-create users for unknown emails.
    expect(call.options.shouldCreateUser).toBe(false);
  });

  it('shows a confirmation after a successful submit', async () => {
    const user = userEvent.setup();
    renderAt('/login');

    await user.type(screen.getByLabelText(/email/i), 'me@example.com');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    expect(await screen.findByText(/check your email/i)).toBeInTheDocument();
  });

  it('shows an error message when signInWithOtp returns an error', async () => {
    signInMock.mockResolvedValue({ data: null, error: { message: 'rate limit' } });
    const user = userEvent.setup();
    renderAt('/login');

    await user.type(screen.getByLabelText(/email/i), 'me@example.com');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    expect(await screen.findByText(/rate limit/i)).toBeInTheDocument();
  });
});
