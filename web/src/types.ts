// Row shape of the recipes_public view.
export type RecipeRow = {
  id: number;
  source_url: string;
  site: string;
  name: string | null;
  author: string | null;
  image_url: string | null;
  jsonld: Record<string, unknown>;
};

// List-page projection (fewer columns, for speed).
export type RecipeListItem = Pick<
  RecipeRow,
  'id' | 'site' | 'name' | 'image_url'
>;

// Display-ready recipe, produced by normalizeRecipe().
export type NormalizedRecipe = {
  name: string;
  author: string | null;
  images: string[];
  description: string | null;
  yield: string | null;
  prepTime: string | null;
  cookTime: string | null;
  totalTime: string | null;
  ingredients: string[];
  instructions: InstructionStep[];
  sourceUrl: string | null;
};

export type InstructionStep =
  | { kind: 'step'; text: string }
  | { kind: 'section'; heading: string; steps: string[] };
