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

// One parsed ingredient line from recipe_ingredients, joined to taxonomy_nodes
// via PostgREST embed. taxonomy node fields are null when taxonomy_node_id is null.
export type RecipeIngredientRow = {
  id: number;
  position: number;
  raw_text: string;
  amount: number | null;
  amount_max: number | null;
  unit: string | null;
  name: string | null;
  modifier: string | null;
  role:
    | 'base_spirit' | 'modifier' | 'citrus' | 'sweetener'
    | 'bitters' | 'dilution' | 'ice' | 'garnish' | 'wash' | 'other'
    | null;
  parse_status: 'parsed' | 'unparseable';
  taxonomy_node_id: number | null;
  taxonomy_nodes: { slug: string; display_name: string } | null;
};
