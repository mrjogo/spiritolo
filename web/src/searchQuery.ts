export type SearchFilters = {
  terms: string[];
  orFilters: string[];
};

export function buildSearchFilters(_q: string): SearchFilters {
  return { terms: [], orFilters: [] };
}
