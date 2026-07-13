// Client-side, unvalidated mirror of ingredients/src/ingredients/recipegf/
// generate.py's generate_bundle: assembles a pin-2-SHAPED preview from the
// same rows (recipes + recipe_ingredients + recipe_steps + the shared
// ingredient_resolutions) for a recipe that hasn't been frozen into
// recipe_exports yet. It intentionally skips RecipeGF's own schema
// validation (not available in the browser) and skips minting a portable
// ingredient ref — this is an ops preview of shape and readiness, not a
// substitute for the real export stage's frozen bundle.

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
// Combining diacritical marks (U+0300-U+036F) that NFKD decomposition
// leaves behind on an accented letter (e.g. e + U+0301 for e-acute).
const COMBINING_MARKS_RE = /[̀-ͯ]/g;

export function slugify(text: string): string {
  const ascii = text.normalize('NFKD').replace(COMBINING_MARKS_RE, '');
  const hyphenated = ascii.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  return hyphenated.replace(/^-+|-+$/g, '');
}

export interface BundlePreviewIngredientInput {
  name: string | null;
  amount: number | null;
  amount_max: number | null;
  unit: string | null;
}

export interface BundlePreviewStepInput {
  verb: string;
  roles: Record<string, unknown>;
  result: string;
  modifiers: string[];
}

export interface BundlePreviewHeaderInput {
  title: string | null;
  canonical_name: string | null;
  recipe_slug: string | null;
  source_url: string | null;
  equipment: string[];
}

export interface BundlePreviewInput {
  header: BundlePreviewHeaderInput;
  ingredients: BundlePreviewIngredientInput[];
  steps: BundlePreviewStepInput[];
  /** normalized (lower/trim) ingredient name -> resolved taxonomy slug, or
   *  null for a name that's been looked at but abstained. A name absent
   *  from the map is treated the same as an explicit null (unresolved). */
  resolutions: Map<string, string | null>;
}

export interface BundlePreviewIngredient {
  name: string;
  slug: string | null;
  amount: number | null;
  amount_max: number | null;
  unit: string | null;
}

export interface BundlePreview {
  recipe: {
    id: string;
    title: string;
    ingredients: BundlePreviewIngredient[];
    equipment: string[];
    steps: BundlePreviewStepInput[];
  };
  meta: {
    slug: string | null;
    source: string;
  };
  unresolvedIngredientCount: number;
}

function mintSlug(header: BundlePreviewHeaderInput): string | null {
  if (header.recipe_slug) return header.recipe_slug;
  const candidate = header.canonical_name || header.title || '';
  const slug = slugify(candidate);
  return slug && SLUG_RE.test(slug) ? slug : null;
}

export function assembleBundlePreview(input: BundlePreviewInput): BundlePreview {
  const slug = mintSlug(input.header);
  const ingredients: BundlePreviewIngredient[] = input.ingredients.map((i) => {
    const key = i.name ? i.name.toLowerCase().trim() : null;
    const resolvedSlug = key ? input.resolutions.get(key) ?? null : null;
    return {
      name: i.name ?? '', slug: resolvedSlug,
      amount: i.amount, amount_max: i.amount_max, unit: i.unit,
    };
  });

  return {
    recipe: {
      id: slug ? `com.spiritolo/${slug}:v1` : '(no slug yet)',
      title: input.header.title || input.header.canonical_name || slug || 'untitled',
      ingredients,
      equipment: input.header.equipment,
      steps: input.steps,
    },
    meta: { slug, source: input.header.source_url ?? '' },
    unresolvedIngredientCount: ingredients.filter((i) => !i.slug).length,
  };
}
