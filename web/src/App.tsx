import { lazy, Suspense } from 'react';
import { Routes, Route } from 'react-router-dom';
import { Header } from './components/Header';
import { RecipeList } from './pages/RecipeList';
import { RecipeDetail } from './pages/RecipeDetail';
import { ErrorPage } from './components/ErrorPage';

// Lazy-load Taxonomy to keep react-force-graph-2d + d3-force out of
// the recipe-page bundle (~600 KB saved on first paint of /).
const Taxonomy = lazy(() =>
  import('./pages/Taxonomy').then((m) => ({ default: m.Taxonomy })),
);

export default function App() {
  return (
    <>
      <Header />
      <Routes>
        <Route path="/" element={<RecipeList />} />
        <Route path="/recipes/:id" element={<RecipeDetail />} />
        <Route
          path="/taxonomy"
          element={
            <Suspense fallback={<div className="page">Loading taxonomy…</div>}>
              <Taxonomy />
            </Suspense>
          }
        />
        <Route
          path="*"
          element={<ErrorPage title="Page not found" message="That URL doesn't match any page." />}
        />
      </Routes>
    </>
  );
}
