import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../supabase';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { SplitView, DetailPane } from '../../ui/SplitView';
import { JsonView } from '../../ui/JsonView';
import { usePagedQuery } from '../../ui/hooks/usePagedQuery';

interface ClusterListRow {
  cluster_key: string;
  canonical_name: string;
  recipe_count: number;
  source_count: number;
}

interface ClusterDetailRow extends ClusterListRow {
  ingredient_set: unknown;
  representative_recipe_id: number | null;
  version: string | null;
}

interface MemberRecipe {
  id: number;
  title: string | null;
  site: string;
}

const LIST_SELECT = 'cluster_key, canonical_name, recipe_count, source_count';

const COLUMNS: DataTableColumn<ClusterListRow>[] = [
  { key: 'canonical_name', header: 'drink' },
  { key: 'cluster_key', header: 'cluster key' },
  { key: 'recipe_count', header: 'recipes' },
  { key: 'source_count', header: 'sources' },
];

// recipe_clusters browser: the derived drink identity a recipe's cluster_id
// points at. Detail drills into the antichain ingredient_set that hashed to
// this cluster_key plus every member recipe currently pointing at it.
export function ClustersBrowser() {
  const { rows } = usePagedQuery<ClusterListRow>({
    table: 'recipe_clusters',
    select: LIST_SELECT,
    order: { col: 'recipe_count', asc: false },
    page: 1,
    pageSize: 50,
  });

  return (
    <div className="ops-clusters">
      <SplitView
        list={({ select }) => (
          <DataTable
            columns={COLUMNS}
            rows={rows}
            rowKey={(r) => r.cluster_key}
            onRowClick={(r) => select(r.cluster_key)}
          />
        )}
        detail={({ selectedId }) => <ClusterDetail clusterKey={selectedId} />}
      />
    </div>
  );
}

function ClusterDetail({ clusterKey }: { clusterKey: string | null }) {
  const detailQuery = useQuery({
    queryKey: ['clusterDetail', clusterKey],
    queryFn: async () => {
      const { data, error } = await supabase
        .from('recipe_clusters')
        .select('*')
        .eq('cluster_key', clusterKey)
        .maybeSingle();
      if (error) throw error;
      return data as ClusterDetailRow | null;
    },
    enabled: clusterKey != null,
  });

  const membersQuery = useQuery({
    queryKey: ['clusterMembers', clusterKey],
    queryFn: async () => {
      const { data, error } = await supabase
        .from('recipes_public')
        .select('id, name, site')
        .eq('cluster_id', clusterKey);
      if (error) throw error;
      return ((data ?? []) as { id: number; name: string | null; site: string }[]).map((r) => ({
        id: r.id, title: r.name, site: r.site,
      })) as MemberRecipe[];
    },
    enabled: clusterKey != null,
  });

  if (clusterKey == null) return <DetailPane>Select a cluster to see its detail.</DetailPane>;
  if (detailQuery.isPending) return <DetailPane>Loading…</DetailPane>;
  if (!detailQuery.data) return <DetailPane>Cluster not found.</DetailPane>;

  const row = detailQuery.data;
  return (
    <DetailPane>
      <h3>{row.canonical_name}</h3>
      <dl>
        <dt>cluster key</dt>
        <dd>{row.cluster_key}</dd>
        <dt>recipes / sources</dt>
        <dd>{row.recipe_count} / {row.source_count}</dd>
      </dl>
      <JsonView value={row.ingredient_set} name="ingredient_set" collapseAtDepth={3} />
      <h4>Member recipes</h4>
      {membersQuery.isPending && <p>Loading…</p>}
      {membersQuery.data && (
        <ul>
          {membersQuery.data.map((m) => (
            <li key={m.id}>{m.title ?? `#${m.id}`} — {m.site}</li>
          ))}
        </ul>
      )}
    </DetailPane>
  );
}
