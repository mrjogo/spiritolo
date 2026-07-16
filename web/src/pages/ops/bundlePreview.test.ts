import { describe, it, expect } from 'vitest';
import { assembleBundlePreview, slugify } from './bundlePreview';

describe('slugify', () => {
  it('lowercases and hyphenates', () => {
    expect(slugify('Old Fashioned')).toBe('old-fashioned');
  });

  it('strips accents', () => {
    expect(slugify('Café Royale')).toBe('cafe-royale');
  });

  it('collapses punctuation runs and trims edges', () => {
    expect(slugify('  The "Best" Drink!! ')).toBe('the-best-drink');
  });

  it('returns empty string for input with no alphanumerics', () => {
    expect(slugify('!!!')).toBe('');
  });
});

describe('assembleBundlePreview', () => {
  const baseHeader = {
    title: 'Old Fashioned',
    canonical_name: 'old fashioned',
    recipe_slug: 'old-fashioned',
    source_url: 'https://ex.test/of',
    equipment: ['mixing_glass', 'bar_spoon'],
  };

  it('mints the recipe id from the frozen recipe_slug when present', () => {
    const preview = assembleBundlePreview({
      header: baseHeader,
      ingredients: [{ name: 'Bourbon', amount: 2, amount_max: null, unit: 'oz' }],
      steps: [{ verb: 'stir', roles: { input: ['bourbon'] }, result: 'stirred', modifiers: [] }],
      resolutions: new Map([['bourbon', 'bourbon']]),
    });
    expect(preview.recipe.id).toBe('com.spiritolo/old-fashioned:v1');
    expect(preview.meta.slug).toBe('old-fashioned');
    expect(preview.recipe.ingredients).toEqual([
      { name: 'Bourbon', slug: 'bourbon', amount: 2, amount_max: null, unit: 'oz' },
    ]);
    expect(preview.unresolvedIngredientCount).toBe(0);
  });

  it('mints a slug from the canonical name when recipe_slug is not yet frozen', () => {
    const preview = assembleBundlePreview({
      header: { ...baseHeader, recipe_slug: null },
      ingredients: [],
      steps: [],
      resolutions: new Map(),
    });
    expect(preview.meta.slug).toBe('old-fashioned');
  });

  it('counts unresolved ingredients and flags them by a null slug', () => {
    const preview = assembleBundlePreview({
      header: baseHeader,
      ingredients: [
        { name: 'Bourbon', amount: 2, amount_max: null, unit: 'oz' },
        { name: 'Mystery Bitters', amount: 1, amount_max: null, unit: 'dash' },
      ],
      steps: [],
      resolutions: new Map([['bourbon', 'bourbon']]),
    });
    expect(preview.unresolvedIngredientCount).toBe(1);
    expect(preview.recipe.ingredients[1]).toEqual(
      { name: 'Mystery Bitters', slug: null, amount: 1, amount_max: null, unit: 'dash' },
    );
  });

  it('has no slug when neither recipe_slug nor a mintable canonical name/title exists', () => {
    const preview = assembleBundlePreview({
      header: { title: null, canonical_name: null, recipe_slug: null, source_url: null, equipment: [] },
      ingredients: [],
      steps: [],
      resolutions: new Map(),
    });
    expect(preview.meta.slug).toBeNull();
    expect(preview.recipe.id).toBe('(no slug yet)');
  });
});
