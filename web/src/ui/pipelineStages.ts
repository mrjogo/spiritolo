// The unified pipeline, discover -> ... -> export, in run order. This is the
// stage SET/ORDER (fixed by the job_items CHECK constraint and the queue
// predicate). Kept dependency-free (no supabase import) so anything that only
// needs the stage order — like the runs stage-picker — doesn't need a Supabase
// client configured.
export const PIPELINE_STAGES = [
  'discover', 'classify', 'fetch', 'extract-recipe', 'parse-ingredients', 'map-ingredient',
  'combine-nodes', 'connect-nodes',
  'convert-steps', 'cluster-recipes', 'export-recipegf',
] as const;

export type PipelineStage = (typeof PIPELINE_STAGES)[number];
