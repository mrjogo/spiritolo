import { describe, it, expect } from 'vitest';
import { normalizeRecipe } from './normalizeRecipe';
import sample from './test/fixtures/diffordsguide-sample.json';

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

describe('normalizeRecipe: ingredients', () => {
  const ing = (r: Record<string, unknown>) => normalizeRecipe(r).ingredients;

  it('uses recipeIngredient when present', () => {
    expect(ing({ recipeIngredient: ['2 oz gin', '0.5 oz lemon juice'] })).toEqual([
      '2 oz gin',
      '0.5 oz lemon juice',
    ]);
  });

  it('splits legacy `ingredients` string on newlines, dropping blanks', () => {
    expect(ing({ ingredients: '2 oz gin\n\n0.5 oz lemon juice\n' })).toEqual([
      '2 oz gin',
      '0.5 oz lemon juice',
    ]);
  });

  it('prefers recipeIngredient over legacy `ingredients`', () => {
    expect(
      ing({
        recipeIngredient: ['new'],
        ingredients: 'old',
      }),
    ).toEqual(['new']);
  });

  it('returns [] when neither is present or usable', () => {
    expect(ing({})).toEqual([]);
    expect(ing({ recipeIngredient: [] })).toEqual([]);
    expect(ing({ ingredients: '' })).toEqual([]);
    expect(ing({ recipeIngredient: 'not-an-array' })).toEqual([]);
  });
});

describe('normalizeRecipe: instructions', () => {
  const ins = (r: Record<string, unknown>) => normalizeRecipe(r).instructions;

  it('handles a plain string, splitting on newlines', () => {
    expect(ins({ recipeInstructions: 'Stir.\n\nStrain.' })).toEqual([
      { kind: 'step', text: 'Stir.' },
      { kind: 'step', text: 'Strain.' },
    ]);
  });

  it('handles an array of strings', () => {
    expect(ins({ recipeInstructions: ['Stir.', 'Strain.'] })).toEqual([
      { kind: 'step', text: 'Stir.' },
      { kind: 'step', text: 'Strain.' },
    ]);
  });

  it('handles an array of HowToStep objects', () => {
    expect(
      ins({
        recipeInstructions: [
          { '@type': 'HowToStep', text: 'Stir.' },
          { '@type': 'HowToStep', text: 'Strain.' },
        ],
      }),
    ).toEqual([
      { kind: 'step', text: 'Stir.' },
      { kind: 'step', text: 'Strain.' },
    ]);
  });

  it('handles HowToSection with nested itemListElement', () => {
    expect(
      ins({
        recipeInstructions: [
          {
            '@type': 'HowToSection',
            name: 'Prep',
            itemListElement: [
              { '@type': 'HowToStep', text: 'Chill glass.' },
              { '@type': 'HowToStep', text: 'Measure.' },
            ],
          },
          {
            '@type': 'HowToSection',
            name: 'Build',
            itemListElement: ['Combine.', 'Stir.'],
          },
        ],
      }),
    ).toEqual([
      { kind: 'section', heading: 'Prep', steps: ['Chill glass.', 'Measure.'] },
      { kind: 'section', heading: 'Build', steps: ['Combine.', 'Stir.'] },
    ]);
  });

  it('skips unknown/empty entries silently', () => {
    expect(
      ins({
        recipeInstructions: [
          { '@type': 'HowToStep', text: '' },
          null,
          { foo: 'bar' },
          'Stir.',
        ],
      }),
    ).toEqual([{ kind: 'step', text: 'Stir.' }]);
  });

  it('returns [] when missing or empty', () => {
    expect(ins({})).toEqual([]);
    expect(ins({ recipeInstructions: [] })).toEqual([]);
    expect(ins({ recipeInstructions: '' })).toEqual([]);
  });
});

describe('normalizeRecipe: real fixture', () => {
  it('normalizes an end-to-end blob without throwing', () => {
    const n = normalizeRecipe(sample as Record<string, unknown>);
    expect(n.name).toBeTruthy();
    expect(n.ingredients.length).toBeGreaterThan(0);
    expect(n.instructions.length).toBeGreaterThan(0);
    expect(Array.isArray(n.images)).toBe(true);
  });

  it('matches the expected shape snapshot', () => {
    expect(normalizeRecipe(sample as Record<string, unknown>)).toMatchSnapshot();
  });
});
