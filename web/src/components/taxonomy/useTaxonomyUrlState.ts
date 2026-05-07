import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { TaxonomyNode } from './shapeData';
import type { EdgeRef } from './EdgeCard';

export interface UseTaxonomyUrlStateArgs {
  nodes: TaxonomyNode[];
}

export interface UseTaxonomyUrlStateReturn {
  focusedId: number | null;
  focusedEdge: EdgeRef | null;
  setFocusedId: (id: number | null) => void;
  setFocusedEdge: (edge: EdgeRef | null) => void;
  clearFocus: () => void;
}

const EDGE_SEP = '~';

export function useTaxonomyUrlState({
  nodes,
}: UseTaxonomyUrlStateArgs): UseTaxonomyUrlStateReturn {
  const [searchParams, setSearchParams] = useSearchParams();
  const bySlug = useMemo(
    () => new Map(nodes.map((n) => [n.slug, n])),
    [nodes],
  );
  const byId = useMemo(
    () => new Map(nodes.map((n) => [n.id, n])),
    [nodes],
  );

  const nodeParam = searchParams.get('node');
  const edgeParam = searchParams.get('edge');

  const focusedId = useMemo<number | null>(() => {
    if (!nodeParam) return null;
    const node = bySlug.get(nodeParam);
    return node ? node.id : null;
  }, [nodeParam, bySlug]);

  const focusedEdge = useMemo<EdgeRef | null>(() => {
    if (!edgeParam) return null;
    const [parentSlug, childSlug] = edgeParam.split(EDGE_SEP);
    if (!parentSlug || !childSlug) return null;
    const source = bySlug.get(parentSlug);
    const target = bySlug.get(childSlug);
    if (!source || !target) return null;
    return { source, target };
  }, [edgeParam, bySlug]);

  const setFocusedId = useCallback(
    (id: number | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('edge');
          if (id == null) {
            next.delete('node');
            return next;
          }
          const node = byId.get(id);
          if (!node) {
            next.delete('node');
            return next;
          }
          next.set('node', node.slug);
          return next;
        },
        { replace: false },
      );
    },
    [byId, setSearchParams],
  );

  const setFocusedEdge = useCallback(
    (edge: EdgeRef | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('node');
          if (edge == null) {
            next.delete('edge');
            return next;
          }
          next.set('edge', `${edge.source.slug}${EDGE_SEP}${edge.target.slug}`);
          return next;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );

  const clearFocus = useCallback(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('node');
        next.delete('edge');
        return next;
      },
      { replace: false },
    );
  }, [setSearchParams]);

  return { focusedId, focusedEdge, setFocusedId, setFocusedEdge, clearFocus };
}
