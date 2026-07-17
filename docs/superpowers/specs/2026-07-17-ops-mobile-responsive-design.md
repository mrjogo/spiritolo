# /ops mobile-responsive design

**Date:** 2026-07-17
**Status:** approved (design), pending implementation plan

## Goal

Make the `/ops` console fully usable on a phone. Today the app has **zero
`@media` queries** — the viewport meta tag is present so text reflows, but
every layout is pinned to desktop widths. An admin should be able to do all
their day-to-day ops work (review & approve, trigger & monitor runs, browse &
inspect data) from a phone, and it should look baseline-nice, not just
functional.

## Scope

**In:** the `/ops` console only — the tab-bar shell (`OpsLayout`) and its seven
pages (Dashboard, Recipes, Stage runs, Audit log, Clusters, Exports, Reviews),
plus the shared primitives they compose (`SplitView`, `DataTable`, `FilterBar`,
`TriggerBar`, `ReviewCard`, `JsonView`, `CostConfirmModal`/`ModalShell`) and the
shared site `Header` (light touch, since it's rendered above every ops page).

**Out:** the Taxonomy curation page (a mouse/hover-centric force-graph canvas —
a substantially larger, separate effort) and the public Recipe list/detail
pages (already mostly single-column). No behavior/data changes — layout and
styling only.

## Approach

**CSS-first, minimal structural change.** One phone breakpoint
(`max-width: 640px`) added to `web/src/pages/ops/ops.css`, plus small TSX edits
where inline styles or missing attributes block a media query from doing its
job. No new dependencies, no JS resize listeners, one code path per component.
Desktop rendering is unchanged.

Rejected alternatives:

- **JS `useMediaQuery` hook** switching component trees — adds
  re-render-on-resize and two code paths per component to keep in sync; not
  warranted here.
- **Adopt Tailwind / a CSS framework** — large invasive rewrite of a small,
  deliberate stylesheet.

**Breakpoint:** a single `@media (max-width: 640px)` block. Below it = touch-first
mobile treatment; at/above it = the current desktop layout, untouched. Large
phones in landscape (~740px+) fall into the desktop layout, which has room; this
is intentional and keeps the CSS simple.

**Design intent:** keep the existing "functional light ops" visual language.
Mobile changes are touch-first — bigger tap targets, phone-native master→detail
navigation, cards instead of horizontally-scrolling tables, and no iOS
focus-zoom.

## The seven pieces

### 1. Tab bar → horizontal scroll strip

`OpsLayout`'s 7 nav tabs currently wrap to 2–3 rows on a phone (they're a
`flex-wrap: wrap` row). Below 640px they become a **single swipeable strip**:
`flex-wrap: nowrap; overflow-x: auto`, larger tap padding, an edge-fade to hint
scrollability, scrollbar hidden, active tab scrolled into view. Reclaims vertical
space on a short viewport. **CSS-only** (the nav already has a `.ops > nav`
hook). *Decision:* scroll strip over wrapping grid (approved).

### 2. Tables → stacked cards

`web/src/ui/DataTable.tsx`: add `data-label={c.header}` to every data `<td>`,
and a label to the optional select-checkbox cell (currently `aria-label="select"`
only, no header — no page uses `selectable` today, but the card layout must not
break if one does). Below 640px, in `ops.css`:

- `.ops .data-table thead { display: none }`
- table / tbody / tr / td → `display: block` (tr = bordered card with spacing;
  td = a `label → value` flex row using `td::before { content: attr(data-label) }`)
- clickable rows (`tr[role="button"]`) get a `›` chevron affordance
- the existing `overflow-x: auto` wrapper is harmless in card mode (no
  horizontal overflow); left as-is

This is **CSS + one attribute** and applies to all five table browsers at once
(Recipes, Stage runs, Audit log, Clusters, Exports).

### 3. Split view → master→detail navigation

`web/src/ui/SplitView.tsx` is a fixed 60/40 flex set via **inline styles**
(inline styles win over stylesheet rules, so a media query can't override them).
Change:

- Lift the inline `display:flex; gap; align-items` and the list/detail
  `flex` ratios into CSS classes (`.ops .split-view`, `.split-view__list`,
  `.split-view__detail`) so the media query can restack them. Desktop values
  identical to today.
- The selected id already lives in the URL (`?sel=`). Set a
  `data-has-selection` attribute on the `.split-view` root reflecting it.
- Add a mobile-only `‹ Back to list` button at the top of the detail wrapper
  (rendered always, hidden on desktop via CSS) that clears `?sel=`.
- On `select`, if `matchMedia('(max-width: 640px)').matches`, scroll the split
  view into view so the detail (with its Back button) starts at the top.

Media query behavior below 640px:

- `.ops .split-view { flex-direction: column }`
- no selection → show list, hide detail:
  `.split-view:not([data-has-selection]) .split-view__detail { display: none }`
- selection present → hide list, show detail:
  `.split-view[data-has-selection] .split-view__list { display: none }`

No `useMediaQuery` hook: JS only sets a data attribute it already knows and does
one guarded `scrollIntoView`; CSS owns the layout switch. On desktop the Back
button is hidden and clearing `?sel=` just returns the detail placeholder — no
change.

Known minor: on mobile, the page's `FilterBar`/`Pager` (siblings above
`SplitView`, owned by each page, not by `SplitView`) remain above the detail
view. The `scrollIntoView` on select scrolls them out of the way. Acceptable;
avoids restructuring every page.

### 4. Filters → stacked, full-width, no zoom

Three filter surfaces stack full-width below 640px:

- `FilterBar` (`web/src/ui/FilterBar.tsx`) — already `flex-wrap: wrap`; add
  mobile CSS making its `<select>` and search `<input>` full-width; chips wrap
  below.
- The inline `role="group"` filter rows in `StageRunsBrowser.tsx` (stage /
  outcome / version) and `AuditLogBrowser.tsx` (actor / table) are
  non-wrapping inline flex → give each a shared class (e.g. `.ops-filters`) and
  let CSS wrap + full-width them on mobile. (Small per-file edit to add the
  className.)
- All `.ops` inputs/selects get `font-size: 16px` below 640px to prevent
  Safari's focus-zoom.

### 5. Touch targets

Below 640px, `.ops button`, `.ops select`, `.ops input` min-height 32px → ~44px.
This automatically covers `TriggerBar`'s Run buttons, the Pager buttons, and the
`ReviewCard` Resolve/Dismiss buttons (all `.ops`-scoped). `ReviewCard`'s JSON
textarea has an inline `fontSize: 12` (would trigger iOS zoom and can't be
media-queried) → move its styling to a `.review-card textarea` CSS rule so the
16px mobile rule applies; also let the `.review-card` header row
(origin/stage/entity) wrap.

### 6. Detail content that overflows

`web/src/ui/JsonView.tsx` has classnames (`json-view__leaf`, `__key`, `__value`,
`__node`, `__children`, `__summary`, `__toggle`) but **no CSS at all** — deep
JSON-LD / audit before-after diffs will blow out the viewport width (each nesting
level adds `padding-left: 16px`, and long URL/image string values don't break).
Add CSS:

- leaf/summary values: `overflow-wrap: anywhere` so long tokens wrap
- reduce the per-level indent on mobile
- the JSON block scrolls within `.detail-pane` (`overflow-x: auto`) rather than
  the page
- long URLs in detail-pane `<p>`s get `word-break`

`.detail-pane` padding trims slightly on mobile.

### 7. Modals fit the screen

`CostConfirmModal` (the metered-cost approval gate — a priority phone task) uses
`ModalShell` → `.tx-modal`. Correction after reading the code: `.tx-modal`
(in `taxonomy.css`) is **already** `width: calc(100vw - 48px)` capped at
`max-width: 400px`, so it is already mobile-width-safe — it only lacks a
`max-height`/scroll for very short screens, and its `.tx-input`/`.tx-select`
are 14px (iOS focus-zoom).

Also note: `taxonomy.css` is imported **only** by the lazy Taxonomy page, not
globally and not on the `/ops` route; only `styles.css` + `tokens.css` are
global and `ops.css` loads with `OpsLayout`. **The adversarial review confirmed
this is worse than "lacks a max-height": the modal's *entire* base styling
(`.tx-modal` panel, `.tx-input`, `.tx-btn`, `.tx-field*`) lives in the taxonomy
chunk, so on a fresh `/ops` session the cost-approval modal renders unstyled —
and half those rules pull deco tokens (`--tx-gold` etc.) scoped to
`.taxonomy-page`, so merely relocating them wouldn't resolve.** So this pass
gives the modal an **ops-native baseline** scoped under `.ops` in `ops.css`: a
plain white card on `--ops-*` tokens (panel + title + `.tx-field`/`.tx-input`/
`.tx-form-actions`), sized `calc(100vw - 40px)`/`max-width: 420px` with a mobile
`max-height` + internal scroll. Scoped to `.ops`, so the taxonomy deco modal is
untouched; works on both viewports; no `taxonomy.css` edit. (A fuller shared
form-kit extraction is a separate, cross-cutting follow-up.)

### Dashboard (no structural change)

`Dashboard.tsx` uses `grid-template-columns: repeat(auto-fill, minmax(260px,
1fr))` → collapses to one column on a phone for free. Only the shared
touch-target polish (piece 5) applies to its `StageCard` `TriggerBar` button.

### Site header (light touch)

`web/src/styles.css` `.site-header` (brand + nav + user + Sign out) is shared
across the whole authed app. Tighten paddings/gaps below 640px so it stays a
single tidy row and the Sign-out button is a comfortable tap target. Conservative
— this is chrome above every page, ops and non-ops alike.

## Files touched (~7)

| File | Change |
|---|---|
| `web/src/pages/ops/ops.css` | The bulk: the `@media (max-width: 640px)` block (nav strip, table→cards, split-view stacking, filters, touch sizes, json-view, detail-pane, pager) + lifting SplitView's base flex into classes |
| `web/src/ui/SplitView.tsx` | Remove inline layout styles → classes; add `data-has-selection`, mobile Back button, guarded `scrollIntoView` on select |
| `web/src/ui/DataTable.tsx` | Add `data-label` to cells; label the select cell |
| `web/src/components/reviews/ReviewCard.tsx` | Move textarea styling inline→CSS; allow header row to wrap |
| `web/src/pages/ops/StageRunsBrowser.tsx` | Add a class to the inline filter group so it wraps on mobile |
| `web/src/pages/ops/AuditLogBrowser.tsx` | Same |
| `web/src/pages/ops/OpsLayout.tsx` | Add nav ref + active-tab-into-view (mobile-gated) |
| `web/src/styles.css` | `.site-header` mobile tightening |

`taxonomy.css` is **not** touched (see piece 7). No new dependencies.

## Testing

- Existing Vitest suites (`web/src/**/*.test.tsx`) must keep passing — the DOM
  structure is preserved (same table/rows, same SplitView children); only
  classes/attributes/CSS are added.
- Add coverage:
  - `DataTable` emits `data-label` on cells (the hook the card layout relies on).
  - `SplitView` renders a Back control that clears the selection param, and sets
    `data-has-selection` when `?sel=` is present.
- Manual/visual check at ~390px (portrait phone) across all seven pages,
  including: table→card rendering, tap-row→detail→Back, the cost-confirm modal,
  a deep JSON-LD detail pane, and filter stacking. (A showboat walkthrough with
  Playwright at a mobile viewport is a good proof artifact — optional.)

## Adversarial review outcome

A multi-lens review (CSS-specificity / regression / a11y, each finding
independently verified) ran over the committed diff. 7 raw findings → 3
confirmed, 4 refuted (e.g. FilterChips 44px was a dead path — chips don't render
inside `.ops`; the stuck-list overflow can't trigger — entity ids aren't
unbreakable; the `.split-view__back` 44px override was correctly present).

Confirmed → addressed:

1. **Cost modal unstyled on `/ops`** — fixed via the ops-native modal baseline
   (see piece 7).
2. **Card chevron polluted the row-button's accessible name** — the `›` was
   `::after { content }`, which the accname spec folds into a `role="button"`
   element's name. Re-implemented as a `background-image` (excluded from accname).
3. **`display:block` card layout strips implicit table/row/cell roles at
   ≤640px** — acknowledged, **not** applying the suggested
   `role="table/row/cell"` fix: rows already carry an intentional
   `role="button"` (they navigate to the detail), and a table can't contain
   button-rows without malformed ARIA. The card is a *list of labelled buttons*,
   and because `td::before` generated content *is* included in the accessible
   name, each card-button announces its field labels + values (arguably richer
   than the desktop row-button). Treated as an accepted trade-off of the
   interactive-row + responsive-card pattern.

## Decisions locked

- Tab bar: horizontal scroll strip (not wrapping grid).
- Split view on mobile: master→detail replace-in-place (not detail-below-list).
- Table rows on mobile: stacked cards (not horizontal-scroll, not
  key-columns-only).
- One breakpoint at 640px.
