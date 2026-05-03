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
                <Suspense fallback={<div className="page">Loading taxonomy…</div>}>
                  <Taxonomy />
                </Suspense>
              }
            />
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
