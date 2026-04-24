import { Routes, Route } from 'react-router-dom';
import { RecipeList } from './pages/RecipeList';
import { RecipeDetail } from './pages/RecipeDetail';
import { ErrorPage } from './components/ErrorPage';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<RecipeList />} />
      <Route path="/recipes/:id" element={<RecipeDetail />} />
      <Route
        path="*"
        element={<ErrorPage title="Page not found" message="That URL doesn't match any page." />}
      />
    </Routes>
  );
}
