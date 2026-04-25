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

  it('drops terms shorter than 3 characters', () => {
    expect(buildSearchFilters('a gin').terms).toEqual(['gin']);
  });

  it('returns empty when every term is too short', () => {
    expect(buildSearchFilters('a b cd')).toEqual({ terms: [], orFilters: [] });
  });

  it('keeps exactly-3-character terms', () => {
    expect(buildSearchFilters('rye').terms).toEqual(['rye']);
  });

  it('strips trailing punctuation from terms', () => {
    expect(buildSearchFilters('gin, vermouth').terms).toEqual(['gin', 'vermouth']);
  });

  it('strips wrapping brackets/parens', () => {
    expect(buildSearchFilters('(rye) [bourbon]').terms).toEqual(['rye', 'bourbon']);
  });

  it('preserves internal punctuation', () => {
    expect(buildSearchFilters('st-germain').terms).toEqual(['st-germain']);
  });

  it('drops a term whose only content is punctuation', () => {
    expect(buildSearchFilters('gin --- lime').terms).toEqual(['gin', 'lime']);
  });

  it('applies min-length AFTER stripping punctuation', () => {
    expect(buildSearchFilters('!!!ab!!! gin').terms).toEqual(['gin']);
  });

  it('escapes ILIKE % wildcard in user input', () => {
    const r = buildSearchFilters('50%');
    expect(r.terms).toEqual(['50%']);
    expect(r.orFilters[0]).toContain('*50\\%*');
  });

  it('escapes ILIKE _ wildcard in user input', () => {
    const r = buildSearchFilters('foo_bar');
    expect(r.orFilters[0]).toContain('*foo\\_bar*');
  });

  it('escapes backslash in user input', () => {
    const r = buildSearchFilters('foo\\bar');
    expect(r.orFilters[0]).toContain('*foo\\\\bar*');
  });

  it('escapes literal asterisk so it does not act as a PostgREST wildcard', () => {
    const r = buildSearchFilters('foo*bar');
    expect(r.orFilters[0]).toContain('*foo\\*bar*');
  });
});
