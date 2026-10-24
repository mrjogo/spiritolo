export interface DataTableColumn<T> {
  key: string;
  header: string;
  render?: (row: T) => React.ReactNode;
  width?: number | string;
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  selectable?: boolean;
  selectedIds?: Set<string | number>;
  onSelectionChange?: (ids: (string | number)[]) => void;
  onRowClick?: (row: T) => void;
  /** Show a loading row instead of (an empty) body while the query runs. */
  loading?: boolean;
  /** Message for the empty (loaded, zero-row) state. */
  emptyMessage?: string;
}

// The one table every /ops browser composes over usePagedQuery: columns with
// optional custom cell renderers (StatusPill/CostBadge cells), optional
// checkbox selection (feeds scoped triggers), optional row click. Sticky
// header + an overflow-x:auto wrapper — no ag-grid, no virtualization.
//
// Every <td> carries data-label={header} so the mobile stylesheet can hide
// the <thead> and linearize each row into a labelled card (td::before renders
// the label) — see the max-width:640px block in pages/ops/ops.css.
export function DataTable<T>({
  columns, rows, rowKey, selectable, selectedIds, onSelectionChange, onRowClick,
  loading, emptyMessage = 'Nothing to show.',
}: DataTableProps<T>) {
  const selected = selectedIds ?? new Set<string | number>();
  const colCount = columns.length + (selectable ? 1 : 0);

  function toggle(id: string | number) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    onSelectionChange?.([...next]);
  }

  return (
    <div className="data-table__wrapper" style={{ overflowX: 'auto' }}>
      <table className="data-table">
        <thead style={{ position: 'sticky', top: 0 }}>
          <tr>
            {selectable && <th scope="col" aria-label="select" />}
            {columns.map((c) => (
              <th key={c.key} scope="col" style={{ width: c.width }}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={colCount} className="data-table__state" aria-busy="true">
                <span className="ops-spinner" aria-hidden="true" /> Loading…
              </td>
            </tr>
          ) : rows.length === 0 ? (
            <tr>
              <td colSpan={colCount} className="data-table__state">{emptyMessage}</td>
            </tr>
          ) : (
            rows.map((row) => {
            const id = rowKey(row);
            return (
              <tr
                key={id}
                tabIndex={onRowClick ? 0 : undefined}
                role={onRowClick ? 'button' : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
              >
                {selectable && (
                  <td data-label="select">
                    <input
                      type="checkbox"
                      aria-label={`select row ${id}`}
                      checked={selected.has(id)}
                      onChange={() => toggle(id)}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </td>
                )}
                {columns.map((c) => (
                  <td key={c.key} data-label={c.header}>
                    {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? '')}
                  </td>
                ))}
              </tr>
            );
          })
          )}
        </tbody>
      </table>
    </div>
  );
}
