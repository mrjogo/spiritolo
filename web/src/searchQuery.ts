export type SearchFilters = {
  terms: string[];
  orFilters: string[];
};

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function buildSearchFilters(q: string): SearchFilters {
  return { terms: [], orFilters: [] };
}
