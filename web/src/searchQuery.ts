export type SearchFilters = {
  terms: string[];
  orFilters: string[];
};

function toOrFilter(term: string): string {
  return `name.ilike.*${term}*,jsonld->>recipeIngredient.ilike.*${term}*`;
}

export function buildSearchFilters(q: string): SearchFilters {
  const trimmed = q.trim();
  if (trimmed === '') return { terms: [], orFilters: [] };
  const terms = trimmed.split(/\s+/);
  return { terms, orFilters: terms.map(toOrFilter) };
}
