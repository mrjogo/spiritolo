import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api';
import { inviteUrl, myPasskeysKey, operatorsKey, type InviteResult, type OperatorRow, type PasskeyRow } from './operators';

// /ops → Operators: who can sign in, and registration links. A link is a
// single-use, 7-day URL that registers a passkey for one operator with no
// session. Use it to let a new operator in, or to re-register yourself after
// the public hostname changes — passkeys only work on the domain they were
// created on, so without a link minted beforehand the move locks everyone out.

export function Operators() {
  const queryClient = useQueryClient();
  const operators = useQuery({ queryKey: operatorsKey, queryFn: () => api<OperatorRow[]>('/api/ops/operators') });
  const [handle, setHandle] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [link, setLink] = useState<InviteResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const passkeys = useQuery({ queryKey: myPasskeysKey, queryFn: () => api<PasskeyRow[]>('/api/auth/passkeys') });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: operatorsKey });

  const removeKey = useMutation({
    mutationFn: (credentialId: string) =>
      api<{ ok: boolean }>(`/api/auth/passkeys/${encodeURIComponent(credentialId)}`, { method: 'DELETE' }),
    onSuccess: async () => {
      setError(null);
      await Promise.all([queryClient.invalidateQueries({ queryKey: myPasskeysKey }), invalidate()]);
    },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });

  function onRemoveKey(k: PasskeyRow) {
    const when = new Date(k.created_at).toLocaleString();
    if (window.confirm(`Remove the passkey created ${when}? It will no longer sign you in.`)) removeKey.mutate(k.credential_id);
  }

  const create = useMutation({
    mutationFn: () => api<{ id: number }>('/api/ops/operators', { body: { handle, display_name: displayName, is_admin: isAdmin } }),
    onSuccess: async () => {
      setHandle(''); setDisplayName(''); setIsAdmin(false); setError(null);
      await invalidate();
    },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });

  const mint = useMutation({
    mutationFn: (operatorId: number) => api<InviteResult>(`/api/ops/operators/${operatorId}/invites`, { body: {} }),
    onSuccess: async (result) => {
      setLink(result); setCopied(false); setError(null);
      await invalidate();
    },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });

  const revoke = useMutation({
    mutationFn: (operatorId: number) => api<{ revoked: number }>(`/api/ops/operators/${operatorId}/invites`, { method: 'DELETE' }),
    onSuccess: async (_r, operatorId) => {
      if (link?.operator_id === operatorId) setLink(null);
      await invalidate();
    },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });

  function onCreate(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  async function copyLink() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(inviteUrl(link.path));
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const linkOwner = link ? operators.data?.find((o) => o.id === link.operator_id) : undefined;

  return (
    <div className="ops-operators">
      <h2>Operators</h2>
      <p className="ops-operators__lead">
        Operators sign in with passkeys. A <strong>registration link</strong> lets one operator add a
        passkey without signing in: it is how a new operator gets their first passkey, and how you keep
        access when the site moves to a new hostname (passkeys only work on the domain they were created
        on, so mint a link for yourself <em>before</em> changing <code>PUBLIC_ORIGIN</code> and open it on
        the new one). Links work once and expire after 7 days.
      </p>

      {error && <p role="alert" className="ops-operators__error">{error}</p>}

      {link && (
        <section className="ops-operators__link" aria-label="registration link">
          <h3>Registration link for {linkOwner ? `${linkOwner.display_name} (${linkOwner.handle})` : `operator #${link.operator_id}`}</h3>
          <p>Shown once. Open it on whichever hostname the operator should register on; the path is the same everywhere.</p>
          <code className="ops-operators__url">{inviteUrl(link.path)}</code>
          <div className="ops-operators__actions">
            <button type="button" onClick={copyLink}>{copied ? 'Copied' : 'Copy link'}</button>
            <button type="button" onClick={() => setLink(null)}>Dismiss</button>
          </div>
          <p className="ops-operators__muted">Expires {new Date(link.expires_at).toLocaleString()}.</p>
        </section>
      )}

      {operators.isLoading && <p>Loading…</p>}
      {operators.error && <p role="alert">{String(operators.error)}</p>}
      {operators.data && (
        <table className="ops-operators__table">
          <thead>
            <tr>
              <th>Handle</th>
              <th>Name</th>
              <th>Admin</th>
              <th>Passkeys</th>
              <th>Last login</th>
              <th>Pending links</th>
              <th aria-label="actions" />
            </tr>
          </thead>
          <tbody>
            {operators.data.map((o) => (
              <tr key={o.id}>
                <td><code>{o.handle}</code></td>
                <td>{o.display_name}</td>
                <td>{o.is_admin ? 'yes' : 'no'}</td>
                <td>{o.passkeys}</td>
                <td>{o.last_login_at ? new Date(o.last_login_at).toLocaleString() : 'never'}</td>
                <td>{o.pending_invites}</td>
                <td className="ops-operators__actions">
                  <button type="button" onClick={() => mint.mutate(o.id)} disabled={mint.isPending}>
                    Registration link
                  </button>
                  {o.pending_invites > 0 && (
                    <button type="button" onClick={() => revoke.mutate(o.id)} disabled={revoke.isPending}>
                      Revoke links
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <section className="ops-operators__keys" aria-label="your passkeys">
        <h3>Your passkeys</h3>
        <p className="ops-operators__muted">
          A passkey only works on the hostname it was created on, so after a hostname move the old one shows no
          new use. You can remove any passkey except your last.
        </p>
        {passkeys.data && (
          <table className="ops-operators__table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Created</th>
                <th>Last used</th>
                <th aria-label="actions" />
              </tr>
            </thead>
            <tbody>
              {passkeys.data.map((k) => (
                <tr key={k.credential_id}>
                  <td>{k.label || <span className="ops-operators__muted">unlabelled</span>}</td>
                  <td>{new Date(k.created_at).toLocaleString()}</td>
                  <td>{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : 'never'}</td>
                  <td className="ops-operators__actions">
                    <button type="button" onClick={() => onRemoveKey(k)}
                      disabled={removeKey.isPending || passkeys.data.length < 2}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="ops-operators__new">
        <h3>New operator</h3>
        <form onSubmit={onCreate}>
          <label htmlFor="op-handle">
            Handle
            <input id="op-handle" required value={handle} onChange={(e) => setHandle(e.target.value)} autoComplete="off" />
          </label>
          <label htmlFor="op-display">
            Display name
            <input id="op-display" value={displayName} onChange={(e) => setDisplayName(e.target.value)} autoComplete="off" />
          </label>
          <label htmlFor="op-admin" className="ops-operators__check">
            <input id="op-admin" type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} />
            Admin (can use /ops)
          </label>
          <button type="submit" disabled={create.isPending || !handle.trim()}>Create operator</button>
        </form>
        <p className="ops-operators__muted">Then mint a registration link for them and send it over.</p>
      </section>
    </div>
  );
}
