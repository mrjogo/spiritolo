import { useEffect, useMemo, useRef, useState } from 'react';
import { useTaxonomyUrlState } from '../components/taxonomy/useTaxonomyUrlState';
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
import { NodeCard, type FieldKey } from '../components/taxonomy/NodeCard';
import { EdgeCard, type EdgeRef } from '../components/taxonomy/EdgeCard';
import { TX_BROWN_MID, TX_FRAME_EDGE, type NodeSizeMode } from '../components/taxonomy/palette';
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
import { updateTaxonomyNode, createTaxonomyNode, setNodeParents, deleteTaxonomyNode, getTaxonomyNodeBlockers } from '../components/taxonomy/rpcs';
import { EditParentsModal } from '../components/taxonomy/EditParentsModal';
import { DeleteNodeModal } from '../components/taxonomy/DeleteNodeModal';
import { Toast } from '../components/taxonomy/Toast';
import { PlusButton } from '../components/taxonomy/PlusButton';
import { CreateChildModal } from '../components/taxonomy/CreateChildModal';
import { HighlightPulse } from '../components/taxonomy/HighlightPulse';
import { outerRingRadius, SHOW_LABEL_AT } from '../components/taxonomy/palette';
import '../components/taxonomy/taxonomy.css';

// Mirrors --site-header-height in styles.css. Used to size the
// taxonomy canvas to fill the viewport below the header.
const SITE_HEADER_HEIGHT = 56;

// Padding (px) around the focused neighborhood when zoomToFit-ing.
// Smaller = tighter zoom on the focused node.
const FOCUS_FIT_PADDING = 60;

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

      {state.status === 'error' ? (
        <div className="taxonomy-page__error">Error: {state.message}</div>
      ) : state.status === 'loaded' ? (
        <LoadedView rows={state.rows} />
      ) : (
        <div className="taxonomy-page__settling" role="status" aria-label="Loading taxonomy">
          <div className="taxonomy-page__spinner" aria-hidden="true" />
        </div>
      )}
    </div>
  );
}

function LoadedView({ rows: initialRows }: { rows: TaxonomyViewRow[] }) {
  const [rows, setRows] = useState<TaxonomyViewRow[]>(initialRows);
  const { nodes, links } = useMemo(() => viewRowsToGraph(rows), [rows]);
  const [size, setSize] = useState({
    w: window.innerWidth,
    h: window.innerHeight - SITE_HEADER_HEIGHT,
  });
  const [hovered, setHovered] = useState<TaxonomyNode | null>(null);
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState<Set<FilterKey>>(new Set());
  const { focusedId, focusedEdge, setFocusedId, setFocusedEdge, clearFocus } =
    useTaxonomyUrlState({ nodes });
  const [hoveredEdge, setHoveredEdge] = useState<EdgeRef | null>(null);
  const [dagMode, setDagMode] = useState<DagMode | undefined>(undefined);
  const [sizeMode, setSizeMode] = useState<NodeSizeMode>('uniform');
  const [settled, setSettled] = useState(false);
  const canvasRef = useRef<ForceCanvasHandle>(null);
  const [toast, setToast] = useState<{ message: string; kind?: 'info' | 'error' } | null>(null);
  const [editingParentsFor, setEditingParentsFor] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [creatingFor, setCreatingFor] = useState<TaxonomyViewRow | null>(null);
  const [plusCoords, setPlusCoords] = useState<{ x: number; y: number; r: number } | null>(null);
  const [pulseFor, setPulseFor] = useState<number | null>(null);
  const [pulseCoords, setPulseCoords] = useState<{ x: number; y: number; radius: number } | null>(null);

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

  const parentLookup = useMemo(
    () => new Map(rows.map((r) => [r.id, { id: r.id, display_name: r.display_name }])),
    [rows],
  );

  const editingParentsNode = editingParentsFor != null ? rows.find((r) => r.id === editingParentsFor) ?? null : null;
  const deletingNode = deletingId != null ? rows.find((r) => r.id === deletingId) ?? null : null;

  async function handleEditField(id: number, key: FieldKey, next: unknown) {
    const patch: Record<string, unknown> = { [key]: next };
    await updateTaxonomyNode(id, patch);
    setRows((prev) =>
      prev.map((r) => (r.id === id ? { ...r, [key]: next as never } : r)),
    );
  }

  useEffect(() => {
    if (!hovered) { setPlusCoords(null); return; }
    let frame = 0;
    const tick = () => {
      const zoom = canvasRef.current?.getZoom() ?? 1;
      // Same zoom threshold as canvas labels: at faraway zoom the graph
      // reads as topology, not as something to edit.
      if (zoom <= SHOW_LABEL_AT) {
        setPlusCoords(null);
        frame = requestAnimationFrame(tick);
        return;
      }
      const c = canvasRef.current?.getNodeScreenCoords(hovered.id);
      if (c) {
        // outerRingRadius() is in simulation-space units; multiply by current
        // zoom to get on-screen pixels so the overlay tracks the visible
        // outer edge (the gold ring), not the inner role-fill disc.
        const r = outerRingRadius(hovered as TaxonomyNode, sizeMode) * zoom;
        setPlusCoords({ x: c.x, y: c.y, r });
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [hovered, sizeMode]);

  useEffect(() => {
    if (pulseFor === null) return;
    const t = setTimeout(() => setPulseFor(null), 2000);
    return () => clearTimeout(t);
  }, [pulseFor]);

  useEffect(() => {
    if (pulseFor === null) { setPulseCoords(null); return; }
    const id = requestAnimationFrame(() => {
      const c = canvasRef.current?.getNodeScreenCoords(pulseFor);
      if (!c) return;
      const node = rows.find((r) => r.id === pulseFor);
      if (!node) return;
      const zoom = canvasRef.current?.getZoom() ?? 1;
      setPulseCoords({ x: c.x, y: c.y, radius: outerRingRadius(node as TaxonomyNode, sizeMode) * zoom });
      if (c.x < 0 || c.y < 0 || c.x > size.w || c.y > size.h) {
        const runtime = (rows.find((r) => r.id === pulseFor) as { x?: number; y?: number } | undefined);
        if (runtime?.x != null && runtime.y != null) {
          canvasRef.current?.centerAt(runtime.x, runtime.y, 600);
        }
      }
    });
    return () => cancelAnimationFrame(id);
  }, [pulseFor, rows, sizeMode, size]);

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
    type PinNode = TaxonomyNode & {
      x?: number; y?: number;
      vx?: number; vy?: number;
      fx?: number | null; fy?: number | null;
    };
    // Wait for the d3 engine to settle — until then nodes don't have
    // stable x/y, so any zoomToFit bbox would be garbage.
    if (!settled) return;
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
    // Snap x/y/vx/vy alongside fx/fy. The simulation is cooled (cooldownTicks=0)
    // so it won't re-tick the canvas to apply fx/fy on its own; snapping x/y
    // makes the new positions render immediately and gives zoomToFit a correct
    // bbox to compute the camera transform from.
    for (const n of nodes as PinNode[]) {
      const p = positions.get(n.id);
      if (p) {
        n.fx = p.x; n.fy = p.y;
        n.x = p.x; n.y = p.y;
        n.vx = 0; n.vy = 0;
      } else if (n.id === focusedNode.id) {
        n.fx = focusedRuntime.x; n.fy = focusedRuntime.y;
      } else {
        n.fx = null; n.fy = null;
      }
    }
    const inFrame = new Set<number>([focusedNode.id, ...positions.keys()]);
    canvasRef.current?.fitToNodes((n) => inFrame.has(n.id), 600, FOCUS_FIT_PADDING);
  }, [focusedNode, nodes, byId, size, focusedId, settled]);
  /* eslint-enable react-hooks/immutability */

  return (
    <>
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
        <select
          value={sizeMode}
          onChange={(e) => setSizeMode(e.target.value as NodeSizeMode)}
          aria-label="Node size mode"
          style={{
            fontFamily: "'Cinzel', serif", fontSize: 12, letterSpacing: '0.18em',
            padding: '6px 10px', borderRadius: 6,
            border: '1px solid #8a6a35',
            background: 'rgba(245, 233, 200, 0.85)',
            color: '#3a2a14',
            textTransform: 'uppercase', cursor: 'pointer',
          }}
        >
          <option value="recipes">Size: by recipes</option>
          <option value="uniform">Size: uniform</option>
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
        sizeMode={sizeMode}
        onNodeClick={(n) => {
          setFocusedId(n.id);
        }}
        onNodeHover={setHovered}
        onLinkClick={(l) => {
          const e = resolveLink(l);
          if (!e) return;
          setFocusedEdge(e);
        }}
        onLinkHover={(l) => setHoveredEdge(l ? resolveLink(l) : null)}
        onBackgroundClick={() => {
          clearFocus();
        }}
        onEngineStop={() => setSettled(true)}
      />
      {!settled && (
        <div className="taxonomy-page__settling" role="status" aria-label="Settling layout">
          <div className="taxonomy-page__spinner" aria-hidden="true" />
        </div>
      )}

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
                  setFocusedId(id);
                }}
              />
            );
          }
          if (focusedNode) {
            return (
              <NodeCard
                node={focusedNode}
                mode="pinned"
                onDismiss={() => setFocusedId(null)}
                onEditField={handleEditField}
                onEditParents={(id) => setEditingParentsFor(id)}
                onDelete={(id) => setDeletingId(id)}
                parentLookup={parentLookup}
              />
            );
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
      {hovered && plusCoords && (
        <PlusButton
          x={plusCoords.x}
          y={plusCoords.y}
          radius={plusCoords.r}
          ariaLabel={`Add child of ${hovered.display_name}`}
          onClick={() => setCreatingFor(hovered)}
        />
      )}
      {creatingFor && (
        <CreateChildModal
          parent={{ id: creatingFor.id, display_name: creatingFor.display_name }}
          onCancel={() => setCreatingFor(null)}
          onCreate={async (parentId, input) => {
            try {
              const newId = await createTaxonomyNode(parentId, input);
              setRows((prev) => [
                ...prev,
                {
                  id: newId, slug: input.slug, display_name: input.display_name,
                  node_kind: input.node_kind, default_role: input.default_role,
                  is_cluster_node: input.is_cluster_node,
                  is_defining_garnish: input.is_defining_garnish,
                  parent_ids: [parentId], child_ids: [],
                  aliases: input.aliases, recipe_count: 0,
                },
              ].map((r) => r.id === parentId ? { ...r, child_ids: [...r.child_ids, newId] } : r));
              setCreatingFor(null);
              setFocusedId(newId);
              setPulseFor(newId);
              setToast({ message: `Created ${input.display_name} (#${newId})` });
            } catch (e) {
              setToast({ message: `Create failed: ${String(e)}`, kind: 'error' });
            }
          }}
        />
      )}
      {pulseCoords && <HighlightPulse {...pulseCoords} />}
      {editingParentsNode && (
        <EditParentsModal
          node={editingParentsNode}
          currentParentIds={editingParentsNode.parent_ids}
          rows={rows}
          onCancel={() => setEditingParentsFor(null)}
          onSave={async (id, parentIds) => {
            try {
              await setNodeParents(id, parentIds);
              setRows((prev) => {
                const next = prev.map((r) => {
                  if (r.id === id) return { ...r, parent_ids: parentIds };
                  const wasParent = r.child_ids.includes(id);
                  const isParent = parentIds.includes(r.id);
                  if (wasParent && !isParent) return { ...r, child_ids: r.child_ids.filter((c) => c !== id) };
                  if (!wasParent && isParent) return { ...r, child_ids: [...r.child_ids, id] };
                  return r;
                });
                return next;
              });
              setEditingParentsFor(null);
              setPulseFor(id);
              setToast({ message: `Updated parents of ${editingParentsNode.display_name}` });
            } catch (e) {
              setToast({ message: `Save failed: ${String(e)}`, kind: 'error' });
            }
          }}
        />
      )}
      {deletingNode && (
        <DeleteNodeModal
          node={{ id: deletingNode.id, slug: deletingNode.slug, display_name: deletingNode.display_name }}
          fetchBlockers={getTaxonomyNodeBlockers}
          onCancel={() => setDeletingId(null)}
          onConfirm={async (id) => {
            try {
              await deleteTaxonomyNode(id);
              setRows((prev) => prev
                .filter((r) => r.id !== id)
                .map((r) => ({
                  ...r,
                  parent_ids: r.parent_ids.filter((p) => p !== id),
                  child_ids: r.child_ids.filter((c) => c !== id),
                })),
              );
              setDeletingId(null);
              if (focusedId === id) setFocusedId(null);
              setToast({ message: `Deleted ${deletingNode.display_name} (#${id})` });
            } catch (e) {
              setToast({ message: `Delete failed: ${String(e)}`, kind: 'error' });
            }
          }}
        />
      )}
      {toast && <Toast {...toast} onDismiss={() => setToast(null)} />}
    </>
  );
}
