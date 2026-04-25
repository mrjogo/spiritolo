export type SearchFilters = {
  terms: string[];
  orFilters: string[];
};

const MIN_TERM_LENGTH = 3;

function toOrFilter(term: string): string {
  return `name.ilike.*${term}*,jsonld->>recipeIngredient.ilike.*${term}*`;
}

export function buildSearchFilters(q: string): SearchFilters {
  const trimmed = q.trim();
  if (trimmed === '') return { terms: [], orFilters: [] };
  const terms = trimmed.split(/\s+/).filter((t) => t.length >= MIN_TERM_LENGTH);
  if (terms.length === 0) return { terms: [], orFilters: [] };
  return { terms, orFilters: terms.map(toOrFilter) };
}
