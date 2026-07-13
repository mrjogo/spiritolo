import { usePagedQuery } from '../../ui/hooks/usePagedQuery';
import { useRealtimeJobs } from '../../ui/hooks/useRealtimeJobs';
import { StatusPill } from '../../ui/StatusPill';
import { CostBadge } from '../../ui/CostBadge';
import { TriggerBar } from '../../ui/TriggerBar';

interface OutcomeRow {
  outcome: string;
  run_count: number;
  cost_cents: number | null;
}

const IN_FLIGHT_STATES = new Set(['claimed', 'running']);

interface Props {
  stage: string;
}

// One card per pipeline stage. Built from what the platform actually has
// today (stage_runs outcome aggregates + live jobs + accumulated cost) —
// NOT from a content-queue-depth count, which needs the relational content
// tables (recipe_docs/recipes) that haven't landed yet. That gap is shown
// as an explicit placeholder rather than a fabricated number.
export function StageCard({ stage }: Props) {
  const { rows: outcomeRows, status } = usePagedQuery<OutcomeRow>({
    table: 'stage_run_outcome_counts',
    select: 'outcome, run_count, cost_cents',
    filters: [{ col: 'stage', op: 'eq', value: stage }],
    page: 1,
    pageSize: 20,
  });
  const { jobs } = useRealtimeJobs({ stage });
  const inFlight = jobs.filter((j) => IN_FLIGHT_STATES.has(String(j.state))).length;
  const totalCostCents = outcomeRows.reduce((sum, r) => sum + (r.cost_cents ?? 0), 0);
  const hasRuns = status === 'loaded' && outcomeRows.length > 0;

  return (
    <div className="stage-card" style={{
      border: '1px solid var(--ops-border, #e3e5e9)', borderRadius: 6, padding: 12,
    }}>
      <h3 style={{ margin: '0 0 8px', fontSize: 14 }}>{stage}</h3>

      <div style={{ marginBottom: 8 }}>
        <span aria-label="in-flight jobs" style={{ fontSize: 12 }}>
          in-flight: {inFlight}
        </span>
      </div>

      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: 11, opacity: 0.7 }}>queue depth</div>
        <div style={{ fontSize: 12, fontStyle: 'italic', opacity: 0.7 }}>
          not yet available — pending content tables (follow-up)
        </div>
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
