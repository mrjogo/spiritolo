import { useEffect, useMemo, useState } from 'react';
import { supabase } from '../supabase';
import { ForceCanvas } from '../components/taxonomy/ForceCanvas';
import {
  viewRowsToGraph,
  type TaxonomyNode,
  type TaxonomyViewRow,
} from '../components/taxonomy/shapeData';
import '../components/taxonomy/taxonomy.css';

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'loaded'; rows: TaxonomyViewRow[] };

const COLUMNS =
  'id, slug, display_name, role, role_default, ' +
  'is_cluster_node, is_defining_garnish, ' +
  'parent_ids, child_ids, aliases, recipe_count';

export function Taxonomy() {
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    supabase
      .from('taxonomy_public')
      .select(COLUMNS)
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) {
          setState({ status: 'error', message: error.message });
          return;
        }
        setState({ status: 'loaded', rows: (data ?? []) as unknown as TaxonomyViewRow[] });
      });
    return () => { cancelled = true; };
  }, []);

  if (state.status === 'loading') {
    return <div className="page">Loading taxonomy…</div>;
  }
  if (state.status === 'error') {
    return <div className="page">Error: {state.message}</div>;
  }
  return <LoadedView rows={state.rows} />;
}

function LoadedView({ rows }: { rows: TaxonomyViewRow[] }) {
  const { nodes, links } = useMemo(() => viewRowsToGraph(rows), [rows]);
  const [size, setSize] = useState({
    w: window.innerWidth,
    h: window.innerHeight - 56,
  });

  useEffect(() => {
    const handler = () => setSize({
      w: window.innerWidth,
      h: window.innerHeight - 56,
    });
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  return (
    <div className="taxonomy-page">
      <div className="taxonomy-page__corner taxonomy-page__corner--tl" />
      <div className="taxonomy-page__corner taxonomy-page__corner--tr" />
      <div className="taxonomy-page__corner taxonomy-page__corner--bl" />
      <div className="taxonomy-page__corner taxonomy-page__corner--br" />

      <div className="taxonomy-page__title">
        <div className="taxonomy-page__title-eyebrow">— A COMPENDIUM OF —</div>
        <div className="taxonomy-page__title-main">SPIRITS &amp; LIQUEURS</div>
        <div className="taxonomy-page__title-rule" />
      </div>

      <ForceCanvas
        nodes={nodes as TaxonomyNode[]}
        links={links}
        width={size.w}
        height={size.h}
        onNodeClick={() => { /* wired in Task 14 */ }}
        onNodeHover={() => { /* wired in Task 14 */ }}
      />
    </div>
  );
}
