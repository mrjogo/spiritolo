// The run-selection filter model, kept pure (no React, no supabase) so it's
// unit-testable and shared by both surfaces that filter a stage's entities:
// the Add-tasks eligible pool and the Run-detail task list.
//
// Two independent pieces live here on purpose:
//   1. buildPFilter — turns the UI filter state into the `p_filter` jsonb the
//      eligible_pool / run_items RPCs take. Arrays are OR *within* a key; keys
//      AND *across* each other (the RPC applies that semantics).
//   2. the Selection reducers — a selection that SURVIVES filter changes. The
//      selection is stored separately from the filter state, so re-filtering
//      the table (a new p_filter) never touches what's already selected. This
//      is the "kept as you change filters" banner in the Add-tasks mockup.

import type { PostgrestFilter } from '../hooks/usePagedQuery';

// ---------------------------------------------------------------------------
// Filter state → p_filter
// ---------------------------------------------------------------------------

/** The multi-select filter dimensions that hold string[] (OR within each). */
export type MultiDimension = 'status' | 'source';

export interface RunFilterState {
  status: string[];
  source: string[];
  /** "processed before code version v<n>" — a single scalar, not a list. */
  code_version_before?: string;
  /** Free-text title / ingredient search. */
  search?: string;
}

/** The jsonb the eligible_pool / run_items RPCs receive as `p_filter`. Empty
 *  dimensions are omitted entirely rather than sent as `[]`, so the RPC's
 *  "key present ⇒ constrain" test stays simple. */
export interface PFilter {
  status?: string[];
  source?: string[];
  code_version_before?: string;
  search?: string;
}

export const emptyFilterState: RunFilterState = { status: [], source: [] };

export function buildPFilter(state: RunFilterState): PFilter {
  const f: PFilter = {};
  if (state.status.length > 0) f.status = [...state.status];
  if (state.source.length > 0) f.source = [...state.source];
  if (state.code_version_before) f.code_version_before = state.code_version_before;
  const search = state.search?.trim();
  if (search) f.search = search;
  return f;
}

/** Toggle one option within a multi-select dimension (OR-within-a-key). */
export function toggleFilterValue(
  state: RunFilterState,
  dimension: MultiDimension,
  value: string,
): RunFilterState {
  const current = state[dimension];
  const next = current.includes(value)
    ? current.filter((v) => v !== value)
    : [...current, value];
  return { ...state, [dimension]: next };
}

/** Replace a whole dimension at once (a popover "Apply"). */
export function setFilterValues(
  state: RunFilterState,
  dimension: MultiDimension,
  values: string[],
): RunFilterState {
  return { ...state, [dimension]: [...values] };
}

export function clearFilters(): RunFilterState {
  return { status: [], source: [] };
}

/** How many distinct dimensions are constrained — drives the "Clear filters"
 *  affordance and the active-pill count. */
export function activeFilterCount(state: RunFilterState): number {
  let n = 0;
  if (state.status.length > 0) n += 1;
  if (state.source.length > 0) n += 1;
  if (state.code_version_before) n += 1;
  if (state.search?.trim()) n += 1;
  return n;
}

/** A p_filter also renders as a PostgREST filter array for any view-backed
 *  read that isn't going through the RPC (kept for parity with FilterBar's
 *  scope.where invariant). OR-within-a-key becomes an `in` op. */
export function pFilterToPostgrest(f: PFilter): PostgrestFilter[] {
  const out: PostgrestFilter[] = [];
  if (f.status?.length) out.push({ col: 'status', op: 'in', value: f.status });
  if (f.source?.length) out.push({ col: 'source', op: 'in', value: f.source });
  if (f.code_version_before) out.push({ col: 'code_version', op: 'lt', value: f.code_version_before });
  if (f.search) out.push({ col: 'title', op: 'ilike', value: `%${f.search}%` });
  return out;
}

// ---------------------------------------------------------------------------
// Persistent selection (survives filter changes)
// ---------------------------------------------------------------------------

// The selection is an accumulator that outlives any single filter view:
//   - `ids`      : explicitly-checked ids (accumulated across filter passes)
//   - `allMatching` + `matchingTotal` : the "Select all N matching" mode
//   - `excluded` : ids un-checked while allMatching is on (exceptions)
//
// Selecting rows from filter view A, then changing to view B and selecting
// more, keeps both — because none of these reducers take the filter as input.
export interface Selection {
  ids: Set<string>;
  allMatching: boolean;
  matchingTotal: number;
  excluded: Set<string>;
}

export const emptySelection: Selection = {
  ids: new Set(),
  allMatching: false,
  matchingTotal: 0,
  excluded: new Set(),
};

export function isSelected(sel: Selection, id: string): boolean {
  if (sel.allMatching) return !sel.excluded.has(id);
  return sel.ids.has(id);
}

export function selectionCount(sel: Selection): number {
  if (sel.allMatching) return Math.max(0, sel.matchingTotal - sel.excluded.size);
  return sel.ids.size;
}

export function toggleSelected(sel: Selection, id: string): Selection {
  if (sel.allMatching) {
    const excluded = new Set(sel.excluded);
    if (excluded.has(id)) excluded.delete(id);
    else excluded.add(id);
    return { ...sel, excluded };
  }
  const ids = new Set(sel.ids);
  if (ids.has(id)) ids.delete(id);
  else ids.add(id);
  return { ...sel, ids };
}

export function setSelected(sel: Selection, id: string, on: boolean): Selection {
  if (isSelected(sel, id) === on) return sel;
  return toggleSelected(sel, id);
}

/** Turn on "select all N matching". Drops the explicit-id and exclusion sets
 *  so the count reads exactly N. */
export function selectAllMatching(total: number): Selection {
  return { ids: new Set(), allMatching: true, matchingTotal: total, excluded: new Set() };
}

export function clearSelection(): Selection {
  return { ids: new Set(), allMatching: false, matchingTotal: 0, excluded: new Set() };
}

/** The concrete id list to hand an RPC, or `null` when "all matching" is on
 *  (the RPC re-derives the set from the filter — add_run_items_by_filter). */
export function selectedIdList(sel: Selection): string[] | null {
  if (sel.allMatching) return null;
  return [...sel.ids];
}
