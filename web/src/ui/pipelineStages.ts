// The unified pipeline, discover -> ... -> export, in run order. This is the
// stage SET/ORDER (fixed by the stage_runs CHECK constraint and the queue
// predicate); metered-vs-free per stage is the separate, owner-rewired
// concern that lives in stage_config (see stageConfig.ts). Kept dependency-
// free (no supabase import) so anything that only needs the stage order —
// like the dashboard grid — doesn't need a Supabase client configured.
export const PIPELINE_STAGES = [
  'discover', 'classify', 'fetch', 'extract', 'parse', 'map', 'role', 'cluster', 'export',
] as const;

export type PipelineStage = (typeof PIPELINE_STAGES)[number];
