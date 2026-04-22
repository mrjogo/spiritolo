import { describe, it, expect } from 'vitest';
import { normalizeRecipe } from './normalizeRecipe';

describe('normalizeRecipe: simple fields', () => {
  it('returns the name', () => {
    expect(normalizeRecipe({ name: 'Old Fashioned' }).name).toBe('Old Fashioned');
  });

  it('returns "Untitled" when name is missing', () => {
    expect(normalizeRecipe({}).name).toBe('Untitled');
  });

  it('returns the description or null', () => {
    expect(normalizeRecipe({ description: 'A classic.' }).description).toBe('A classic.');
    expect(normalizeRecipe({}).description).toBeNull();
  });

  it('returns the recipeYield as a string', () => {
    expect(normalizeRecipe({ recipeYield: '1 drink' }).yield).toBe('1 drink');
    expect(normalizeRecipe({ recipeYield: 2 }).yield).toBe('2');
    expect(normalizeRecipe({}).yield).toBeNull();
  });

  it('returns the sourceUrl from jsonld.url when present', () => {
    expect(normalizeRecipe({ url: 'https://example.com/x' }).sourceUrl).toBe(
      'https://example.com/x',
    );
    expect(normalizeRecipe({}).sourceUrl).toBeNull();
  });
});

describe('normalizeRecipe: author', () => {
  it('handles a bare string author', () => {
    expect(normalizeRecipe({ author: 'Jerry Thomas' }).author).toBe('Jerry Thomas');
  });

  it('handles a Person object', () => {
    expect(
      normalizeRecipe({ author: { '@type': 'Person', name: 'Jerry Thomas' } }).author,
    ).toBe('Jerry Thomas');
  });

  it('handles an array of authors, joining with " & "', () => {
    expect(
      normalizeRecipe({
        author: [
          { '@type': 'Person', name: 'A' },
          { '@type': 'Person', name: 'B' },
          'C',
        ],
      }).author,
    ).toBe('A & B & C');
  });

  it('returns null when author is missing or empty', () => {
    expect(normalizeRecipe({}).author).toBeNull();
    expect(normalizeRecipe({ author: [] }).author).toBeNull();
    expect(normalizeRecipe({ author: '' }).author).toBeNull();
  });
});
