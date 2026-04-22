import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { supabase } from '../supabase';
import { ErrorPage } from '../components/ErrorPage';
import { normalizeRecipe } from '../normalizeRecipe';
import type { RecipeRow } from '../types';

type State =
  | { status: 'loading' }
  | { status: 'notfound' }
  | { status: 'error'; message: string }
  | { status: 'loaded'; row: RecipeRow };

export function RecipeDetail() {
  const { id } = useParams();
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });

    supabase
      .from('recipes_public')
      .select('*')
      .eq('id', id)
      .single()
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) {
          if (error.code === 'PGRST116') {
            setState({ status: 'notfound' });
            return;
          }
          setState({ status: 'error', message: error.message });
          return;
        }
        if (!data) {
          setState({ status: 'notfound' });
          return;
        }
        setState({ status: 'loaded', row: data as RecipeRow });
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  if (state.status === 'loading') return <div className="page">Loading…</div>;
  if (state.status === 'notfound')
    return <ErrorPage title="Recipe not found" message="No recipe with that ID." />;
  if (state.status === 'error')
    return <ErrorPage title="Couldn't load recipe" message={state.message} />;

  let normalized;
  try {
    normalized = normalizeRecipe(state.row.jsonld);
  } catch (err) {
    return (
      <ErrorPage
        title="Couldn't display recipe"
        message={err instanceof Error ? err.message : String(err)}
      />
    );
  }

  const host = safeHost(state.row.source_url);

  return (
    <div className="page recipe-detail">
      <p>
        <a href="/">← Back to recipes</a>
      </p>
      {normalized.images[0] && (
        <img src={normalized.images[0]} alt="" className="recipe-detail__hero" />
      )}
      <h1>{normalized.name}</h1>
      {(normalized.author || state.row.site) && (
        <p className="recipe-detail__byline">
          {normalized.author && <>By {normalized.author} · </>}
          {state.row.site}
        </p>
      )}
      {normalized.description && <p>{normalized.description}</p>}
      {(normalized.yield || normalized.prepTime || normalized.cookTime || normalized.totalTime) && (
        <ul className="recipe-detail__meta">
          {normalized.yield && <li>Yield: {normalized.yield}</li>}
          {normalized.prepTime && <li>Prep: {normalized.prepTime}</li>}
          {normalized.cookTime && <li>Cook: {normalized.cookTime}</li>}
          {normalized.totalTime && <li>Total: {normalized.totalTime}</li>}
        </ul>
      )}
      {normalized.ingredients.length > 0 && (
        <>
          <h2>Ingredients</h2>
          <ul>
            {normalized.ingredients.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </>
      )}
      {normalized.instructions.length > 0 && (
        <>
          <h2>Instructions</h2>
          {normalized.instructions.map((step, i) =>
            step.kind === 'step' ? (
              <p key={i}>{step.text}</p>
            ) : (
              <section key={i}>
                {step.heading && <h3>{step.heading}</h3>}
                <ol>
                  {step.steps.map((s, j) => (
                    <li key={j}>{s}</li>
                  ))}
                </ol>
              </section>
            ),
          )}
        </>
      )}
      <p>
        <a href={state.row.source_url} target="_blank" rel="noreferrer">
          View on {host}
        </a>
      </p>
    </div>
  );
}

function safeHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return 'source';
  }
}
