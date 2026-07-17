import { useRef } from 'react';
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

// Phone breakpoint — mirrors the max-width:640px block in pages/ops/ops.css
// that flips this from side-by-side to a stacked master→detail view.
const MOBILE_QUERY = '(max-width: 640px)';

function isMobileViewport(): boolean {
  // matchMedia is undefined under jsdom, so this is false in tests — the
  // scroll-on-select branch below is a real-browser-only affordance.
  return !!window.matchMedia?.(MOBILE_QUERY)?.matches;
}

// Master list left, detail right; selected id lives in the URL (?sel=) so
// every /ops DB browser is `<SplitView list={<DataTable/>} detail={<DetailPane/>}/>`
// with the selection shareable/bookmarkable, mirroring useTaxonomyUrlState.
//
// Layout (flex row, 60/40) lives in ops.css under `.split-view*`, not inline,
// so the mobile stylesheet can restack it. On a phone the two panes stack and
// only one shows at a time: no selection → the list; a selection → the detail
// with a Back control (the `data-has-selection` attribute drives that in CSS).
export function SplitView({ list, detail, paramName = 'sel' }: Props) {
  const [params, setParams] = useSearchParams();
  const selectedId = params.get(paramName);
  const rootRef = useRef<HTMLDivElement>(null);

  function select(id: string) {
    const next = new URLSearchParams(params);
    next.set(paramName, id);
    setParams(next);
    // On a phone the detail replaces the list in place; scroll it up so the
    // Back control and detail heading start at the top rather than wherever
    // the tapped row happened to sit.
    if (isMobileViewport()) {
      rootRef.current?.scrollIntoView({ block: 'start' });
    }
  }

  function clearSelection() {
    const next = new URLSearchParams(params);
    next.delete(paramName);
    setParams(next);
  }

  return (
    <div
      className="split-view"
      data-has-selection={selectedId ? '' : undefined}
      ref={rootRef}
    >
      <div className="split-view__list">{list({ selectedId, select })}</div>
      <div className="split-view__detail">
        {/* Hidden on desktop; on mobile it returns from the detail to the list.
            Only visible when a selection is showing (the pane itself is hidden
            without one), so it never appears over the empty placeholder. */}
        <button type="button" className="split-view__back" onClick={clearSelection}>
          ‹ Back to list
        </button>
        {detail({ selectedId })}
      </div>
    </div>
  );
}

export function DetailPane({ children }: { children: React.ReactNode }) {
  return <div className="detail-pane">{children}</div>;
}
