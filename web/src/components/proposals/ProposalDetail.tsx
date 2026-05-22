import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { slugFormSchema, type SlugFormInput, type PendingProposal } from './schemas';
import { CandidatesList } from './CandidatesList';
import { NodePicker, type PickerNode } from './NodePicker';
import { FlagInput } from './FlagInput';

type Mode = 'idle' | 'map' | 'flag';

interface Props {
  proposal: PendingProposal;
  nodes: PickerNode[];
  flagReasons: string[];
  onCreate: (proposalId: number, slug: string) => Promise<void>;
  onMapToExisting: (proposalId: number, nodeId: number) => Promise<void>;
  onFlag: (proposalId: number, reason: string) => Promise<void>;
  onDefer: (proposalId: number) => void;
}

export function ProposalDetail({
  proposal, nodes, flagReasons,
  onCreate, onMapToExisting, onFlag, onDefer,
}: Props) {
  const [mode, setMode] = useState<Mode>('idle');
  const [mapTarget, setMapTarget] = useState<number | null>(null);

  // Reset transient state when the selected proposal changes. Keyed via
  // proposal.id at the component caller (Proposals page) — but the
  // mode/mapTarget state lives here so we reset on prop change too.
  const slugForm = useForm<SlugFormInput>({
    resolver: zodResolver(slugFormSchema),
    defaultValues: { slug: proposal.proposed_slug },
  });

  // Destructure formState eagerly so RHF's proxy reliably subscribes to
  // `errors` changes. Reads behind a short-circuit (`errors.slug && ...`)
  // can otherwise miss the subscription and skip re-renders on validation.
  const { isDirty, errors } = slugForm.formState;
  const slugError = errors.slug;

  // Re-sync the slug field whenever the user navigates to a different
  // proposal (parent should also reset by re-mounting via key, but this
  // is a safety net for in-place updates).
  if (slugForm.getValues('slug') !== proposal.proposed_slug && !isDirty) {
    slugForm.reset({ slug: proposal.proposed_slug });
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: 16 }}>
      <div>
        <div className="tx-field__label">Raw ingredient string</div>
        <div style={{ fontSize: 22, fontWeight: 600 }}>{proposal.raw_string}</div>
      </div>

      <div className="tx-form-row" style={{ display: 'flex', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <label htmlFor="slug" className="tx-field__label">Proposed slug</label>
          <input
            id="slug"
            type="text"
            className="tx-input"
            aria-invalid={!!slugError || undefined}
            {...slugForm.register('slug')}
          />
          {slugError && (
            <div className="tx-field__error">{slugError.message}</div>
          )}
        </div>
        <div style={{ flex: 1 }}>
          <div className="tx-field__label">Proposed display name</div>
          <div>{proposal.proposed_display_name ?? <em>(none)</em>}</div>
        </div>
        <div style={{ flex: 1 }}>
          <div className="tx-field__label">Proposed parent</div>
          <div>{proposal.proposed_parent_display_name ?? <em>(none)</em>}</div>
        </div>
      </div>

      <div>
        <div className="tx-field__label">Candidates (LLM nearest-neighbors)</div>
        <CandidatesList
          candidates={proposal.candidates}
          onPick={(id) => { setMode('map'); setMapTarget(id); }}
        />
      </div>

      {mode === 'map' && (
        <div>
          <div className="tx-field__label">Map raw_string to an existing node</div>
          <NodePicker
            nodes={nodes}
            value={mapTarget}
            onChange={setMapTarget}
          />
          <div className="tx-form-actions" style={{ marginTop: 8 }}>
            <button
              type="button"
              className="tx-btn tx-btn--ghost"
              onClick={() => { setMode('idle'); setMapTarget(null); }}
            >
              Cancel
            </button>
            <button
              type="button"
              className="tx-btn tx-btn--primary"
              disabled={mapTarget === null}
              onClick={async () => {
                if (mapTarget === null) return;
                await onMapToExisting(proposal.id, mapTarget);
                setMode('idle'); setMapTarget(null);
              }}
            >
              Confirm map
            </button>
          </div>
        </div>
      )}

      {mode === 'flag' && (
        <FlagInput
          existingReasons={flagReasons}
          onCancel={() => setMode('idle')}
          onSubmit={async (reason) => {
            await onFlag(proposal.id, reason);
            setMode('idle');
          }}
        />
      )}

      {mode === 'idle' && (
        <div className="tx-form-actions">
          <button
            type="button"
            className="tx-btn tx-btn--primary"
            onClick={slugForm.handleSubmit(async (v) => {
              await onCreate(proposal.id, v.slug);
            })}
          >
            Create
          </button>
          <button
            type="button"
            className="tx-btn"
            onClick={() => {
              setMode('map');
              setMapTarget(proposal.candidates[0]?.node_id ?? null);
            }}
          >
            Map to existing
          </button>
          <button
            type="button"
            className="tx-btn"
            onClick={() => setMode('flag')}
          >
            Flag
          </button>
          <button
            type="button"
            className="tx-btn tx-btn--ghost"
            onClick={() => onDefer(proposal.id)}
          >
            Defer
          </button>
        </div>
      )}
    </div>
  );
}
