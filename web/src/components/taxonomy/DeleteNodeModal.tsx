import { useEffect, useState } from 'react';
import { ModalShell } from '../../ui/Modal';
import type { TaxonomyBlockers } from './rpcs';

interface Props {
  node: { id: number; slug: string; display_name: string };
  fetchBlockers: (id: number) => Promise<TaxonomyBlockers>;
  onCancel: () => void;
  onConfirm: (id: number) => Promise<void> | void;
}

export function DeleteNodeModal({ node, fetchBlockers, onCancel, onConfirm }: Props) {
  const [b, setB] = useState<TaxonomyBlockers | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirmInput, setConfirmInput] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchBlockers(node.id)
      .then((res) => { if (!cancelled) setB(res); })
      .catch((e: unknown) => { if (!cancelled) setErr(String(e)); });
    return () => { cancelled = true; };
  }, [fetchBlockers, node.id]);

  if (err) {
    return (
      <ModalShell onBackdropClick={onCancel}>
        <h2 className="tx-modal__title">Delete {node.display_name}?</h2>
        <div className="tx-field__error">Failed to read blockers: {err}</div>
        <div className="tx-form-actions">
          <button type="button" className="tx-btn tx-btn--ghost" onClick={onCancel}>Close</button>
        </div>
      </ModalShell>
    );
  }

  if (b === null) {
    return (
      <ModalShell onBackdropClick={onCancel}>
        <h2 className="tx-modal__title">Delete {node.display_name}?</h2>
        <div style={{ fontStyle: 'italic', opacity: 0.7 }}>Checking blockers…</div>
      </ModalShell>
    );
  }

  const blocked = b.children > 0 || b.recipe_ingredients > 0 || b.form_proposals > 0;
  const cascade: string[] = [];
  if (b.parents > 0) cascade.push(`${b.parents} parent edge${b.parents === 1 ? '' : 's'}`);
  if (b.aliases > 0) cascade.push(`${b.aliases} alias${b.aliases === 1 ? '' : 'es'}`);
  if (b.provenance > 0) cascade.push(`${b.provenance} provenance row${b.provenance === 1 ? '' : 's'}`);

  const blockerLines: string[] = [];
  if (b.children > 0) blockerLines.push(`${b.children} children — re-parent or delete first`);
  if (b.recipe_ingredients > 0) blockerLines.push(`${b.recipe_ingredients} recipe_ingredients references — remap first`);
  if (b.form_proposals > 0) blockerLines.push(`${b.form_proposals} open form-proposal references`);

  return (
    <ModalShell onBackdropClick={onCancel}>
      <h2 className="tx-modal__title">Delete {node.display_name} (#{node.id})?</h2>

      {cascade.length > 0 && (
        <>
          <div className="tx-field__label">Will cascade</div>
          <ul style={{ margin: '0 0 12px', paddingLeft: 18, fontSize: 13 }}>
            {cascade.map((c) => <li key={c}>{c}</li>)}
          </ul>
        </>
      )}

      {blocked && (
        <>
          <div className="tx-field__label" style={{ color: 'var(--tx-danger)' }}>Blockers</div>
          <ul style={{ margin: '0 0 12px', paddingLeft: 18, fontSize: 13, color: 'var(--tx-danger)' }}>
            {blockerLines.map((l) => <li key={l}>{l}</li>)}
          </ul>
          {b.child_names.length > 0 && (
            <div style={{ fontSize: 11, opacity: 0.7, marginBottom: 12, fontStyle: 'italic' }}>
              Children: {b.child_names.slice(0, 5).map((c) => `${c.display_name} (#${c.id})`).join(', ')}
              {b.child_names.length > 5 && `, … +${b.child_names.length - 5} more`}
            </div>
          )}
        </>
      )}

      {!blocked && (
        <div className="tx-field">
          <label className="tx-field__label" htmlFor="confirm-slug">
            Type slug to confirm
          </label>
          <input
            id="confirm-slug"
            className="tx-input"
            aria-label="confirm slug"
            type="text"
            value={confirmInput}
            onChange={(e) => setConfirmInput(e.target.value)}
            placeholder={node.slug}
          />
        </div>
      )}

      <div className="tx-form-actions">
        <button type="button" className="tx-btn tx-btn--ghost" onClick={onCancel}>Cancel</button>
        <button
          type="button"
          className="tx-btn tx-btn--danger"
          disabled={blocked || confirmInput !== node.slug || submitting}
          onClick={async () => {
            setSubmitting(true);
            try { await onConfirm(node.id); }
            finally { setSubmitting(false); }
          }}
        >Delete</button>
      </div>
    </ModalShell>
  );
}
