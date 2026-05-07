import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from 'react';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';
import { bboxCollide } from 'd3-bboxCollide';
import {
  effectiveKind,
  LABEL_FONT,
  type TaxonomyNode,
  type TaxonomyLink,
} from './shapeData';
import {
  ROLE_FILL,
  TX_GOLD,
  TX_GOLD_DIM,
  TX_CLUSTER_RING,
  TX_NODE_BG,
  TX_LINK,
  TX_LINK_DIM,
  TX_BROWN_FAINT,
  nodeRadius,
  type NodeSizeMode,
} from './palette';

const SHOW_LABEL_AT = 1.2;

export type DagMode = 'td' | 'bu' | 'lr' | 'rl' | 'radialout' | 'radialin';

export interface ForceCanvasHandle {
  zoom: (factor: number) => void;
  setZoom: (level: number, ms?: number) => void;
  fit: () => void;
  fitToNodes: (
    filter: (node: TaxonomyNode) => boolean,
    ms?: number,
    padding?: number,
  ) => void;
  centerAt: (x: number, y: number, ms?: number) => void;
  /** Convert a node's simulation coords to viewport (CSS) pixel coords. Returns null if not yet positioned. */
  getNodeScreenCoords: (id: number) => { x: number; y: number } | null;
  /** Current zoom factor — multiply simulation lengths by this to get on-screen pixel lengths. */
  getZoom: () => number;
}

// react-force-graph mutates `source`/`target` from id-numbers to the
// node objects after the simulation hooks them up. The accessor lambdas
// below see the post-mutation form; outbound callbacks return the same.
export interface RuntimeLink {
  source: TaxonomyNode | number;
  target: TaxonomyNode | number;
}

interface Props {
  nodes: TaxonomyNode[];
  links: TaxonomyLink[];
  width: number;
  height: number;
  dimmedIds?: Set<number>;
  dagMode?: DagMode;
  sizeMode?: NodeSizeMode;
  onNodeClick: (node: TaxonomyNode) => void;
  onNodeHover: (node: TaxonomyNode | null) => void;
  onLinkClick?: (link: RuntimeLink) => void;
  onLinkHover?: (link: RuntimeLink | null) => void;
  onBackgroundClick?: () => void;
  onEngineStop?: () => void;
}

function endpointId(end: TaxonomyNode | number): number {
  return typeof end === 'object' ? end.id : end;
}

export const ForceCanvas = forwardRef<ForceCanvasHandle, Props>(function ForceCanvas(
  {
    nodes, links, width, height, dimmedIds, dagMode, sizeMode = 'recipes',
    onNodeClick, onNodeHover, onLinkClick, onLinkHover, onBackgroundClick, onEngineStop,
  },
  ref,
) {
  const inner = useRef<ForceGraphMethods | undefined>(undefined);

  useImperativeHandle(ref, () => ({
    zoom: (factor) => {
      const g = inner.current;
      if (!g) return;
      const cur = g.zoom();
      g.zoom(cur * factor, 250);
    },
    setZoom: (level, ms = 400) => inner.current?.zoom(level, ms),
    fit: () => inner.current?.zoomToFit(400, 60),
    fitToNodes: (filter, ms = 400, padding = 60) =>
      inner.current?.zoomToFit(ms, padding, (n) => filter(n as TaxonomyNode)),
    centerAt: (x, y, ms = 400) => inner.current?.centerAt(x, y, ms),
    getNodeScreenCoords: (id) => {
      const g = inner.current;
      if (!g) return null;
      const node = nodes.find((n) => n.id === id) as { x?: number; y?: number } | undefined;
      if (node?.x == null || node.y == null) return null;
      const { x, y } = g.graph2ScreenCoords(node.x, node.y);
      return { x, y };
    },
    getZoom: () => inner.current?.zoom() ?? 1,
  }), [nodes]);

  useEffect(() => {
    const fg = inner.current;
    if (!fg) return;

    const PAD = 4;
    fg.d3Force(
      'collide',
      bboxCollide((node: unknown) => {
        const n = node as TaxonomyNode;
        const r = nodeRadius(n, sizeMode);
        const halfW = n.labelW / 2 + r + PAD;
        const halfH = n.labelH / 2 + r + PAD;
        return [[-halfW, -halfH], [halfW, halfH]];
      }).iterations(2),
    );
    fg.d3ReheatSimulation();
  }, [sizeMode]);

  const data = useMemo(() => ({ nodes, links }), [nodes, links]);

  return (
    <ForceGraph2D
      ref={inner}
      graphData={data}
      width={width}
      height={height}
      backgroundColor="rgba(0,0,0,0)"
      dagMode={dagMode}
      dagLevelDistance={80}
      nodeRelSize={4}
      nodeVal={(n) => nodeRadius(n as TaxonomyNode, sizeMode)}
      linkColor={(l) => {
        const link = l as RuntimeLink;
        const sId = endpointId(link.source);
        const tId = endpointId(link.target);
        return dimmedIds?.has(sId) || dimmedIds?.has(tId) ? TX_LINK_DIM : TX_LINK;
      }}
      linkWidth={0.6}
      linkCurvature={0.18}
      linkDirectionalArrowLength={4}
      linkDirectionalArrowRelPos={0.92}
      linkDirectionalArrowColor={(l) => {
        const link = l as RuntimeLink;
        const sId = endpointId(link.source);
        const tId = endpointId(link.target);
        return dimmedIds?.has(sId) || dimmedIds?.has(tId) ? TX_GOLD_DIM : TX_GOLD;
      }}
      enableNodeDrag={false}
      warmupTicks={300}
      cooldownTicks={0}
      showPointerCursor={(obj) => obj != null}
      onNodeClick={(n) => onNodeClick(n as TaxonomyNode)}
      onNodeHover={(n) => onNodeHover((n as TaxonomyNode | null) ?? null)}
      onLinkClick={(l) => onLinkClick?.(l as RuntimeLink)}
      onLinkHover={(l) => onLinkHover?.((l as RuntimeLink | null) ?? null)}
      onBackgroundClick={onBackgroundClick}
      onEngineStop={onEngineStop}
      nodeCanvasObject={(node, ctx, globalScale) => {
        const n = node as TaxonomyNode & { x: number; y: number };
        const dimmed = dimmedIds?.has(n.id) ?? false;
        ctx.globalAlpha = dimmed ? 0.18 : 1;
        drawNode(n, ctx, sizeMode);
        if (globalScale > SHOW_LABEL_AT) {
          ctx.font = LABEL_FONT;
          ctx.fillStyle = TX_BROWN_FAINT;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          ctx.fillText(n.display_name, n.x, n.y + nodeRadius(n, sizeMode) + 3);
        }
        ctx.globalAlpha = 1;
      }}
      nodeCanvasObjectMode={() => 'replace'}
    />
  );
});

function drawNode(
  node: TaxonomyNode & { x: number; y: number },
  ctx: CanvasRenderingContext2D,
  sizeMode: NodeSizeMode,
) {
  const role = effectiveKind(node);
  const fill = ROLE_FILL[role];
  const radius = nodeRadius(node, sizeMode);
  const outerR = radius + 2.5;

  // Outer dark cap
  ctx.beginPath();
  ctx.arc(node.x, node.y, outerR, 0, 2 * Math.PI);
  ctx.fillStyle = TX_NODE_BG;
  ctx.fill();

  // Gold ring (rust for clustering nodes)
  ctx.beginPath();
  ctx.arc(node.x, node.y, outerR, 0, 2 * Math.PI);
  ctx.strokeStyle = node.is_cluster_node ? TX_CLUSTER_RING : TX_GOLD;
  ctx.lineWidth = 1.0;
  ctx.stroke();

  // Inner role-colored dot
  ctx.beginPath();
  ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
  ctx.fillStyle = fill;
  ctx.fill();

  // Defining-garnish glyph: a small floral mark (❦) to the upper-left
  // when the node's presence changes a drink's identity (cocktail onion
  // → Gibson, salt rim → Salty Dog, etc.). Uses a serif character so
  // it renders monochrome in the deco palette, not as a color emoji.
  if (node.is_defining_garnish) {
    ctx.font = `${Math.max(8, radius * 1.6)}px serif`;
    ctx.fillStyle = TX_GOLD;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.fillText('❦', node.x - outerR - 1, node.y - outerR - 1);
  }
}

