import { useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { startAuthentication, startRegistration } from '@simplewebauthn/browser';
import { api } from '../api';
import { useAuth } from '../auth/AuthProvider';

type Status =
  | { kind: 'idle' }
  | { kind: 'working' }
  | { kind: 'error'; message: string };

function safeNext(raw: string | null): string {
  // Only accept same-origin relative paths to prevent an open redirect via ?next=.
  return raw && raw.startsWith('/') && !raw.startsWith('//') ? raw : '/recipes';
}

function message(err: unknown): string {
  if (err && typeof err === 'object' && 'name' in err && (err as { name: string }).name === 'NotAllowedError') {
    return 'The passkey prompt was cancelled.';
  }
  return err instanceof Error ? err.message : String(err);
}

// Passkey login. While no operator exists yet the page offers first-time
// setup instead: create the operator and its first passkey in one step.
export function Login() {
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const navigate = useNavigate();
  const { user, loading, setupRequired, refresh } = useAuth();
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  const [handle, setHandle] = useState('');
  const [displayName, setDisplayName] = useState('');

  async function signIn() {
    setStatus({ kind: 'working' });
    try {
      const optionsJSON = await api<Parameters<typeof startAuthentication>[0]['optionsJSON']>(
        '/api/auth/login/options', { method: 'POST' },
      );
      const credential = await startAuthentication({ optionsJSON });
      await api('/api/auth/login/verify', { body: { credential } });
      await refresh();
      navigate(next, { replace: true });
    } catch (err) {
      setStatus({ kind: 'error', message: message(err) });
    }
  }

  async function setUp(e: FormEvent) {
    e.preventDefault();
    setStatus({ kind: 'working' });
    try {
      const optionsJSON = await api<Parameters<typeof startRegistration>[0]['optionsJSON']>(
        '/api/auth/register/options', { body: { handle, display_name: displayName } },
      );
      const credential = await startRegistration({ optionsJSON });
      await api('/api/auth/register/verify', { body: { credential, label: 'first passkey' } });
      await refresh();
      navigate(next, { replace: true });
    } catch (err) {
      setStatus({ kind: 'error', message: message(err) });
    }
  }

  if (!loading && user) {
    navigate(next, { replace: true });
    return null;
  }

  const busy = status.kind === 'working' || loading;

  return (
    <main className="page page--login">
      <h1>Spiritolo</h1>
      {setupRequired ? (
        <form onSubmit={setUp}>
          <p>No operator exists yet. Create the first account and its passkey.</p>
          <label htmlFor="handle">
            Handle
            <input
              id="handle"
              required
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              autoComplete="username webauthn"
            />
          </label>
          <label htmlFor="display_name">
            Display name
            <input
              id="display_name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              autoComplete="name"
            />
          </label>
          <button type="submit" disabled={busy}>
            Create passkey
          </button>
        </form>
      ) : (
        <button type="button" onClick={signIn} disabled={busy}>
          Sign in with passkey
        </button>
      )}
      {status.kind === 'error' && <p role="alert">{status.message}</p>}
    </main>
  );
}
