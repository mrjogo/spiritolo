import { Routes, Route } from 'react-router-dom';
import { Header } from './components/Header';
import { RecipeList } from './pages/RecipeList';
import { RecipeDetail } from './pages/RecipeDetail';
import { ErrorPage } from './components/ErrorPage';

export default function App() {
  return (
    <>
      <Header />
      <Routes>
        <Route path="/" element={<RecipeList />} />
        <Route path="/recipes/:id" element={<RecipeDetail />} />
        <Route
          path="*"
          element={<ErrorPage title="Page not found" message="That URL doesn't match any page." />}
        />
      </Routes>
    </>
  );
}
