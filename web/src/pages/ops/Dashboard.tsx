import { PIPELINE_STAGES } from '../../ui/pipelineStages';
import { StageCard } from './StageCard';

export function Dashboard() {
  return (
    <div
      className="ops-dashboard"
      role="list"
      aria-label="pipeline stages"
      style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}
    >
      {PIPELINE_STAGES.map((stage) => (
        <div role="listitem" key={stage}>
          <StageCard stage={stage} />
        </div>
      ))}
    </div>
  );
}
