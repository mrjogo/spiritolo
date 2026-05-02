import { useEffect, useMemo, useRef, useState } from 'react';
import { supabase } from '../supabase';
import { ForceCanvas, type ForceCanvasHandle } from '../components/taxonomy/ForceCanvas';
import { Legend } from '../components/taxonomy/Legend';
import { SearchBox } from '../components/taxonomy/SearchBox';
import { FilterChips } from '../components/taxonomy/FilterChips';
import { ZoomControls } from '../components/taxonomy/ZoomControls';
import { NodeCard } from '../components/taxonomy/NodeCard';
import {
  effectiveRoleLabel,
  matchesQuery,
  neighborsOf,
  radialPositions,
  rowMatchesFilters,
  viewRowsToGraph,
  type FilterKey,
  type TaxonomyNode,
  type TaxonomyViewRow,
} from '../components/taxonomy/shapeData';
import { TX_BROWN_SOFT } from '../components/taxonomy/palette';
import '../components/taxonomy/taxonomy.css';

// Mirrors --site-header-height in styles.css. Used to size the
// taxonomy canvas to fill the viewport below the header.
const SITE_HEADER_HEIGHT = 56;

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
    h: window.innerHeight - SITE_HEADER_HEIGHT,
  });
  const [hovered, setHovered] = useState<TaxonomyNode | null>(null);
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState<Set<FilterKey>>(new Set());
  const [focusedId, setFocusedId] = useState<number | null>(null);
  const canvasRef = useRef<ForceCanvasHandle>(null);

  const byId = useMemo(() => new Map(rows.map((r) => [r.id, r])), [rows]);
  const focusedNode = focusedId ? (byId.get(focusedId) ?? null) : null;

  const neighborIds = useMemo(() => {
    if (!focusedNode) return null;
    const { parents, children } = neighborsOf(focusedNode, byId);
    return new Set<number>([
      focusedNode.id,
      ...parents.map((p) => p.id),
      ...children.map((c) => c.id),
    ]);
  }, [focusedNode, byId]);

  const dimmedIds = useMemo(() => {
    const dim = new Set<number>();
    for (const r of rows) {
      let dimMe = false;
      if (query.trim() !== '' && !matchesQuery(r, query)) dimMe = true;
      if (filters.size > 0 && !rowMatchesFilters(r, filters)) dimMe = true;
      if (neighborIds !== null && !neighborIds.has(r.id)) dimMe = true;
      if (dimMe) dim.add(r.id);
    }
    return dim;
  }, [rows, query, filters, neighborIds]);

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
      h: window.innerHeight - SITE_HEADER_HEIGHT,
    });
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  // Pin radial neighbors when focused, release when unfocused. We mutate
  // fx/fy on nodes in place — react-force-graph reads these properties
  // off the simulation graph each tick and pins matching nodes to the
  // given coordinates. This is the lib's documented pin API; React-side
  // immutability isn't observable here because the canvas owns its own
  // dataIsEqual checks and the mutation does not feed back into React
  // state. Disabling react-hooks/immutability for this block only.
  /* eslint-disable react-hooks/immutability */
  useEffect(() => {
    type PinNode = TaxonomyNode & { fx?: number | null; fy?: number | null };
    if (!focusedNode) {
      for (const n of nodes as PinNode[]) { n.fx = null; n.fy = null; }
      return;
    }
    const focusedRuntime = nodes.find((n) => n.id === focusedId) as { x?: number; y?: number } | undefined;
    if (focusedRuntime?.x == null || focusedRuntime.y == null) return;
    const { parents, children } = neighborsOf(focusedNode, byId);
    const positions = radialPositions(
      { id: focusedNode.id, x: focusedRuntime.x, y: focusedRuntime.y },
      parents, children,
      Math.min(size.w, size.h) * 0.22,
    );
    for (const n of nodes as PinNode[]) {
      const p = positions.get(n.id);
      if (p) { n.fx = p.x; n.fy = p.y; }
      else if (n.id === focusedNode.id) { n.fx = focusedRuntime.x; n.fy = focusedRuntime.y; }
      else { n.fx = null; n.fy = null; }
    }
    canvasRef.current?.centerAt(focusedRuntime.x, focusedRuntime.y, 600);
  }, [focusedNode, nodes, byId, size, focusedId]);
  /* eslint-enable react-hooks/immutability */

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

      <div
        style={{
          position: 'absolute', top: 14, left: 14, zIndex: 3,
          display: 'flex', flexDirection: 'column', gap: 8,
        }}
      >
        <SearchBox
          value={query}
          onChange={setQuery}
          onSubmit={() => {
            const top = rows.find((r) => matchesQuery(r, query));
            if (top) setFocusedId(top.id);
          }}
        />
        <FilterChips active={filters} onToggle={toggleFilter} />
      </div>
      <ForceCanvas
        ref={canvasRef}
        nodes={nodes}
        links={links}
        width={size.w}
        height={size.h}
        dimmedIds={dimmedIds}
        onNodeClick={(n) => setFocusedId(n.id)}
        onNodeHover={setHovered}
        onBackgroundClick={() => setFocusedId(null)}
      />
      <ZoomControls
        onZoomIn={() => canvasRef.current?.zoom(1.4)}
        onZoomOut={() => canvasRef.current?.zoom(1 / 1.4)}
        onFit={() => canvasRef.current?.fit()}
        right={focusedNode ? 264 : 24}
      />

      <Legend />

      {hovered && !focusedNode && (
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

      {focusedNode && (
        <NodeCard node={focusedNode} mode="pinned" onDismiss={() => setFocusedId(null)} />
      )}
    </div>
  );
}
