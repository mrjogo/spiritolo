import { Fragment, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { supabase } from '../supabase';
import { ErrorPage } from '../components/ErrorPage';
import { normalizeRecipe } from '../normalizeRecipe';
import type { InstructionStep, RecipeRow } from '../types';

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

    const numericId = Number(id);
    if (!id || !Number.isFinite(numericId) || !Number.isInteger(numericId)) {
      setState({ status: 'notfound' });
      return;
    }

    supabase
      .from('recipes_public')
      .select('*')
      .eq('id', numericId)
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
        <Link to="/">← Back to recipes</Link>
      </p>
      {normalized.images[0] && (
        <img src={normalized.images[0]} alt="" className="recipe-detail__hero" />
      )}
      <h1>{normalized.name}</h1>
      {(normalized.author || host) && (
        <p className="recipe-detail__byline">
          {normalized.author && <>By {normalized.author} · </>}
          {host}
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
          {renderInstructions(normalized.instructions)}
        </>
      )}
      <p>
        <a href={state.row.source_url} target="_blank" rel="noreferrer">
          View at {state.row.source_url}
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

function renderInstructions(steps: InstructionStep[]) {
  const groups: Array<
    | { kind: 'steps'; steps: string[] }
    | { kind: 'section'; heading: string; steps: string[] }
  > = [];
  for (const step of steps) {
    if (step.kind === 'step') {
      const last = groups[groups.length - 1];
      if (last && last.kind === 'steps') last.steps.push(step.text);
      else groups.push({ kind: 'steps', steps: [step.text] });
    } else {
      groups.push({ kind: 'section', heading: step.heading, steps: step.steps });
    }
  }
  return groups.map((g, i) => {
    if (g.kind === 'steps') {
      if (g.steps.length === 1) return <p key={i}>{g.steps[0]}</p>;
      return (
        <ol key={i} className="recipe-detail__steps">
          {g.steps.map((s, j) => (
            <li key={j}>{s}</li>
          ))}
        </ol>
      );
    }
    return (
      <Fragment key={i}>
        {g.heading && <h3>{g.heading}</h3>}
        <ol className="recipe-detail__steps">
          {g.steps.map((s, j) => (
            <li key={j}>{s}</li>
          ))}
        </ol>
      </Fragment>
    );
  });
}
