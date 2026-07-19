import { describe, it, expect } from 'vitest';
import {
  emptyFilterState,
  buildPFilter,
  toggleFilterValue,
  setFilterValues,
  clearFilters,
  activeFilterCount,
  emptySelection,
  toggleSelected,
  setSelected,
  selectAllMatching,
  clearSelection,
  isSelected,
  selectionCount,
  selectedIdList,
  type RunFilterState,
} from './filter';

describe('buildPFilter', () => {
  it('omits empty dimensions rather than sending []', () => {
    expect(buildPFilter(emptyFilterState)).toEqual({});
  });

  it('OR-within-a-key: a dimension carries its full value list', () => {
    const state: RunFilterState = { status: ['flagged', 'failed'], source: [] };
    expect(buildPFilter(state)).toEqual({ status: ['flagged', 'failed'] });
  });

  it('AND-across-keys: distinct dimensions coexist in one p_filter object', () => {
    const state: RunFilterState = {
      status: ['flagged', 'failed'],
      source: ['diffordsguide'],
      code_version_before: 'v5',
      search: 'negroni',
    };
    expect(buildPFilter(state)).toEqual({
      status: ['flagged', 'failed'],
      source: ['diffordsguide'],
      code_version_before: 'v5',
      search: 'negroni',
    });
  });

  it('trims and drops a blank search', () => {
    expect(buildPFilter({ ...emptyFilterState, search: '   ' })).toEqual({});
    expect(buildPFilter({ ...emptyFilterState, search: '  gin ' })).toEqual({ search: 'gin' });
  });
});

describe('filter state reducers', () => {
  it('toggleFilterValue adds then removes a value within a dimension', () => {
    let s = emptyFilterState;
    s = toggleFilterValue(s, 'status', 'flagged');
    expect(s.status).toEqual(['flagged']);
    s = toggleFilterValue(s, 'status', 'failed');
    expect(s.status).toEqual(['flagged', 'failed']);
    s = toggleFilterValue(s, 'status', 'flagged');
    expect(s.status).toEqual(['failed']);
  });

  it('setFilterValues replaces a whole dimension (popover Apply)', () => {
    const s = setFilterValues(emptyFilterState, 'source', ['punch', 'diffordsguide']);
    expect(s.source).toEqual(['punch', 'diffordsguide']);
  });

  it('activeFilterCount counts constrained dimensions, and clearFilters resets', () => {
    const s: RunFilterState = {
      status: ['flagged'],
      source: ['punch'],
      code_version_before: 'v5',
      search: 'gin',
    };
    expect(activeFilterCount(s)).toBe(4);
    expect(activeFilterCount(clearFilters())).toBe(0);
  });
});

describe('persistent selection', () => {
  it('accumulates explicit ids and counts them', () => {
    let sel = emptySelection;
    sel = toggleSelected(sel, 'a');
    sel = toggleSelected(sel, 'b');
    expect(isSelected(sel, 'a')).toBe(true);
    expect(isSelected(sel, 'c')).toBe(false);
    expect(selectionCount(sel)).toBe(2);
    expect(selectedIdList(sel)).toEqual(['a', 'b']);
  });

  it('SURVIVES a filter change: re-filtering does not reset selection', () => {
    // Select two rows under filter view A.
    let sel = toggleSelected(toggleSelected(emptySelection, 'a'), 'b');
    // Change the filter (a brand-new p_filter). buildPFilter never takes the
    // selection as input, so the selection object is untouched by re-filtering.
    const viewA = buildPFilter({ status: ['flagged'], source: [] });
    const viewB = buildPFilter({ status: ['failed'], source: ['punch'] });
    expect(viewA).not.toEqual(viewB);
    // Select another row under filter view B — the earlier picks remain.
    sel = toggleSelected(sel, 'c');
    expect(selectionCount(sel)).toBe(3);
    expect(selectedIdList(sel)).toEqual(['a', 'b', 'c']);
  });

  it('select-all-matching reports N and returns null id-list (RPC re-derives)', () => {
    const sel = selectAllMatching(1139);
    expect(selectionCount(sel)).toBe(1139);
    expect(selectedIdList(sel)).toBeNull();
  });

  it('un-checking a row while all-matching subtracts it as an exception', () => {
    let sel = selectAllMatching(1139);
    sel = toggleSelected(sel, 'x');
    expect(isSelected(sel, 'x')).toBe(false);
    expect(selectionCount(sel)).toBe(1138);
  });

  it('setSelected is idempotent and clearSelection empties everything', () => {
    let sel = setSelected(emptySelection, 'a', true);
    sel = setSelected(sel, 'a', true);
    expect(selectionCount(sel)).toBe(1);
    expect(selectionCount(clearSelection())).toBe(0);
  });
});
