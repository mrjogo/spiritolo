import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Pager } from '../../../ui/Pager';
import { FilterBar, type FilterDimension } from '../../../ui/runs/FilterBar';
import { StatusBadge } from '../../../ui/runs/badges';
import { useRun } from '../../../ui/runs/useRun';
import {
  useEligiblePool,
  useAddRunItems,
  useAddRunItemsByFilter,
  type EligibleRow,
} from '../../../ui/runs/useEligiblePool';
import type { Sort } from '../../../ui/runs/useRunItems';
import {
  buildPFilter,
  emptyFilterState,
  emptySelection,
  toggleSelected,
  setSelected,
  selectAllMatching,
  clearSelection,
  isSelected,
  selectionCount,
  selectedIdList,
  type RunFilterState,
  type Selection,
} from '../../../ui/runs/filter';
import type { FacetOption } from '../../../ui/runs/FilterPopover';
import './runs.css';

const PAGE_SIZE = 50;
const DEFAULT_SORT: Sort = { col: 'last_run', asc: false };

// The entity a run's items point at depends on its stage: the node
// harmonization stages operate on taxonomy nodes, extract on pages, everything
// else on recipes. (Mirrors add_run_items_by_filter's server-side v_etype.)
function entityTypeForStage(stage: string): string {
  if (stage === 'combine-nodes' || stage === 'connect-nodes') return 'taxonomy_node';
  if (stage === 'extract-recipe') return 'page';
  return 'recipe';
}

const SORT_OPTIONS = [
  { col: 'last_run', label: 'Last run' },
  { col: 'title', label: 'Recipe' },
];

// Builds the popover option list for a dimension from its facet map, listing
// every value with its count (including zeros the RPC reports).
function facetOptions(facet: Record<string, number> | undefined): FacetOption[] {
  if (!facet) return [];
  return Object.entries(facet).map(([value, count]) => ({
    value,
    label: value.replace(/_/g, ' '),
    count,
  }));
}

// The Add-tasks surface: browse a stage's eligible pool with JIRA-style
// filters, accumulate a selection that survives filter changes, then add it to
// the draft run. Metered concerns don't live here — this only loads `pending`
// items; starting (and its cost gate) happens back on the run detail.
export function AddTasks() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const jobId = id ? Number(id) : null;

  const { run } = useRun(jobId);
  const stage = run?.stage ?? '';
  const entityType = entityTypeForStage(stage);

  const [filterState, setFilterState] = useState<RunFilterState>(emptyFilterState);
  const [sort, setSort] = useState<Sort>(DEFAULT_SORT);
  const [page, setPage] = useState(1);
  const [selection, setSelection] = useState<Selection>(emptySelection);
  const [viewSelectionOnly, setViewSelectionOnly] = useState(false);

  const pFilter = useMemo(() => buildPFilter(filterState), [filterState]);
  const { rows, total, facets } = useEligiblePool(stage, pFilter, sort, page, PAGE_SIZE);

  const dimensions: FilterDimension[] = [
    { key: 'status', label: 'Status', options: facetOptions(facets.status) },
    { key: 'source', label: 'Source', options: facetOptions(facets.source) },
  ];

  const addByIds = useAddRunItems(jobId ?? 0);
  const addByFilter = useAddRunItemsByFilter(jobId ?? 0);

  const selCount = selectionCount(selection);
  // "View selection" narrows the visible page to the rows currently selected —
  // a client-side lens over the loaded page (the pool RPC has no selected-only
  // mode). Honest and cheap; it doesn't page across the whole selection.
  const visibleRows: EligibleRow[] = viewSelectionOnly
    ? rows.filter((r) => isSelected(selection, r.entity_id))
    : rows;

  const allVisibleSelected = visibleRows.length > 0 && visibleRows.every((r) => isSelected(selection, r.entity_id));

  function onChangeFilter(next: RunFilterState) {
    setFilterState(next);
    setPage(1);
    // NB: selection is deliberately NOT reset here — it survives filter changes.
  }

  function toggleAllVisible() {
    setSelection((prev) => {
      let next = prev;
      for (const r of visibleRows) next = setSelected(next, r.entity_id, !allVisibleSelected);
      return next;
    });
  }

  async function handleAdd() {
    const ids = selectedIdList(selection);
    if (ids === null) {
      await addByFilter.mutateAsync({ job_id: jobId!, p_filter: pFilter });
    } else if (ids.length > 0) {
      await addByIds.mutateAsync({ job_id: jobId!, entity_type: entityType, entity_ids: ids });
    }
    navigate(`/ops/runs/${jobId}`);
  }

  return (
    <div className="ops-add-tasks">
      <div className="runs-ctxbar">
        <Link className="ops-xlink" to={`/ops/runs/${jobId}`}>← Run #{jobId}</Link>
        <span className="runs-ctxbar__t">
          Add tasks <span className="runs-stage-pill">{stage || '…'}</span>
        </span>
        <div className="runs-metrics">
          <div className="runs-metric">
            <div className="runs-metric__n">{(run?.task_count ?? 0).toLocaleString()}</div>
            <div className="runs-metric__l">in run</div>
          </div>
          <div className="runs-metric runs-metric--add">
            <div className="runs-metric__n">+{selCount.toLocaleString()}</div>
            <div className="runs-metric__l">selected</div>
          </div>
        </div>
      </div>

      <div className="runs-panel">
        <FilterBar
          state={filterState}
          dimensions={dimensions}
          sort={sort}
          sortOptions={SORT_OPTIONS}
          onChange={onChangeFilter}
          onSortChange={(s) => { setSort(s); setPage(1); }}
        />

        {selCount > 0 && (
          <div className="runs-selbanner" role="status">
            <b>{selCount.toLocaleString()}</b> selected — kept as you change filters.{' '}
            <button
              type="button"
              className="runs-selbanner__link"
              onClick={() => setSelection(selectAllMatching(total))}
            >
              Select all {total.toLocaleString()} matching
            </button>
            ·
            <button
              type="button"
              className="runs-selbanner__link"
              aria-pressed={viewSelectionOnly}
              onClick={() => setViewSelectionOnly((v) => !v)}
            >
              View selection
            </button>
            ·
            <button
              type="button"
              className="runs-selbanner__link"
              onClick={() => { setSelection(clearSelection()); setViewSelectionOnly(false); }}
            >
              Clear all selected
            </button>
          </div>
        )}

        <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th scope="col" style={{ width: 34 }}>
                <input
                  type="checkbox"
                  aria-label="select all on page"
                  checked={allVisibleSelected}
                  onChange={toggleAllVisible}
                />
              </th>
              <SortableTh label="Recipe" col="title" sort={sort} onSort={setSort} />
              <SortableTh label="Source" col="source" sort={sort} onSort={setSort} />
              <SortableTh label="Status" col="status" sort={sort} onSort={setSort} />
              <SortableTh label="Last run" col="last_run" sort={sort} onSort={setSort} />
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((r) => {
              const sel = isSelected(selection, r.entity_id);
              return (
                <tr key={r.entity_id}>
                  <td data-label="select">
                    <input
                      type="checkbox"
                      aria-label={`select ${r.title}`}
                      checked={sel}
                      onChange={() => setSelection((prev) => toggleSelected(prev, r.entity_id))}
                    />
                  </td>
                  <td data-label="Recipe" className="title">{r.title}</td>
                  <td data-label="Source">{r.source}</td>
                  <td data-label="Status">
                    <StatusBadge status={r.status} detail={r.status_detail} />
                  </td>
                  <td data-label="Last run">{r.last_run_label ?? '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <Pager page={page} pageSize={PAGE_SIZE} total={total} onPage={setPage} unit="matching" />
      </div>

      {selCount > 0 && (
        <div className="runs-addbar" role="region" aria-label="add to run">
          <span>
            <b>{selCount.toLocaleString()}</b> selected to add
          </span>
          <span className="runs-grow" />
          <button
            type="button"
            className="runs-addbar__link"
            onClick={() => { setSelection(clearSelection()); setViewSelectionOnly(false); }}
          >
            Clear
          </button>
          <button
            type="button"
            className="runs-btn--primary"
            disabled={addByIds.isPending || addByFilter.isPending}
            onClick={handleAdd}
          >
            ＋ Add {selCount.toLocaleString()} to run → back to Run #{jobId}
          </button>
        </div>
      )}
    </div>
  );
}

function sortIndicator(sort: Sort, col: string): string {
  if (sort.col !== col) return '';
  return sort.asc ? '↑' : '↓';
}

function SortableTh({
  label, col, sort, onSort,
}: {
  label: string;
  col: string;
  sort: Sort;
  onSort: (s: Sort) => void;
}) {
  const indicator = sortIndicator(sort, col);
  return (
    <th scope="col">
      <button
        type="button"
        className="runs-clearall"
        style={{ textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}
        aria-label={`Sort by ${label}`}
        onClick={() => onSort({ col, asc: sort.col === col ? !sort.asc : false })}
      >
        {label} {indicator && <span aria-hidden>{indicator}</span>}
      </button>
    </th>
  );
}
