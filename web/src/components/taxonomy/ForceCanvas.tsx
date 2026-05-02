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
  TX_CLUSTER_RING,
  TX_NODE_BG,
  TX_LINK,
  TX_BROWN_FAINT,
  nodeRadius,
} from './palette';

const SHOW_LABEL_AT = 1.2;

export type DagMode = 'td' | 'bu' | 'lr' | 'rl' | 'radialout' | 'radialin';

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
  dagMode?: DagMode;
  onNodeClick: (node: TaxonomyNode) => void;
  onNodeHover: (node: TaxonomyNode | null) => void;
  onBackgroundClick?: () => void;
}

export const ForceCanvas = forwardRef<ForceCanvasHandle, Props>(function ForceCanvas(
  { nodes, links, width, height, dimmedIds, dagMode, onNodeClick, onNodeHover, onBackgroundClick },
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

  useEffect(() => {
    const fg = inner.current;
    if (!fg) return;

    const PAD = 4;
    fg.d3Force(
      'collide',
      bboxCollide((node: unknown) => {
        const n = node as TaxonomyNode;
        const r = nodeRadius(n);
        const halfW = n.labelW / 2 + r + PAD;
        const halfH = n.labelH / 2 + r + PAD;
        return [[-halfW, -halfH], [halfW, halfH]];
      }).iterations(2),
    );
  }, []);

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
      nodeVal={(n) => nodeRadius(n as TaxonomyNode)}
      linkColor={() => TX_LINK}
      linkWidth={0.6}
      linkCurvature={0.18}
      linkDirectionalArrowLength={4}
      linkDirectionalArrowRelPos={0.92}
      linkDirectionalArrowColor={() => TX_GOLD}
      enableNodeDrag={false}
      cooldownTicks={120}
      onNodeClick={(n) => onNodeClick(n as TaxonomyNode)}
      onNodeHover={(n) => onNodeHover((n as TaxonomyNode | null) ?? null)}
      onBackgroundClick={onBackgroundClick}
      nodeCanvasObject={(node, ctx, globalScale) => {
        const n = node as TaxonomyNode & { x: number; y: number };
        const dimmed = dimmedIds?.has(n.id) ?? false;
        ctx.globalAlpha = dimmed ? 0.18 : 1;
        drawNode(n, ctx);
        if (globalScale > SHOW_LABEL_AT) {
          ctx.font = LABEL_FONT;
          ctx.fillStyle = TX_BROWN_FAINT;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          ctx.fillText(n.display_name, n.x, n.y + nodeRadius(n) + 3);
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
  const role = effectiveKind(node);
  const fill = ROLE_FILL[role];
  const radius = nodeRadius(node);
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

