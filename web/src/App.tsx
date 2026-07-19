import { lazy, Suspense } from 'react';
import { Routes, Route } from 'react-router-dom';
import { AppLayout } from './components/AppLayout';
import { RequireAuth } from './auth/RequireAuth';
import { RequireAdmin } from './auth/RequireAdmin';
import { Landing } from './pages/Landing';
import { Login } from './pages/Login';
import { AuthCallback } from './pages/AuthCallback';
import { RecipeList } from './pages/RecipeList';
import { RecipeDetail } from './pages/RecipeDetail';
import { ErrorPage } from './components/ErrorPage';

// Lazy-load Taxonomy to keep react-force-graph-2d + d3-force out of the
// recipe-page bundle (~600 KB saved on first paint of /recipes).
const Taxonomy = lazy(() =>
  import('./pages/Taxonomy').then((m) => ({ default: m.Taxonomy })),
);

// Lazy-load the /ops console the same way — a separate chunk kept out of
// the recipe-page bundle until an admin actually opens it.
const OpsLayout = lazy(() =>
  import('./pages/ops/OpsLayout').then((m) => ({ default: m.OpsLayout })),
);
const OpsRecipesBrowser = lazy(() =>
  import('./pages/ops/RecipesBrowser').then((m) => ({ default: m.RecipesBrowser })),
);
const OpsStageRunsBrowser = lazy(() =>
  import('./pages/ops/StageRunsBrowser').then((m) => ({ default: m.StageRunsBrowser })),
);
const OpsAuditLogBrowser = lazy(() =>
  import('./pages/ops/AuditLogBrowser').then((m) => ({ default: m.AuditLogBrowser })),
);
const OpsClustersBrowser = lazy(() =>
  import('./pages/ops/ClustersBrowser').then((m) => ({ default: m.ClustersBrowser })),
);
const OpsExportsBrowser = lazy(() =>
  import('./pages/ops/ExportsBrowser').then((m) => ({ default: m.ExportsBrowser })),
);
const OpsReviewsBrowser = lazy(() =>
  import('./pages/ops/ReviewsBrowser').then((m) => ({ default: m.ReviewsBrowser })),
);
const OpsRunsList = lazy(() =>
  import('./pages/ops/runs/RunsList').then((m) => ({ default: m.RunsList })),
);
const OpsRunDetail = lazy(() =>
  import('./pages/ops/runs/RunDetail').then((m) => ({ default: m.RunDetail })),
);
const OpsAddTasks = lazy(() =>
  import('./pages/ops/runs/AddTasks').then((m) => ({ default: m.AddTasks })),
);

function OpsChunkFallback() {
  return (
    <div role="status" aria-label="Loading ops console">
      Loading…
    </div>
  );
}

// Self-contained fallback for the lazy chunk: matches the in-page
// "settling" spinner so loading the chunk → loading data → settling
// the d3 simulation all show the same affordance in the same spot,
// with no flash of legacy "Loading…" text. Inlined here because the
// taxonomy.css that defines the matching rule lives inside the lazy
// chunk and isn't available yet.
const TAXONOMY_FALLBACK_CSS = `
@keyframes tx-fallback-spin { to { transform: rotate(360deg); } }
.tx-fallback {
  position: relative;
  min-height: calc(100vh - var(--site-header-height));
  background: radial-gradient(
    ellipse at center,
    #2a1d11 0%, #160d05 70%, #0d0703 100%
  );
}
.tx-fallback__spinner {
  position: absolute;
  inset: 0;
  margin: auto;
  width: 28px; height: 28px;
  border-radius: 50%;
  border: 1.5px solid rgba(201, 164, 73, 0.2);
  border-top-color: #c9a449;
  animation: tx-fallback-spin 900ms linear infinite;
}
`;

function TaxonomyChunkFallback() {
  return (
    <>
      <style>{TAXONOMY_FALLBACK_CSS}</style>
      <div className="tx-fallback" role="status" aria-label="Loading taxonomy">
        <div className="tx-fallback__spinner" aria-hidden="true" />
      </div>
    </>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/auth/callback" element={<AuthCallback />} />

      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route path="/recipes" element={<RecipeList />} />
          <Route path="/recipes/:id" element={<RecipeDetail />} />

          <Route element={<RequireAdmin />}>
            <Route
              path="/taxonomy"
              element={
                <Suspense fallback={<TaxonomyChunkFallback />}>
                  <Taxonomy />
                </Suspense>
              }
            />

            <Route
              path="/ops"
              element={
                <Suspense fallback={<OpsChunkFallback />}>
                  <OpsLayout />
                </Suspense>
              }
            >
              <Route
                index
                element={
                  <Suspense fallback={<OpsChunkFallback />}>
                    <OpsRunsList />
                  </Suspense>
                }
              />
              <Route
                path="recipes"
                element={
                  <Suspense fallback={<OpsChunkFallback />}>
                    <OpsRecipesBrowser />
                  </Suspense>
                }
              />
              <Route
                path="stage-runs"
                element={
                  <Suspense fallback={<OpsChunkFallback />}>
                    <OpsStageRunsBrowser />
                  </Suspense>
                }
              />
              <Route
                path="audit-log"
                element={
                  <Suspense fallback={<OpsChunkFallback />}>
                    <OpsAuditLogBrowser />
                  </Suspense>
                }
              />
              <Route
                path="clusters"
                element={
                  <Suspense fallback={<OpsChunkFallback />}>
                    <OpsClustersBrowser />
                  </Suspense>
                }
              />
              <Route
                path="exports"
                element={
                  <Suspense fallback={<OpsChunkFallback />}>
                    <OpsExportsBrowser />
                  </Suspense>
                }
              />
              <Route
                path="reviews"
                element={
                  <Suspense fallback={<OpsChunkFallback />}>
                    <OpsReviewsBrowser />
                  </Suspense>
                }
              />
              <Route
                path="runs"
                element={
                  <Suspense fallback={<OpsChunkFallback />}>
                    <OpsRunsList />
                  </Suspense>
                }
              />
              <Route
                path="runs/:id"
                element={
                  <Suspense fallback={<OpsChunkFallback />}>
                    <OpsRunDetail />
                  </Suspense>
                }
              />
              <Route
                path="runs/:id/add"
                element={
                  <Suspense fallback={<OpsChunkFallback />}>
                    <OpsAddTasks />
                  </Suspense>
                }
              />
            </Route>
          </Route>
        </Route>
      </Route>

      <Route
        path="*"
        element={<ErrorPage title="Page not found" message="That URL doesn't match any page." />}
      />
    </Routes>
  );
}
