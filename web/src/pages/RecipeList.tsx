import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { supabase } from '../supabase';
import { Pagination } from '../components/Pagination';
import { buildSearchFilters } from '../searchQuery';
import type { RecipeListItem } from '../types';

const PAGE_SIZE = 50;

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'loaded'; rows: RecipeListItem[]; total: number };

export function RecipeList() {
  const [params, setSearchParams] = useSearchParams();
  const page = Math.max(1, parseInt(params.get('page') ?? '1', 10) || 1);
  const q = params.get('q') ?? '';
  const [inputValue, setInputValue] = useState(q);
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    const from = (page - 1) * PAGE_SIZE;
    const to = from + PAGE_SIZE - 1;

    let query = supabase
      .from('recipes_public')
      .select('id, site, name, image_url', { count: 'exact' });

    const { orFilters } = buildSearchFilters(q);
    for (const f of orFilters) {
      query = query.or(f);
    }

    query
      .order('name', { nullsFirst: false })
      .range(from, to)
      .then(({ data, count, error }) => {
        if (cancelled) return;
        if (error) {
          setState({ status: 'error', message: error.message });
          return;
        }
        setState({
          status: 'loaded',
          rows: (data ?? []) as RecipeListItem[],
          total: count ?? 0,
        });
      });

    return () => {
      cancelled = true;
    };
  }, [page, q]);

  // Keep input in sync if URL changes externally (back/forward navigation).
  useEffect(() => {
    setInputValue(q);
  }, [q]);

  // Debounce inputValue → URL.
  useEffect(() => {
    if (inputValue === q) return; // no-op when already in sync
    const handle = setTimeout(() => {
      const next = new URLSearchParams(params);
      if (inputValue === '') next.delete('q');
      else next.set('q', inputValue);
      next.set('page', '1');
      setSearchParams(next, { replace: true });
    }, 250);
    return () => clearTimeout(handle);
  }, [inputValue, q, params, setSearchParams]);

  if (state.status === 'error') {
    return (
      <div className="page error-page">
        <h1>Couldn't load recipes</h1>
        <p>{state.message}</p>
      </div>
    );
  }

  return (
    <div className="page">
      <h1>Recipes</h1>
      <div className="recipe-list__search">
        <input
          type="search"
          aria-label="Search recipes"
          placeholder="Search recipes…"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
        />
      </div>
      {state.status === 'loading' ? (
        <div>Loading…</div>
      ) : (
        <>
          <Pagination total={state.total} pageSize={PAGE_SIZE} />
          {state.rows.length === 0 ? (
            <p className="recipe-list__empty">No recipes yet — extract some and they'll show up here.</p>
          ) : (
            <ul className="recipe-list">
              {state.rows.map((r) => (
                <li key={r.id} className="recipe-list__item">
                  <Link to={`/recipes/${r.id}`}>
                    {r.image_url && (
                      <img src={r.image_url} alt="" className="recipe-list__thumb" />
                    )}
                    <div className="recipe-list__meta">
                      <div className="recipe-list__name">{r.name ?? 'Untitled'}</div>
                      <div className="recipe-list__site">{r.site}</div>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <Pagination total={state.total} pageSize={PAGE_SIZE} />
        </>
      )}
    </div>
  );
}
