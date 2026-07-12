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
}

// The one table every /ops browser composes over usePagedQuery: columns with
// optional custom cell renderers (StatusPill/CostBadge cells), optional
// checkbox selection (feeds scoped triggers), optional row click. Sticky
// header + an overflow-x:auto wrapper — no ag-grid, no virtualization.
export function DataTable<T>({
  columns, rows, rowKey, selectable, selectedIds, onSelectionChange, onRowClick,
}: DataTableProps<T>) {
  const selected = selectedIds ?? new Set<string | number>();

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
          {rows.map((row) => {
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
                  <td>
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
                  <td key={c.key}>
                    {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? '')}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
