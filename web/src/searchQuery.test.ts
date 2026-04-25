import { describe, it, expect } from 'vitest';
import { buildSearchFilters } from './searchQuery';

describe('buildSearchFilters', () => {
  it('returns empty terms and orFilters for an empty string', () => {
    expect(buildSearchFilters('')).toEqual({ terms: [], orFilters: [] });
  });

  it('returns empty for whitespace-only input', () => {
    expect(buildSearchFilters('   \t\n')).toEqual({ terms: [], orFilters: [] });
  });
});
