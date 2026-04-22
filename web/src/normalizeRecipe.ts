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

function extractImageUrl(x: unknown): string | null {
  if (typeof x === 'string') return asString(x);
  if (x && typeof x === 'object' && 'url' in x) return asString((x as Json).url);
  return null;
}

function normalizeImages(raw: unknown): string[] {
  if (raw == null) return [];
  const arr = Array.isArray(raw) ? raw : [raw];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of arr) {
    const url = extractImageUrl(item);
    if (url && !seen.has(url)) {
      seen.add(url);
      out.push(url);
    }
  }
  return out;
}

function normalizeAuthor(raw: unknown): string | null {
  if (raw == null) return null;
  const arr = Array.isArray(raw) ? raw : [raw];
  const names = arr.map(extractName).filter((n): n is string => !!n);
  return names.length === 0 ? null : names.join(' & ');
}

function formatDuration(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const m = raw.match(/^PT(?:(\d+)H)?(?:(\d+)M)?$/);
  if (!m) return null;
  const hours = m[1] ? parseInt(m[1], 10) : 0;
  const mins = m[2] ? parseInt(m[2], 10) : 0;
  if (hours === 0 && mins === 0) return null;
  if (hours > 0 && mins > 0) return `${hours} h ${mins} min`;
  if (hours > 0) return `${hours} h`;
  return `${mins} min`;
}

function normalizeIngredients(jsonld: Json): string[] {
  const primary = jsonld.recipeIngredient;
  if (Array.isArray(primary)) {
    return primary.map((x) => asString(x)).filter((s): s is string => !!s);
  }
  const legacy = jsonld.ingredients;
  if (typeof legacy === 'string') {
    return legacy
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line !== '');
  }
  return [];
}

export function normalizeRecipe(jsonld: Json): NormalizedRecipe {
  return {
    name: asString(jsonld.name) ?? 'Untitled',
    author: normalizeAuthor(jsonld.author),
    images: normalizeImages(jsonld.image),
    description: asString(jsonld.description),
    yield: asString(jsonld.recipeYield),
    prepTime: formatDuration(jsonld.prepTime),
    cookTime: formatDuration(jsonld.cookTime),
    totalTime: formatDuration(jsonld.totalTime),
    ingredients: normalizeIngredients(jsonld),
    instructions: [],
    sourceUrl: asString(jsonld.url),
  };
}
