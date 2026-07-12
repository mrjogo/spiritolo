import { useSearchParams } from 'react-router-dom';

export interface SplitViewListCtx {
  selectedId: string | null;
  select: (id: string) => void;
}

export interface SplitViewDetailCtx {
  selectedId: string | null;
}

interface Props {
  list: (ctx: SplitViewListCtx) => React.ReactNode;
  detail: (ctx: SplitViewDetailCtx) => React.ReactNode;
  /** URL search-param name carrying the selection. Default 'sel'. */
  paramName?: string;
}

// Master list left, detail right; selected id lives in the URL (?sel=) so
// every /ops DB browser is `<SplitView list={<DataTable/>} detail={<DetailPane/>}/>`
// with the selection shareable/bookmarkable, mirroring useTaxonomyUrlState.
export function SplitView({ list, detail, paramName = 'sel' }: Props) {
  const [params, setParams] = useSearchParams();
  const selectedId = params.get(paramName);

  function select(id: string) {
    const next = new URLSearchParams(params);
    next.set(paramName, id);
    setParams(next);
  }

  return (
    <div className="split-view" style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
      <div className="split-view__list" style={{ flex: '1 1 60%', minWidth: 0 }}>
        {list({ selectedId, select })}
      </div>
      <div className="split-view__detail" style={{ flex: '1 1 40%', minWidth: 0 }}>
        {detail({ selectedId })}
      </div>
    </div>
  );
}

export function DetailPane({ children }: { children: React.ReactNode }) {
  return <div className="detail-pane">{children}</div>;
}
