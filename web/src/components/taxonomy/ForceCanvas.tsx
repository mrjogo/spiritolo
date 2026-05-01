import { useMemo, useRef } from 'react';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';
import {
  effectiveRole,
  isOrphan,
  type TaxonomyNode,
  type TaxonomyLink,
  type TaxonomyRole,
} from './shapeData';

const ROLE_FILL: Record<TaxonomyRole, string> = {
  substance:  '#e8d9b0',
  expression: '#a85b3a',
  brand:      '#7a9a82',
  unknown:    '#888888',
};

const RING        = '#c9a449';
const NODE_BG     = '#1a0f06';
const ORPHAN_RING = '#a85b3a';
const LINK        = 'rgba(201, 164, 73, 0.55)';

interface Props {
  nodes: TaxonomyNode[];
  links: TaxonomyLink[];
  width: number;
  height: number;
  onNodeClick: (node: TaxonomyNode) => void;
  onNodeHover: (node: TaxonomyNode | null) => void;
}

export function ForceCanvas({
  nodes, links, width, height, onNodeClick, onNodeHover,
}: Props) {
  const ref = useRef<ForceGraphMethods | undefined>(undefined);

  const data = useMemo(() => ({ nodes, links }), [nodes, links]);

  return (
    <ForceGraph2D
      ref={ref}
      graphData={data}
      width={width}
      height={height}
      backgroundColor="rgba(0,0,0,0)"
      nodeRelSize={4}
      nodeVal={(n) => Math.sqrt((n as TaxonomyNode).recipe_count + 1) * 2.2}
      linkColor={() => LINK}
      linkWidth={0.6}
      linkCurvature={0.18}
      enableNodeDrag={false}
      cooldownTicks={120}
      onNodeClick={(n) => onNodeClick(n as TaxonomyNode)}
      onNodeHover={(n) => onNodeHover((n as TaxonomyNode | null) ?? null)}
      nodeCanvasObject={(node, ctx) => drawNode(node as TaxonomyNode & { x: number; y: number }, ctx)}
      nodeCanvasObjectMode={() => 'replace'}
    />
  );
}

function drawNode(
  node: TaxonomyNode & { x: number; y: number },
  ctx: CanvasRenderingContext2D,
) {
  const role = effectiveRole(node);
  const fill = ROLE_FILL[role];
  const radius = Math.max(3, Math.sqrt(node.recipe_count + 1) * 2.2);

  // Outer dark cap
  ctx.beginPath();
  ctx.arc(node.x, node.y, radius + 2.5, 0, 2 * Math.PI);
  ctx.fillStyle = NODE_BG;
  ctx.fill();

  // Cluster halo (thin extra ring)
  if (node.is_cluster_node) {
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius + 1.7, 0, 2 * Math.PI);
    ctx.strokeStyle = RING;
    ctx.lineWidth = 0.4;
    ctx.stroke();
  }

  // Gold ring
  ctx.beginPath();
  ctx.arc(node.x, node.y, radius + 2.5, 0, 2 * Math.PI);
  if (isOrphan(node)) {
    ctx.strokeStyle = ORPHAN_RING;
    ctx.setLineDash([2.2, 1.8]);
    ctx.lineWidth = 1.0;
  } else {
    ctx.strokeStyle = RING;
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
