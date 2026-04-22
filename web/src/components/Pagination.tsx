import { useSearchParams } from 'react-router-dom';

type Props = { totalPages: number };

export function Pagination({ totalPages }: Props) {
  const [params, setParams] = useSearchParams();
  const page = parseInt(params.get('page') ?? '1', 10);

  if (totalPages <= 1) return null;

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
        Page {page} of {totalPages}
      </span>
      <button disabled={page >= totalPages} onClick={() => goto(page + 1)}>
        Next
      </button>
    </div>
  );
}
