import { describe, it, expect } from 'vitest';
import { buildSearchFilters } from './searchQuery';

describe('buildSearchFilters', () => {
  it('returns empty terms and orFilters for an empty string', () => {
    expect(buildSearchFilters('')).toEqual({ terms: [], orFilters: [] });
  });

  it('returns empty for whitespace-only input', () => {
    expect(buildSearchFilters('   \t\n')).toEqual({ terms: [], orFilters: [] });
  });

  it('returns one term and one orFilter for a single word', () => {
    const result = buildSearchFilters('negroni');
    expect(result.terms).toEqual(['negroni']);
    expect(result.orFilters).toEqual([
      'name.ilike.*negroni*,jsonld->>recipeIngredient.ilike.*negroni*',
    ]);
  });

  it('trims surrounding whitespace from a single-term input', () => {
    expect(buildSearchFilters('  martini  ').terms).toEqual(['martini']);
  });

  it('splits multi-word input on whitespace', () => {
    const result = buildSearchFilters('gin lime');
    expect(result.terms).toEqual(['gin', 'lime']);
    expect(result.orFilters).toEqual([
      'name.ilike.*gin*,jsonld->>recipeIngredient.ilike.*gin*',
      'name.ilike.*lime*,jsonld->>recipeIngredient.ilike.*lime*',
    ]);
  });

  it('collapses runs of whitespace and tabs', () => {
    expect(buildSearchFilters('gin\t\t  lime  vermouth').terms).toEqual([
      'gin',
      'lime',
      'vermouth',
    ]);
  });
});
