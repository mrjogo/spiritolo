import { describe, it, expect, beforeAll } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useTaxonomyUrlState } from './useTaxonomyUrlState';
import { viewRowsToGraph, type TaxonomyViewRow, type TaxonomyNode } from './shapeData';

const ROWS: TaxonomyViewRow[] = [
  {
    id: 1, slug: 'gin', display_name: 'Gin',
    node_kind: null, default_role: 'base_spirit',
    is_cluster_node: true, is_defining_garnish: false,
    parent_ids: [], child_ids: [2], aliases: [], recipe_count: 0,
  },
  {
    id: 2, slug: 'london_dry_gin', display_name: 'London Dry Gin',
    node_kind: 'expression', default_role: 'base_spirit',
    is_cluster_node: false, is_defining_garnish: false,
    parent_ids: [1], child_ids: [], aliases: [], recipe_count: 0,
  },
];

let NODES: TaxonomyNode[] = [];

beforeAll(() => {
  NODES = viewRowsToGraph(ROWS).nodes;
});

function wrapperWithUrl(initial: string) {
  return function W({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[initial]}>{children}</MemoryRouter>;
  };
}

describe('useTaxonomyUrlState — read side', () => {
  it('initializes focusedId from ?node=<slug>', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?node=gin'),
    });
    expect(result.current.focusedId).toBe(1);
    expect(result.current.focusedEdge).toBeNull();
  });

  it('initializes focusedEdge from ?edge=<parent>~<child>', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?edge=gin~london_dry_gin'),
    });
    expect(result.current.focusedId).toBeNull();
    expect(result.current.focusedEdge).not.toBeNull();
    expect(result.current.focusedEdge?.source.slug).toBe('gin');
    expect(result.current.focusedEdge?.target.slug).toBe('london_dry_gin');
  });

  it('returns null focus for unresolvable ?node=<slug>', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?node=missing'),
    });
    expect(result.current.focusedId).toBeNull();
    expect(result.current.focusedEdge).toBeNull();
  });

  it('returns null focus for malformed ?edge=', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?edge=gin'),
    });
    expect(result.current.focusedEdge).toBeNull();
  });
});

describe('useTaxonomyUrlState — write side', () => {
  it('setFocusedId writes ?node=<slug> and clears any ?edge', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?edge=gin~london_dry_gin'),
    });
    act(() => { result.current.setFocusedId(2); });
    expect(result.current.focusedId).toBe(2);
    expect(result.current.focusedEdge).toBeNull();
  });

  it('setFocusedEdge writes ?edge=<a>~<b> and clears any ?node', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?node=gin'),
    });
    const edge = {
      source: NODES.find((n) => n.slug === 'gin')!,
      target: NODES.find((n) => n.slug === 'london_dry_gin')!,
    };
    act(() => { result.current.setFocusedEdge(edge); });
    expect(result.current.focusedId).toBeNull();
    expect(result.current.focusedEdge?.source.slug).toBe('gin');
    expect(result.current.focusedEdge?.target.slug).toBe('london_dry_gin');
  });

  it('clearFocus removes both params', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?node=gin'),
    });
    act(() => { result.current.clearFocus(); });
    expect(result.current.focusedId).toBeNull();
    expect(result.current.focusedEdge).toBeNull();
  });

  it('setFocusedId(null) clears the node param', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?node=gin'),
    });
    act(() => { result.current.setFocusedId(null); });
    expect(result.current.focusedId).toBeNull();
  });
});
