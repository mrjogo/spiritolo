-- stage_runs -> queue-table foreign keys.
--
-- stage_runs was created before jobs / job_batches existed, so its batch_id and
-- job_id columns shipped as plain bigints with the references deferred. Both
-- queue tables now exist, so wire the FKs: a run's batch_id points at the
-- job_batches row that produced it, and its job_id at the jobs row that ran it.
--
-- ON DELETE SET NULL, not CASCADE: the ledger is a rebuildable cache of derived
-- facts about an entity, so pruning a job or a batch must not delete the runs it
-- produced — the derived facts outlive the dispatch intent. The columns stay
-- nullable (a deterministic run cites neither).

alter table stage_runs
  add constraint stage_runs_batch_id_fkey
    foreign key (batch_id) references job_batches (id) on delete set null,
  add constraint stage_runs_job_id_fkey
    foreign key (job_id) references jobs (id) on delete set null;
