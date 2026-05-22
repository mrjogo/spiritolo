import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { supabase } from '../supabase';
import { ProposalList } from '../components/proposals/ProposalList';
import { ProposalDetail } from '../components/proposals/ProposalDetail';
import {
  usePendingProposals, usePendingParents, useFlagReasons,
  useInvalidateProposalQueries,
} from '../components/proposals/queries';
import {
  applyProposalCreate, applyProposalMapToExisting, applyProposalFlag,
} from '../components/proposals/rpcs';
import type { PickerNode } from '../components/proposals/NodePicker';

async function fetchTaxonomyForPicker(): Promise<PickerNode[]> {
  const { data, error } = await supabase
    .from('taxonomy_public')
    .select('id, slug, display_name, aliases');
  if (error) throw error;
  return (data ?? []) as PickerNode[];
}

export function Proposals() {
  const proposalsQ = usePendingProposals();
  const parentsQ = usePendingParents();
  const flagReasonsQ = useFlagReasons();
  const nodesQ = useQuery({
    queryKey: ['taxonomy', 'picker'],
    queryFn: fetchTaxonomyForPicker,
  });
  const invalidate = useInvalidateProposalQueries();

  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Auto-select the first proposal when the list loads, and re-select
  // when the current selection disappears (after a write).
  useEffect(() => {
    const list = proposalsQ.data;
    if (!list || list.length === 0) { setSelectedId(null); return; }
    if (selectedId === null || !list.some((p) => p.id === selectedId)) {
      setSelectedId(list[0].id);
    }
  }, [proposalsQ.data, selectedId]);

  if (proposalsQ.isPending || parentsQ.isPending || nodesQ.isPending) {
    return <div style={{ padding: 24 }}>Loading proposals…</div>;
  }
  if (proposalsQ.error) {
    return <div style={{ padding: 24, color: 'crimson' }}>Error: {String(proposalsQ.error)}</div>;
  }

  const proposals = proposalsQ.data ?? [];
  const parents = parentsQ.data ?? [];
  const nodes = nodesQ.data ?? [];
  const flagReasons = flagReasonsQ.data ?? [];
  const selected = proposals.find((p) => p.id === selectedId) ?? null;

  if (proposals.length === 0) {
    return (
      <div style={{ padding: 24 }}>
        <h1>Proposals</h1>
        <p>No pending proposals.</p>
        <p style={{ opacity: 0.7 }}>
          Generate more with{' '}
          <code>cd ingredients &amp;&amp; uv run python -m ingredients.cli map resolve-pending</code>.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '38% 62%', height: 'calc(100vh - 56px)' }}>
      <div style={{ borderRight: '1px solid var(--tx-form-border)' }}>
        <ProposalList
          proposals={proposals}
          parents={parents}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
      </div>
      <div style={{ overflowY: 'auto' }}>
        {selected ? (
          <ProposalDetail
            // Re-mount detail on selection change so RHF + Mode state
            // start fresh for each proposal.
            key={selected.id}
            proposal={selected}
            nodes={nodes}
            flagReasons={flagReasons}
            onCreate={async (id, slug) => {
              await applyProposalCreate(id, slug === selected.proposed_slug ? null : slug);
              invalidate();
            }}
            onMapToExisting={async (id, nodeId) => {
              await applyProposalMapToExisting(id, nodeId);
              invalidate();
            }}
            onFlag={async (id, reason) => {
              await applyProposalFlag(id, reason);
              invalidate();
            }}
            onDefer={() => { setSelectedId(null); }}
          />
        ) : (
          <div style={{ padding: 24, opacity: 0.6 }}>Select a proposal.</div>
        )}
      </div>
    </div>
  );
}
