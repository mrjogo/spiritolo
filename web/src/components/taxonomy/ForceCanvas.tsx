import { forwardRef, useImperativeHandle, useMemo, useRef } from 'react';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';
import {
  effectiveRole,
  isOrphan,
  type TaxonomyNode,
  type TaxonomyLink,
} from './shapeData';
import {
  ROLE_FILL,
  TX_GOLD,
  TX_NODE_BG,
  TX_ORPHAN_RING,
  TX_LINK,
  nodeRadius,
} from './palette';

export interface ForceCanvasHandle {
  zoom: (factor: number) => void;
  fit: () => void;
  centerAt: (x: number, y: number, ms?: number) => void;
}

interface Props {
  nodes: TaxonomyNode[];
  links: TaxonomyLink[];
  width: number;
  height: number;
  dimmedIds?: Set<number>;
  onNodeClick: (node: TaxonomyNode) => void;
  onNodeHover: (node: TaxonomyNode | null) => void;
  onBackgroundClick?: () => void;
}

export const ForceCanvas = forwardRef<ForceCanvasHandle, Props>(function ForceCanvas(
  { nodes, links, width, height, dimmedIds, onNodeClick, onNodeHover, onBackgroundClick },
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
    fit: () => inner.current?.zoomToFit(400, 60),
    centerAt: (x, y, ms = 400) => inner.current?.centerAt(x, y, ms),
  }), []);

  const data = useMemo(() => ({ nodes, links }), [nodes, links]);

  return (
    <ForceGraph2D
      ref={inner}
      graphData={data}
      width={width}
      height={height}
      backgroundColor="rgba(0,0,0,0)"
      nodeRelSize={4}
      nodeVal={(n) => nodeRadius(n as TaxonomyNode)}
      linkColor={() => TX_LINK}
      linkWidth={0.6}
      linkCurvature={0.18}
      enableNodeDrag={false}
      cooldownTicks={120}
      onNodeClick={(n) => onNodeClick(n as TaxonomyNode)}
      onNodeHover={(n) => onNodeHover((n as TaxonomyNode | null) ?? null)}
      onBackgroundClick={onBackgroundClick}
      nodeCanvasObject={(node, ctx) => {
        const n = node as TaxonomyNode & { x: number; y: number };
        const dimmed = dimmedIds?.has(n.id) ?? false;
        ctx.globalAlpha = dimmed ? 0.18 : 1;
        drawNode(n, ctx);
        ctx.globalAlpha = 1;
      }}
      nodeCanvasObjectMode={() => 'replace'}
    />
  );
});

function drawNode(
  node: TaxonomyNode & { x: number; y: number },
  ctx: CanvasRenderingContext2D,
) {
  const role = effectiveRole(node);
  const fill = ROLE_FILL[role];
  const radius = nodeRadius(node);
  const outerR = radius + 2.5;
  const haloR = radius + 1.7;

  // Outer dark cap
  ctx.beginPath();
  ctx.arc(node.x, node.y, outerR, 0, 2 * Math.PI);
  ctx.fillStyle = TX_NODE_BG;
  ctx.fill();

  // Cluster halo (thin extra ring)
  if (node.is_cluster_node) {
    ctx.beginPath();
    ctx.arc(node.x, node.y, haloR, 0, 2 * Math.PI);
    ctx.strokeStyle = TX_GOLD;
    ctx.lineWidth = 0.4;
    ctx.stroke();
  }

  // Gold ring (or dashed red if orphan)
  ctx.beginPath();
  ctx.arc(node.x, node.y, outerR, 0, 2 * Math.PI);
  if (isOrphan(node)) {
    ctx.strokeStyle = TX_ORPHAN_RING;
    ctx.setLineDash([2.2, 1.8]);
    ctx.lineWidth = 1.0;
  } else {
    ctx.strokeStyle = TX_GOLD;
    ctx.setLineDash([]);
    ctx.lineWidth = 1.0;
  }
  ctx.stroke();
  ctx.setLineDash([]);

  // Inner role-colored dot
  ctx.beginPath();
  ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
  ctx.fillStyle = fill;
  ctx.fill();
}
