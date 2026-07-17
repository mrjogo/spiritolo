interface PagerProps {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
  unit?: string;
}

// Prev / range-of-total / Next. Buttons disable at the ends; the range label
// always shows, so a single-page result still reads "1–N of N". Pairs with
// usePagedQuery (server-side range), so only one page of rows is ever fetched.
export function Pager({ page, pageSize, total, onPage, unit = 'rows' }: PagerProps) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(Math.max(1, page), pages);
  const from = total === 0 ? 0 : (current - 1) * pageSize + 1;
  const to = Math.min(current * pageSize, total);

  return (
    <div className="ops-pager" role="navigation" aria-label="pagination">
      <button type="button" onClick={() => onPage(current - 1)} disabled={current <= 1}>
        ← Prev
      </button>
      <span className="ops-pager__count">
        {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()} {unit}
      </span>
      <button type="button" onClick={() => onPage(current + 1)} disabled={current >= pages}>
        Next →
      </button>
    </div>
  );
}
