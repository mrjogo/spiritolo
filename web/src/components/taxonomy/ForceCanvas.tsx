import { forwardRef, useImperativeHandle, useMemo, useRef } from 'react';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';
import {
  effectiveRole,
  type TaxonomyNode,
  type TaxonomyLink,
} from './shapeData';
import {
  ROLE_FILL,
  TX_GOLD,
  TX_NODE_BG,
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
  focusedId?: number | null;
  onNodeClick: (node: TaxonomyNode) => void;
  onNodeHover: (node: TaxonomyNode | null) => void;
  onBackgroundClick?: () => void;
}

export const ForceCanvas = forwardRef<ForceCanvasHandle, Props>(function ForceCanvas(
  { nodes, links, width, height, dimmedIds, focusedId, onNodeClick, onNodeHover, onBackgroundClick },
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
        if (focusedId != null && n.id === focusedId && n.aliases.length > 0) {
          drawAliasOrbit(n, ctx);
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

  // Gold ring
  ctx.beginPath();
  ctx.arc(node.x, node.y, outerR, 0, 2 * Math.PI);
  ctx.strokeStyle = TX_GOLD;
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

// Render a focused node's aliases as italic labels orbiting it. The
// labels are evenly spaced on a circle outside the node's outer ring;
// in dense arrangements adjacent labels can overlap (acceptable — the
// SpecimenCard panel always shows the canonical list).
function drawAliasOrbit(
  node: TaxonomyNode & { x: number; y: number },
  ctx: CanvasRenderingContext2D,
) {
  const radius = nodeRadius(node);
  const orbitR = radius + 22;
  const aliases = node.aliases.slice(0, 6); // cap so the canvas stays legible
  const step = (2 * Math.PI) / aliases.length;
  ctx.font = "italic 10px 'Cormorant Garamond', Georgia, serif";
  ctx.fillStyle = TX_GOLD;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (let i = 0; i < aliases.length; i++) {
    // Start at the top of the circle and walk clockwise.
    const angle = -Math.PI / 2 + i * step;
    const x = node.x + orbitR * Math.cos(angle);
    const y = node.y + orbitR * Math.sin(angle);
    ctx.fillText(`"${aliases[i]}"`, x, y);
  }
  if (node.aliases.length > 6) {
    ctx.fillText(`+${node.aliases.length - 6} more`, node.x, node.y + orbitR + 14);
  }
}
