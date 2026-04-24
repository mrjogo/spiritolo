import { useSearchParams } from 'react-router-dom';

type Props = { total: number; pageSize: number };

export function Pagination({ total, pageSize }: Props) {
  const [params, setParams] = useSearchParams();
  const page = parseInt(params.get('page') ?? '1', 10);
  const totalPages = Math.ceil(total / pageSize);

  if (totalPages <= 1) return null;

  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  const goto = (n: number) => {
    const next = new URLSearchParams(params);
    if (n === 1) next.delete('page');
    else next.set('page', String(n));
    setParams(next);
  };

  return (
    <div className="pagination">
      <button disabled={page <= 1} onClick={() => goto(page - 1)}>
        Prev
      </button>
      <span>
        {from}–{to} of {total}
      </span>
      <button disabled={page >= totalPages} onClick={() => goto(page + 1)}>
        Next
      </button>
    </div>
  );
}
