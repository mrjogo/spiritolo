import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../supabase';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { SplitView, DetailPane } from '../../ui/SplitView';
import { JsonView } from '../../ui/JsonView';
import { FilterBar } from '../../ui/FilterBar';
import { usePagedQuery, type PostgrestFilter } from '../../ui/hooks/usePagedQuery';

interface RecipeListRow {
  id: number;
  source_url: string;
  site: string;
  name: string | null;
  cluster_id: string | null;
}

interface RecipeHeader {
  id: number;
  source_url: string;
  site: string;
  title: string | null;
  canonical_name: string | null;
  cluster_id: string | null;
  recipe_slug: string | null;
  source: Record<string, unknown>;
}

interface IngredientRow {
  id: number;
  position: number;
  name: string | null;
  amount: number | null;
  amount_max: number | null;
  unit: string | null;
  raw_text: string;
}

interface ClusterInfo {
  cluster_key: string;
  canonical_name: string;
  recipe_count: number;
  source_count: number;
}

interface ExportInfo {
  recipe_ref: string;
  converter_version: string;
  exported_at: string;
}

interface RecipeDetailData {
  header: RecipeHeader;
  ingredients: IngredientRow[];
  resolutions: Map<string, string | null>;
  cluster: ClusterInfo | null;
  latestExport: ExportInfo | null;
}

const LIST_SELECT = 'id, source_url, site, name, cluster_id';

const COLUMNS: DataTableColumn<RecipeListRow>[] = [
  { key: 'id', header: 'id' },
  { key: 'name', header: 'name', render: (r) => r.name ?? '—' },
  { key: 'site', header: 'site' },
  { key: 'cluster_id', header: 'cluster', render: (r) => r.cluster_id ?? '—' },
];

// The recipes browser: drill from the raw source JSON-LD a recipe was
// extracted from, through its parsed recipe_ingredients, each name's shared
// ingredient_resolutions entry, the recipe_clusters identity it rolled up
// to, and the frozen recipe_exports bundle, in one detail pane.
export function RecipesBrowser() {
  const [filters, setFilters] = useState<PostgrestFilter[]>([]);

  const { rows, total } = usePagedQuery<RecipeListRow>({
    table: 'recipes_public',
    select: LIST_SELECT,
    filters,
    order: { col: 'id', asc: false },
    page: 1,
    pageSize: 50,
  });

  return (
    <div className="ops-recipes">
      <FilterBar onChange={(v) => setFilters(v.filters)} />
      <p style={{ fontSize: 12, opacity: 0.7 }}>{total} recipes</p>
      <SplitView
        list={({ select }) => (
          <DataTable
            columns={COLUMNS}
            rows={rows}
            rowKey={(r) => r.id}
            onRowClick={(r) => select(String(r.id))}
          />
        )}
        detail={({ selectedId }) => <RecipeDetail id={selectedId} />}
      />
    </div>
  );
}

async function fetchRecipeDetail(id: number): Promise<RecipeDetailData | null> {
  const { data: header, error: headerError } = await supabase
    .from('recipes')
    .select('id, source_url, site, title, canonical_name, cluster_id, recipe_slug, source')
    .eq('id', id)
    .maybeSingle();
  if (headerError) throw headerError;
  if (!header) return null;

  const { data: ingredientRows, error: ingredientsError } = await supabase
    .from('recipe_ingredients')
    .select('id, position, name, amount, amount_max, unit, raw_text')
    .eq('recipe_id', id)
    .order('position', { ascending: true });
  if (ingredientsError) throw ingredientsError;
  const ingredients = (ingredientRows ?? []) as IngredientRow[];

  const names = [
    ...new Set(
      ingredients
        .map((i) => i.name)
        .filter((n): n is string => !!n && n.trim() !== '')
        .map((n) => n.toLowerCase().trim()),
    ),
  ];
  const resolutions = new Map<string, string | null>();
  if (names.length > 0) {
    const { data: resolutionRows, error: resolutionsError } = await supabase
      .from('ingredient_resolutions')
      .select('normalized_name, taxonomy_slug')
      .in('normalized_name', names);
    if (resolutionsError) throw resolutionsError;
    for (const r of (resolutionRows ?? []) as { normalized_name: string; taxonomy_slug: string | null }[]) {
      resolutions.set(r.normalized_name, r.taxonomy_slug);
    }
  }

  let cluster: ClusterInfo | null = null;
  const clusterId = (header as RecipeHeader).cluster_id;
  if (clusterId) {
    const { data: clusterRow, error: clusterError } = await supabase
      .from('recipe_clusters')
      .select('cluster_key, canonical_name, recipe_count, source_count')
      .eq('cluster_key', clusterId)
      .maybeSingle();
    if (clusterError) throw clusterError;
    cluster = clusterRow as ClusterInfo | null;
  }

  const { data: exportRows, error: exportError } = await supabase
    .from('recipe_exports')
    .select('recipe_ref, converter_version, exported_at')
    .eq('recipe_id', id)
    .order('exported_at', { ascending: false });
  if (exportError) throw exportError;
  const latestExport = ((exportRows ?? []) as ExportInfo[])[0] ?? null;

  return { header: header as RecipeHeader, ingredients, resolutions, cluster, latestExport };
}

function RecipeDetail({ id }: { id: string | null }) {
  const query = useQuery({
    queryKey: ['recipeDetail', id],
    queryFn: () => fetchRecipeDetail(Number(id)),
    enabled: id != null,
  });

  if (id == null) return <DetailPane>Select a recipe to see its detail.</DetailPane>;
  if (query.isPending) return <DetailPane>Loading…</DetailPane>;
  if (!query.data) return <DetailPane>Recipe not found.</DetailPane>;

  const { header, ingredients, resolutions, cluster, latestExport } = query.data;
  return (
    <DetailPane>
      <h3>{header.title ?? header.canonical_name ?? `#${header.id}`}</h3>
      <p style={{ fontSize: 12, opacity: 0.7 }}>{header.site} — {header.source_url}</p>

      <h4>Raw source</h4>
      <JsonView value={header.source} name="source" />

      <h4>Parsed ingredients</h4>
      <ul>
        {ingredients.map((i) => {
          const key = i.name ? i.name.toLowerCase().trim() : null;
          const slug = key ? resolutions.get(key) : undefined;
          return (
            <li key={i.id}>
              {i.raw_text} — {i.name ?? 'unparsed'}
              {i.name && (
                <> ({slug ? slug : 'unresolved'})</>
              )}
            </li>
          );
        })}
        {ingredients.length === 0 && <li>No parsed ingredients yet.</li>}
      </ul>

      <h4>Cluster</h4>
      {cluster ? (
        <p>{cluster.canonical_name} — cluster {cluster.cluster_key} ({cluster.recipe_count} recipes, {cluster.source_count} sources)</p>
      ) : (
        <p style={{ fontStyle: 'italic', opacity: 0.7 }}>not yet clustered</p>
      )}

      <h4>Export</h4>
      {latestExport ? (
        <p>{latestExport.recipe_ref} @ {latestExport.converter_version} ({latestExport.exported_at})</p>
      ) : (
        <p style={{ fontStyle: 'italic', opacity: 0.7 }}>not yet exported</p>
      )}
    </DetailPane>
  );
}
