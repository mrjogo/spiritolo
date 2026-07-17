import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../supabase';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { SplitView, DetailPane } from '../../ui/SplitView';
import { JsonView } from '../../ui/JsonView';
import { usePagedQuery } from '../../ui/hooks/usePagedQuery';
import { Pager } from '../../ui/Pager';
import {
  assembleBundlePreview,
  type BundlePreview,
  type BundlePreviewHeaderInput,
  type BundlePreviewIngredientInput,
  type BundlePreviewStepInput,
} from './bundlePreview';

interface ExportListRow {
  id: number;
  recipe_id: number;
  recipe_slug: string;
  recipe_ref: string;
  converter_version: string;
  exported_at: string;
}

interface ExportDetailRow extends ExportListRow {
  bundle: unknown;
}

const LIST_SELECT = 'id, recipe_id, recipe_slug, recipe_ref, converter_version, exported_at';

const COLUMNS: DataTableColumn<ExportListRow>[] = [
  { key: 'recipe_slug', header: 'slug' },
  { key: 'converter_version', header: 'version' },
  { key: 'exported_at', header: 'exported' },
];

// Two halves: the frozen recipe_exports catalog (drill into a stored
// bundle), and a preview panel that assembles the pin-2 shape on demand
// for a recipe that hasn't been frozen yet (bundlePreview.ts — a client-
// side, unvalidated mirror of the export stage's generate_bundle).
const PAGE_SIZE = 50;

export function ExportsBrowser() {
  const [page, setPage] = useState(1);
  const { rows, total } = usePagedQuery<ExportListRow>({
    table: 'recipe_exports',
    select: LIST_SELECT,
    order: { col: 'exported_at', asc: false },
    page,
    pageSize: PAGE_SIZE,
  });

  return (
    <div className="ops-exports">
      <Pager page={page} pageSize={PAGE_SIZE} total={total} onPage={setPage} unit="exports" />
      <SplitView
        list={({ select }) => (
          <DataTable
            columns={COLUMNS}
            rows={rows}
            rowKey={(r) => r.id}
            onRowClick={(r) => select(String(r.id))}
          />
        )}
        detail={({ selectedId }) => <ExportDetail id={selectedId} />}
      />
      <PreviewPanel />
    </div>
  );
}

function ExportDetail({ id }: { id: string | null }) {
  const query = useQuery({
    queryKey: ['exportDetail', id],
    queryFn: async () => {
      const { data, error } = await supabase
        .from('recipe_exports')
        .select('*')
        .eq('id', Number(id))
        .maybeSingle();
      if (error) throw error;
      return data as ExportDetailRow | null;
    },
    enabled: id != null,
  });

  if (id == null) return <DetailPane>Select an export to see its frozen bundle.</DetailPane>;
  if (query.isPending) return <DetailPane>Loading…</DetailPane>;
  if (!query.data) return <DetailPane>Export not found.</DetailPane>;

  const row = query.data;
  return (
    <DetailPane>
      <h3>{row.recipe_ref} @ {row.converter_version}</h3>
      <JsonView value={row.bundle} name="bundle" collapseAtDepth={2} />
    </DetailPane>
  );
}

async function fetchPreview(recipeId: number): Promise<BundlePreview | null> {
  const { data: header, error: headerError } = await supabase
    .from('recipes')
    .select('id, title, canonical_name, recipe_slug, source_url, equipment')
    .eq('id', recipeId)
    .maybeSingle();
  if (headerError) throw headerError;
  if (!header) return null;

  const { data: ingredientRows, error: ingredientsError } = await supabase
    .from('recipe_ingredients')
    .select('name, amount, amount_max, unit')
    .eq('recipe_id', recipeId)
    .order('position', { ascending: true });
  if (ingredientsError) throw ingredientsError;

  const { data: stepRows, error: stepsError } = await supabase
    .from('recipe_steps')
    .select('verb, roles, result, modifiers')
    .eq('recipe_id', recipeId)
    .order('step_index', { ascending: true });
  if (stepsError) throw stepsError;

  const ingredients = (ingredientRows ?? []) as BundlePreviewIngredientInput[];
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

  return assembleBundlePreview({
    header: header as BundlePreviewHeaderInput,
    ingredients,
    steps: (stepRows ?? []) as BundlePreviewStepInput[],
    resolutions,
  });
}

function PreviewPanel() {
  const [input, setInput] = useState('');
  const [recipeId, setRecipeId] = useState<number | null>(null);

  const query = useQuery({
    queryKey: ['exportPreview', recipeId],
    queryFn: () => fetchPreview(recipeId as number),
    enabled: recipeId != null,
  });

  return (
    <div className="ops-exports__preview" style={{ marginTop: 16 }}>
      <h3>Preview a bundle on demand</h3>
      <p style={{ fontSize: 12, opacity: 0.7 }}>
        Unvalidated preview assembled client-side from the current rows — not
        the authoritative bundle the export stage freezes into recipe_exports.
      </p>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input aria-label="recipe id" value={input} onChange={(e) => setInput(e.target.value)} />
        <button
          type="button"
          onClick={() => {
            const n = Number(input.trim());
            if (input.trim() !== '' && Number.isFinite(n)) setRecipeId(n);
          }}
        >
          Preview
        </button>
      </div>
      {recipeId != null && query.isPending && <p>Loading…</p>}
      {recipeId != null && !query.isPending && query.data === null && <p>Recipe not found.</p>}
      {query.data && (
        <>
          {query.data.unresolvedIngredientCount > 0 && (
            <p style={{ color: 'var(--st-failed, #b00020)' }}>
              {query.data.unresolvedIngredientCount} unresolved ingredient
              {query.data.unresolvedIngredientCount === 1 ? '' : 's'} — this recipe cannot export yet.
            </p>
          )}
          <JsonView value={query.data} name="preview" collapseAtDepth={2} />
        </>
      )}
    </div>
  );
}
