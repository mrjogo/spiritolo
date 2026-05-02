import { useEffect, useMemo, useRef, useState } from 'react';
import { supabase } from '../supabase';
import {
  ForceCanvas,
  type DagMode,
  type ForceCanvasHandle,
  type RuntimeLink,
} from '../components/taxonomy/ForceCanvas';
import { Legend } from '../components/taxonomy/Legend';
import { SearchBox } from '../components/taxonomy/SearchBox';
import { FilterChips } from '../components/taxonomy/FilterChips';
import { NodeCard } from '../components/taxonomy/NodeCard';
import { EdgeCard, type EdgeRef } from '../components/taxonomy/EdgeCard';
import { TX_BROWN_MID, TX_FRAME_EDGE } from '../components/taxonomy/palette';
import {
  matchesQuery,
  neighborsOf,
  radialPositions,
  rowMatchesFilters,
  viewRowsToGraph,
  type FilterKey,
  type TaxonomyNode,
  type TaxonomyViewRow,
} from '../components/taxonomy/shapeData';
import '../components/taxonomy/taxonomy.css';

// Mirrors --site-header-height in styles.css. Used to size the
// taxonomy canvas to fill the viewport below the header.
const SITE_HEADER_HEIGHT = 56;

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'loaded'; rows: TaxonomyViewRow[] };

const COLUMNS =
  'id, slug, display_name, node_kind, default_role, ' +
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
  const [hoveredEdge, setHoveredEdge] = useState<EdgeRef | null>(null);
  const [focusedEdge, setFocusedEdge] = useState<EdgeRef | null>(null);
  const [dagMode, setDagMode] = useState<DagMode | undefined>(undefined);
  const canvasRef = useRef<ForceCanvasHandle>(null);

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const focusedNode = focusedId ? (byId.get(focusedId) ?? null) : null;

  const resolveLink = (l: RuntimeLink): EdgeRef | null => {
    const sId = typeof l.source === 'object' ? l.source.id : l.source;
    const tId = typeof l.target === 'object' ? l.target.id : l.target;
    const source = byId.get(sId);
    const target = byId.get(tId);
    if (!source || !target) return null;
    return { source, target };
  };

  const neighborIds = useMemo(() => {
    if (!focusedNode) return null;
    const { parents, children } = neighborsOf(focusedNode, byId);
    return new Set<number>([
      focusedNode.id,
      ...parents.map((p) => p.id),
      ...children.map((c) => c.id),
    ]);
  }, [focusedNode, byId]);

  const edgeFocusIds = useMemo<Set<number> | null>(() => {
    if (!focusedEdge) return null;
    return new Set([focusedEdge.source.id, focusedEdge.target.id]);
  }, [focusedEdge]);

  const dimmedIds = useMemo(() => {
    const dim = new Set<number>();
    for (const r of rows) {
      let dimMe = false;
      if (query.trim() !== '' && !matchesQuery(r, query)) dimMe = true;
      if (filters.size > 0 && !rowMatchesFilters(r, filters)) dimMe = true;
      if (neighborIds !== null && !neighborIds.has(r.id)) dimMe = true;
      if (edgeFocusIds !== null && !edgeFocusIds.has(r.id)) dimMe = true;
      if (dimMe) dim.add(r.id);
    }
    return dim;
  }, [rows, query, filters, neighborIds, edgeFocusIds]);

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
        <select
          value={dagMode ?? 'free'}
          onChange={(e) => {
            const v = e.target.value;
            setDagMode(v === 'free' ? undefined : (v as DagMode));
          }}
          aria-label="Layout mode"
          style={{
            fontFamily: "'Cinzel', serif", fontSize: 12, letterSpacing: '0.18em',
            padding: '6px 10px', borderRadius: 6,
            border: '1px solid #8a6a35',
            background: 'rgba(245, 233, 200, 0.85)',
            color: '#3a2a14',
            textTransform: 'uppercase', cursor: 'pointer',
          }}
        >
          <option value="free">Layout: free</option>
          <option value="td">Layout: top → down</option>
          <option value="bu">Layout: bottom → up</option>
          <option value="lr">Layout: left → right</option>
          <option value="rl">Layout: right → left</option>
          <option value="radialout">Layout: radial out</option>
          <option value="radialin">Layout: radial in</option>
        </select>
        <button
          type="button"
          onClick={() => canvasRef.current?.fit()}
          aria-label="Fit to view"
          style={{
            fontFamily: "'Cinzel', serif", fontSize: 12, letterSpacing: '0.18em',
            padding: '6px 10px', borderRadius: 6,
            border: `1px solid ${TX_FRAME_EDGE}`,
            background: 'rgba(245, 233, 200, 0.85)',
            color: TX_BROWN_MID,
            textTransform: 'uppercase', cursor: 'pointer',
          }}
        >
          View all
        </button>
      </div>
      <ForceCanvas
        ref={canvasRef}
        nodes={nodes}
        links={links}
        width={size.w}
        height={size.h}
        dimmedIds={dimmedIds}
        dagMode={dagMode}
        onNodeClick={(n) => {
          setFocusedEdge(null);
          setFocusedId(n.id);
        }}
        onNodeHover={setHovered}
        onLinkClick={(l) => {
          const e = resolveLink(l);
          if (!e) return;
          setFocusedId(null);
          setFocusedEdge(e);
        }}
        onLinkHover={(l) => setHoveredEdge(l ? resolveLink(l) : null)}
        onBackgroundClick={() => {
          setFocusedId(null);
          setFocusedEdge(null);
        }}
      />

      <div
        style={{
          position: 'absolute', top: 14, right: 14, zIndex: 3,
          display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 12,
          maxHeight: `calc(100vh - ${SITE_HEADER_HEIGHT + 28}px)`,
        }}
      >
        <Legend />
        {(() => {
          if (focusedEdge) {
            return (
              <EdgeCard
                edge={focusedEdge}
                mode="pinned"
                onDismiss={() => setFocusedEdge(null)}
                onFocusNode={(id) => {
                  setFocusedEdge(null);
                  setFocusedId(id);
                }}
              />
            );
          }
          if (focusedNode) {
            return <NodeCard node={focusedNode} mode="pinned" onDismiss={() => setFocusedId(null)} />;
          }
          if (hoveredEdge && !focusedNode) {
            return <EdgeCard edge={hoveredEdge} mode="hover" onDismiss={() => {}} />;
          }
          if (hovered) {
            return <NodeCard node={hovered} mode="hover" onDismiss={() => {}} />;
          }
          return null;
        })()}
      </div>
    </div>
  );
}
