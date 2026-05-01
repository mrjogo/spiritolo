import { useEffect, useMemo, useState } from 'react';
import { supabase } from '../supabase';
import { ForceCanvas } from '../components/taxonomy/ForceCanvas';
import { Legend } from '../components/taxonomy/Legend';
import { SearchBox } from '../components/taxonomy/SearchBox';
import { FilterChips } from '../components/taxonomy/FilterChips';
import {
  effectiveRoleLabel,
  matchesQuery,
  rowMatchesFilters,
  viewRowsToGraph,
  type FilterKey,
  type TaxonomyNode,
  type TaxonomyViewRow,
} from '../components/taxonomy/shapeData';
import { TX_BROWN_SOFT } from '../components/taxonomy/palette';
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
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState<Set<FilterKey>>(new Set());

  const dimmedIds = useMemo(() => {
    const dim = new Set<number>();
    for (const r of rows) {
      let dimMe = false;
      if (query.trim() !== '' && !matchesQuery(r, query)) dimMe = true;
      if (filters.size > 0 && !rowMatchesFilters(r, filters)) dimMe = true;
      if (dimMe) dim.add(r.id);
    }
    return dim;
  }, [rows, query, filters]);

  function toggleFilter(key: FilterKey) {
    setFilters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

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

      <SearchBox
        value={query}
        onChange={setQuery}
        onSubmit={() => { /* focus top match in Task 14 */ }}
      />
      <FilterChips active={filters} onToggle={toggleFilter} />
      <ForceCanvas
        nodes={nodes as TaxonomyNode[]}
        links={links}
        width={size.w}
        height={size.h}
        dimmedIds={dimmedIds}
        onNodeClick={() => { /* Task 14 */ }}
        onNodeHover={setHovered}
      />

      <Legend />

      {hovered && (
        <div
          className="tx-card"
          style={{
            position: 'absolute', top: 150, right: 14, zIndex: 3,
            padding: '8px 12px', fontSize: 12, lineHeight: 1.5, width: 200,
          }}
        >
          <div style={{ fontFamily: "'Cinzel', serif", fontWeight: 600, letterSpacing: '0.12em' }}>
            {hovered.display_name}
          </div>
          <div style={{ color: TX_BROWN_SOFT, fontStyle: 'italic' }}>
            {effectiveRoleLabel(hovered)} · {hovered.recipe_count} recipes · {hovered.aliases.length} aliases
          </div>
        </div>
      )}
    </div>
  );
}

