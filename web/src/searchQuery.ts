export type SearchFilters = {
  terms: string[];
  orFilters: string[];
};

const MIN_TERM_LENGTH = 3;

function stripEdges(term: string): string {
  return term.replace(/^[^A-Za-z0-9\\%_*]+|[^A-Za-z0-9\\%_*]+$/g, '');
}

function escapeIlike(term: string): string {
  return term.replace(/[\\%_*]/g, (c) => '\\' + c);
}

function toOrFilter(term: string): string {
  const e = escapeIlike(term);
  return `name.ilike.*${e}*,jsonld->>recipeIngredient.ilike.*${e}*`;
}

export function buildSearchFilters(q: string): SearchFilters {
  const trimmed = q.trim();
  if (trimmed === '') return { terms: [], orFilters: [] };
  const terms = trimmed
    .split(/\s+/)
    .map(stripEdges)
    .filter((t) => t.length >= MIN_TERM_LENGTH);
  if (terms.length === 0) return { terms: [], orFilters: [] };
  return { terms, orFilters: terms.map(toOrFilter) };
}
