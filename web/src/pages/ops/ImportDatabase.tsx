import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '../../api';
import { importStatusKey, uploadDatabase, type ImportStatus } from './importDb';

// /ops → Import: replace the live database with a SQLite file built offline
// by scripts/pg_to_sqlite (the staging data migration). Two steps, mirroring
// the API: stage (upload + verify, nothing live changes) then apply (swap,
// which in the container restarts the process).

function formatBytes(n: number): string {
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

type Phase =
  | { kind: 'idle' }
  | { kind: 'uploading'; name: string }
  | { kind: 'applying' }
  | { kind: 'restarting'; since: number }
  | { kind: 'done' }
  | { kind: 'error'; message: string };

export function ImportDatabase() {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: importStatusKey,
    queryFn: () => api<ImportStatus>('/api/ops/import-db'),
  });
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });
  const fileRef = useRef<HTMLInputElement>(null);

  // After a restart-mode apply, poll /api/health until the new process answers.
  useEffect(() => {
    if (phase.kind !== 'restarting') return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const res = await fetch('/api/health', { credentials: 'same-origin' });
        if (res.ok && !cancelled) {
          setPhase({ kind: 'done' });
          void queryClient.invalidateQueries();
        }
      } catch {
        /* still down */
      }
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [phase, queryClient]);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: importStatusKey });

  async function onUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setPhase({ kind: 'uploading', name: file.name });
    try {
      await uploadDatabase(file);
      setPhase({ kind: 'idle' });
      await invalidate();
    } catch (e) {
      setPhase({ kind: 'error', message: e instanceof Error ? e.message : String(e) });
    }
  }

  async function onApply() {
    if (!window.confirm('Replace the live database with the staged file? The current data is discarded.')) return;
    setPhase({ kind: 'applying' });
    try {
      const r = await api<{ applied: boolean; restarting: boolean }>('/api/ops/import-db/apply', { body: {} });
      if (r.restarting) {
        setPhase({ kind: 'restarting', since: Date.now() });
      } else {
        setPhase({ kind: 'done' });
        void queryClient.invalidateQueries();
      }
    } catch (e) {
      // A restart-mode apply can drop the connection before the JSON arrives.
      if (status.data?.restart_on_apply && !(e instanceof ApiError)) {
        setPhase({ kind: 'restarting', since: Date.now() });
        return;
      }
      setPhase({ kind: 'error', message: e instanceof Error ? e.message : String(e) });
    }
  }

  async function onDiscard() {
    try {
      await api('/api/ops/import-db', { method: 'DELETE' });
      setPhase({ kind: 'idle' });
      await invalidate();
    } catch (e) {
      setPhase({ kind: 'error', message: e instanceof Error ? e.message : String(e) });
    }
  }

  const staged = status.data?.staged ?? null;
  const busy = phase.kind === 'uploading' || phase.kind === 'applying' || phase.kind === 'restarting';

  return (
    <div className="ops-import">
      <h2>Import database</h2>
      <p className="ops-import__lead">
        Replace the live SQLite database with a file built by <code>scripts/pg_to_sqlite</code>.
        Uploading only stages the file and verifies it; nothing changes until you apply.
        {status.data?.restart_on_apply && ' Applying restarts the service for a few seconds.'}
      </p>

      <section className="ops-import__step">
        <h3>1. Stage a file</h3>
        <input ref={fileRef} type="file" accept=".db,.sqlite,.sqlite3" disabled={busy} aria-label="database file" />
        <button type="button" onClick={onUpload} disabled={busy}>
          {phase.kind === 'uploading' ? `Uploading ${phase.name}…` : 'Upload and verify'}
        </button>
      </section>

      <section className="ops-import__step">
        <h3>2. Apply</h3>
        {status.isLoading && <p>Loading…</p>}
        {status.isError && <p className="ops-import__error">Could not load import status.</p>}
        {status.data && !staged && <p>Nothing staged.</p>}
        {staged && (
          <div className="ops-import__staged">
            <dl>
              <dt>Size</dt><dd>{formatBytes(staged.bytes)}</dd>
              <dt>SHA-256</dt><dd><code>{staged.sha256}</code></dd>
              <dt>Staged at</dt><dd>{staged.staged_at}</dd>
              <dt>Migrations</dt>
              <dd>
                {staged.migrations.length} applied
                {staged.pending_migrations.length > 0 && `, ${staged.pending_migrations.length} will apply on boot`}
              </dd>
              <dt>Operators</dt>
              <dd>{staged.operators_carried > 0 ? `${staged.operators_carried} carried over from the live database` : 'present in file'}</dd>
            </dl>
            <table className="ops-import__counts">
              <thead><tr><th>Table</th><th>Rows</th></tr></thead>
              <tbody>
                {Object.entries(staged.counts).map(([table, n]) => (
                  <tr key={table}><td>{table}</td><td>{n.toLocaleString()}</td></tr>
                ))}
              </tbody>
            </table>
            <div className="ops-import__actions">
              <button type="button" onClick={onApply} disabled={busy} className="ops-import__apply">
                {phase.kind === 'applying' ? 'Applying…' : 'Apply: replace the live database'}
              </button>
              <button type="button" onClick={onDiscard} disabled={busy}>Discard staged file</button>
            </div>
          </div>
        )}
      </section>

      {phase.kind === 'restarting' && (
        <p role="status" className="ops-import__notice">Restarting the service… waiting for it to come back.</p>
      )}
      {phase.kind === 'done' && (
        <p role="status" className="ops-import__notice">Import applied. The live database is now the imported file.</p>
      )}
      {phase.kind === 'error' && (
        <p role="alert" className="ops-import__error">{phase.message}</p>
      )}
    </div>
  );
}
