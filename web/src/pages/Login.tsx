import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { supabase } from '../supabase';

export function Login() {
  const [params] = useSearchParams();
  const next = params.get('next') ?? '/recipes';
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<
    | { kind: 'idle' }
    | { kind: 'sending' }
    | { kind: 'sent' }
    | { kind: 'error'; message: string }
  >({ kind: 'idle' });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setStatus({ kind: 'sending' });
    const emailRedirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(
      next,
    )}`;
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo },
    });
    if (error) {
      setStatus({ kind: 'error', message: error.message });
      return;
    }
    setStatus({ kind: 'sent' });
  }

  return (
    <main className="page page--login">
      <h1>Spiritolo</h1>
      <form onSubmit={onSubmit}>
        <label>
          Email
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </label>
        <button type="submit" disabled={status.kind === 'sending'}>
          Send magic link
        </button>
      </form>
      {status.kind === 'sent' && <p>Check your email for a sign-in link.</p>}
      {status.kind === 'error' && <p role="alert">{status.message}</p>}
    </main>
  );
}
