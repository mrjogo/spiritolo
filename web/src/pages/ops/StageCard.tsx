import { Link } from 'react-router-dom';
import { usePagedQuery } from '../../ui/hooks/usePagedQuery';
import { stageRunsHref } from '../../ui/opsLinks';
import { useRealtimeJobs } from '../../ui/hooks/useRealtimeJobs';
import { useStageQueueCounts, queueDepthForStage } from '../../ui/hooks/useStageQueueCounts';
import { StatusPill } from '../../ui/StatusPill';
import { CostBadge } from '../../ui/CostBadge';
import { TriggerBar } from '../../ui/TriggerBar';

interface OutcomeRow {
  outcome: string;
  run_count: number;
  cost_cents: number | null;
}

const IN_FLIGHT_STATES = new Set(['claimed', 'running']);

// One-line reminder of what each pipeline stage does, shown under its name.
const STAGE_DESCRIPTIONS: Record<string, string> = {
  discover: 'Crawl sites for candidate URLs',
  classify: 'Label each URL by content type',
  fetch: 'Fetch + cache page HTML',
  extract: 'Page HTML → recipe (Schema.org JSON-LD)',
  parse: 'Ingredient strings → structured rows',
  map: 'Ingredient names → taxonomy slugs',
  convert: 'Recipe → verb-frame steps',
  cluster: 'Derive drink identity + dedup',
  export: 'Freeze the RecipeGF bundle',
};

interface Props {
  stage: string;
}

// One card per pipeline stage. Built from what the platform actually has
// today (stage_runs outcome aggregates + live jobs + accumulated cost),
// plus a real content-queue-depth count from stage_queue_counts for every
// stage that RPC tracks. A stage with no row there (discover/classify/fetch,
// still SQLite-backed) shows an explicit "not tracked" message rather than a
// fabricated number.
export function StageCard({ stage }: Props) {
  const { rows: outcomeRows, status } = usePagedQuery<OutcomeRow>({
    table: 'stage_run_outcome_counts',
    select: 'outcome, run_count, cost_cents',
    filters: [{ col: 'stage', op: 'eq', value: stage }],
    page: 1,
    pageSize: 20,
  });
  const { jobs } = useRealtimeJobs({ stage });
  const { rows: queueRows, status: queueStatus } = useStageQueueCounts();
  const queueDepth = queueDepthForStage(queueRows, stage);
  const inFlight = jobs.filter((j) => IN_FLIGHT_STATES.has(String(j.state))).length;
  const totalCostCents = outcomeRows.reduce((sum, r) => sum + (r.cost_cents ?? 0), 0);
  const hasRuns = status === 'loaded' && outcomeRows.length > 0;

  return (
    <div className="stage-card" style={{
      border: '1px solid var(--ops-border, #e3e5e9)', borderRadius: 6, padding: 12,
    }}>
      <h3 style={{ margin: '0 0 2px', fontSize: 14 }}>
        <Link className="ops-xlink" to={stageRunsHref(stage)}>{stage}</Link>
      </h3>
      {STAGE_DESCRIPTIONS[stage] && (
        <p style={{ margin: '0 0 10px', fontSize: 11.5, lineHeight: 1.3, color: 'var(--ops-muted, #8a8f98)' }}>
          {STAGE_DESCRIPTIONS[stage]}
        </p>
      )}

      <div style={{ marginBottom: 8 }}>
        <span aria-label="in-flight jobs" style={{ fontSize: 12 }}>
          in-flight: {inFlight}
        </span>
      </div>

      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: 11, opacity: 0.7 }}>queue depth</div>
        {queueStatus === 'loading' && (
          <div style={{ fontSize: 12, opacity: 0.7 }}>…</div>
        )}
        {queueStatus !== 'loading' && queueDepth === null && (
          <div style={{ fontSize: 12, fontStyle: 'italic', opacity: 0.7 }}>
            not tracked
          </div>
        )}
        {queueStatus !== 'loading' && queueDepth !== null && (
          <div style={{ fontSize: 20, fontWeight: 600 }}>{queueDepth}</div>
        )}
      </div>

      <div
        role="list"
        aria-label={`${stage} outcome mix`}
        style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}
      >
        {status === 'loaded' && !hasRuns && (
          <span style={{ fontSize: 12, fontStyle: 'italic', opacity: 0.7 }}>no runs yet</span>
        )}
        {outcomeRows.map((r) => (
          <span key={r.outcome} role="listitem" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <StatusPill kind={r.outcome} />
            <span style={{ fontSize: 12 }}>{r.run_count}</span>
          </span>
        ))}
      </div>

      <div style={{ marginBottom: 8 }}>
        <CostBadge cents={totalCostCents} metered={totalCostCents > 0} />
      </div>

      <TriggerBar stage={stage} />
    </div>
  );
}
