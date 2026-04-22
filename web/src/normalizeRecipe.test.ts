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

describe('normalizeRecipe: images', () => {
  const img = (r: Record<string, unknown>) => normalizeRecipe(r).images;

  it('handles a single string', () => {
    expect(img({ image: 'https://x/a.jpg' })).toEqual(['https://x/a.jpg']);
  });

  it('handles an ImageObject', () => {
    expect(img({ image: { '@type': 'ImageObject', url: 'https://x/a.jpg' } })).toEqual([
      'https://x/a.jpg',
    ]);
  });

  it('handles an array of strings', () => {
    expect(img({ image: ['https://x/a.jpg', 'https://x/b.jpg'] })).toEqual([
      'https://x/a.jpg',
      'https://x/b.jpg',
    ]);
  });

  it('handles an array of ImageObjects, preserves order, dedupes', () => {
    expect(
      img({
        image: [
          { url: 'https://x/a.jpg' },
          { url: 'https://x/b.jpg' },
          { url: 'https://x/a.jpg' },
        ],
      }),
    ).toEqual(['https://x/a.jpg', 'https://x/b.jpg']);
  });

  it('drops falsy, non-string urls, and returns [] when nothing usable', () => {
    expect(img({})).toEqual([]);
    expect(img({ image: null })).toEqual([]);
    expect(img({ image: ['', null, { url: '' }] })).toEqual([]);
    expect(img({ image: [{ foo: 'bar' }] })).toEqual([]);
  });
});

describe('normalizeRecipe: times', () => {
  const times = (r: Record<string, unknown>) => {
    const n = normalizeRecipe(r);
    return { prep: n.prepTime, cook: n.cookTime, total: n.totalTime };
  };

  it('formats minutes', () => {
    expect(times({ totalTime: 'PT15M' }).total).toBe('15 min');
  });

  it('formats hours and minutes', () => {
    expect(times({ totalTime: 'PT1H30M' }).total).toBe('1 h 30 min');
  });

  it('formats whole hours', () => {
    expect(times({ totalTime: 'PT2H' }).total).toBe('2 h');
  });

  it('returns null on malformed durations', () => {
    expect(times({ totalTime: 'fifteen minutes' }).total).toBeNull();
    expect(times({ totalTime: '' }).total).toBeNull();
  });

  it('handles prepTime and cookTime independently', () => {
    const n = normalizeRecipe({ prepTime: 'PT5M', cookTime: 'PT10M' });
    expect(n.prepTime).toBe('5 min');
    expect(n.cookTime).toBe('10 min');
  });

  it('returns null when missing', () => {
    const n = normalizeRecipe({});
    expect(n.prepTime).toBeNull();
    expect(n.cookTime).toBeNull();
    expect(n.totalTime).toBeNull();
  });
});
