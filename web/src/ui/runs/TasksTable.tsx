import { DataTable, type DataTableColumn } from '../DataTable';
import { Pager } from '../Pager';
import { WhyAddedBadge, TaskStateChip } from './badges';
import { RUN_STATUS_CHIPS, batchMode } from './tasksTableModel';
import type { RunItem } from './useRunItems';
import type { RunState, ApplyMode } from './useRun';

interface Props {
  runState: RunState;
  applyMode: ApplyMode;
  items: RunItem[];
  total: number;
  /** status → count from run_items_facets, for the chip counts. */
  statusFacets: Record<string, number>;
  activeStatus: string | null;
  onStatus: (status: string | null) => void;
  search: string;
  onSearch: (v: string) => void;
  page: number;
  pageSize: number;
  onPage: (p: number) => void;
  selectedIds: Set<string>;
  onSelectionChange: (ids: string[]) => void;
  onRemove: (ids: string[]) => void;
  onApply: (ids: string[]) => void;
}

const COLUMNS: DataTableColumn<RunItem>[] = [
  { key: 'title', header: 'Recipe' },
  { key: 'why_added', header: 'Why added', render: (r) => <WhyAddedBadge why={r.why_added} /> },
  { key: 'source', header: 'Source' },
  { key: 'task_state', header: 'Task state', render: (r) => <TaskStateChip state={r.task_state} /> },
];

export function TasksTable({
  runState, applyMode, items, total, statusFacets, activeStatus, onStatus,
  search, onSearch, page, pageSize, onPage, selectedIds, onSelectionChange,
  onRemove, onApply,
}: Props) {
  const mode = batchMode(runState, applyMode);
  const selectedList = [...selectedIds];
  const hasSelection = selectedList.length > 0;

  function chipCount(key: string | null): number {
    if (key === null) return total;
    return statusFacets[key] ?? 0;
  }

  return (
    <div className="runs-tasks">
      <div className="runs-tasksbar">
        <h2>
          Tasks <span className="runs-meta" style={{ fontWeight: 400 }}>· {total.toLocaleString()}</span>
        </h2>
        <span className="runs-grow" />
        <div className="runs-chipset" role="group" aria-label="task status filter">
          {RUN_STATUS_CHIPS.map((chip) => {
            const on = activeStatus === chip.key;
            return (
              <button
                key={chip.label}
                type="button"
                className="runs-chip"
                aria-pressed={on}
                onClick={() => onStatus(chip.key)}
              >
                {chip.label} <span className="runs-chip__c">{chipCount(chip.key).toLocaleString()}</span>
              </button>
            );
          })}
        </div>
        <input
          type="search"
          aria-label="search in run"
          placeholder="Search in run…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
        />
      </div>

      {hasSelection && (
        <div className="runs-batchbar" role="region" aria-label="task selection actions">
          <span>
            <b>{selectedList.length.toLocaleString()}</b> tasks selected
            {mode === 'inspect' && <span> · inspecting</span>}
          </span>
          <span className="runs-grow" />
          {mode === 'remove' && (
            <button type="button" className="runs-btn--danger" onClick={() => onRemove(selectedList)}>
              Remove from run
            </button>
          )}
          {mode === 'apply' && (
            <button type="button" className="runs-btn--primary" onClick={() => onApply(selectedList)}>
              Apply {selectedList.length.toLocaleString()}
            </button>
          )}
          <button type="button" onClick={() => onSelectionChange([])}>
            Clear
          </button>
        </div>
      )}

      <div className="runs-panel">
        <DataTable
          columns={COLUMNS}
          rows={items}
          rowKey={(r) => r.item_id}
          selectable
          selectedIds={selectedIds as Set<string | number>}
          onSelectionChange={(ids) => onSelectionChange(ids.map(String))}
        />
      </div>
      <Pager page={page} pageSize={pageSize} total={total} onPage={onPage} unit="tasks" />
    </div>
  );
}
