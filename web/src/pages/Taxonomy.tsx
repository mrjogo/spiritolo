import { useEffect, useMemo, useState } from 'react';
import { supabase } from '../supabase';
import { ForceCanvas } from '../components/taxonomy/ForceCanvas';
import { Legend } from '../components/taxonomy/Legend';
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
  const [hovered, setHovered] = useState<TaxonomyNode | null>(null);

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
        onNodeClick={() => { /* Task 14 */ }}
        onNodeHover={setHovered}
      />

      <Legend />

      {hovered && (
        <div
          className="tx-card"
          style={{
            position: 'absolute', top: 80, right: 14, zIndex: 3,
            padding: '8px 12px', fontSize: 12, lineHeight: 1.5, width: 200,
          }}
        >
          <div style={{ fontFamily: "'Cinzel', serif", fontWeight: 600, letterSpacing: '0.12em' }}>
            {hovered.display_name}
          </div>
          <div style={{ color: '#5a3f1a', fontStyle: 'italic' }}>
            {effectiveRoleLabel(hovered)} · {hovered.recipe_count} recipes · {hovered.aliases.length} aliases
          </div>
        </div>
      )}
    </div>
  );
}

function effectiveRoleLabel(n: TaxonomyNode): string {
  if (n.role) return n.role;
  if (n.role_default) return `${n.role_default}?`;
  return 'unknown';
}
