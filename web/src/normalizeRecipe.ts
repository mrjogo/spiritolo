import type { NormalizedRecipe } from './types';

type Json = Record<string, unknown>;

function asString(x: unknown): string | null {
  if (typeof x === 'string') {
    const s = x.trim();
    return s === '' ? null : s;
  }
  if (typeof x === 'number') return String(x);
  return null;
}

function extractName(x: unknown): string | null {
  if (typeof x === 'string') return asString(x);
  if (x && typeof x === 'object' && 'name' in x) return asString((x as Json).name);
  return null;
}

function normalizeAuthor(raw: unknown): string | null {
  if (raw == null) return null;
  const arr = Array.isArray(raw) ? raw : [raw];
  const names = arr.map(extractName).filter((n): n is string => !!n);
  return names.length === 0 ? null : names.join(' & ');
}

export function normalizeRecipe(jsonld: Json): NormalizedRecipe {
  return {
    name: asString(jsonld.name) ?? 'Untitled',
    author: normalizeAuthor(jsonld.author),
    images: [],
    description: asString(jsonld.description),
    yield: asString(jsonld.recipeYield),
    prepTime: null,
    cookTime: null,
    totalTime: null,
    ingredients: [],
    instructions: [],
    sourceUrl: asString(jsonld.url),
  };
}
