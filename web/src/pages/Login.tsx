import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { startAuthentication, startRegistration } from '@simplewebauthn/browser';
import { api, ApiError } from '../api';
import { useAuth } from '../auth/AuthProvider';

interface InviteInfo {
  operator: { id: number; handle: string; display_name: string };
  expires_at: string;
}

type InviteState =
  | { kind: 'none' }
  | { kind: 'loading' }
  | { kind: 'ready'; info: InviteInfo }
  | { kind: 'invalid'; message: string };

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
// With ?invite=<token> (a registration link minted in /ops → Operators) it
// registers a passkey for that link's operator without a session — how a
// second operator joins, and how an existing one re-registers after the
// hostname changes (passkeys are bound to the domain they were made on).
export function Login() {
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const inviteToken = params.get('invite');
  const navigate = useNavigate();
  const { user, loading, setupRequired, refresh } = useAuth();
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  const [handle, setHandle] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [invite, setInvite] = useState<InviteState>({ kind: inviteToken ? 'loading' : 'none' });

  useEffect(() => {
    if (!inviteToken) return;
    let cancelled = false;
    api<InviteInfo>(`/api/auth/invite/${encodeURIComponent(inviteToken)}`)
      .then((info) => { if (!cancelled) setInvite({ kind: 'ready', info }); })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg = err instanceof ApiError && err.status === 410
          ? 'This registration link has already been used or has expired. Ask an admin for a new one.'
          : message(err);
        setInvite({ kind: 'invalid', message: msg });
      });
    return () => { cancelled = true; };
  }, [inviteToken]);

  async function redeemInvite() {
    if (invite.kind !== 'ready' || !inviteToken) return;
    setStatus({ kind: 'working' });
    try {
      const optionsJSON = await api<Parameters<typeof startRegistration>[0]['optionsJSON']>(
        '/api/auth/register/options', { body: { invite: inviteToken } },
      );
      const credential = await startRegistration({ optionsJSON });
      await api('/api/auth/register/verify', { body: { credential, label: `registered via link on ${window.location.hostname}` } });
      await refresh();
      navigate(next, { replace: true });
    } catch (err) {
      setStatus({ kind: 'error', message: message(err) });
    }
  }

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

  if (!loading && user && invite.kind === 'none') {
    navigate(next, { replace: true });
    return null;
  }

  const busy = status.kind === 'working' || loading;

  return (
    <main className="page page--login">
      <h1>Spiritolo</h1>
      {invite.kind !== 'none' ? (
        <section aria-label="registration link">
          {invite.kind === 'loading' && <p>Checking the registration link…</p>}
          {invite.kind === 'invalid' && <p role="alert">{invite.message}</p>}
          {invite.kind === 'ready' && (
            <>
              <p>
                Register a passkey for <strong>{invite.info.operator.display_name}</strong>{' '}
                (<code>{invite.info.operator.handle}</code>) on <code>{window.location.hostname}</code>.
                This link works once.
              </p>
              <button type="button" onClick={redeemInvite} disabled={busy}>
                Register passkey
              </button>
            </>
          )}
        </section>
      ) : setupRequired ? (
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
