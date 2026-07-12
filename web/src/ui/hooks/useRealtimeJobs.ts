import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { RealtimePostgresChangesPayload } from '@supabase/supabase-js';
import { supabase } from '../../supabase';

export interface Job {
  id: number | string;
  stage: string;
  state: string;
  [key: string]: unknown;
}

export interface UseRealtimeJobsFilter {
  stage?: string;
  state?: string;
}

export interface UseRealtimeJobsResult {
  jobs: Job[];
  connected: boolean;
}

const POLL_INTERVAL_MS = 3000;

// Supabase Realtime postgres_changes on `jobs`, merged into the react-query
// cache so dashboard/jobs views update live with no extra fetch. Falls back
// to react-query polling (refetchInterval) when the channel never reaches
// SUBSCRIBED (e.g. no Realtime connection).
export function useRealtimeJobs(filter?: UseRealtimeJobsFilter): UseRealtimeJobsResult {
  const [connected, setConnected] = useState(false);
  const queryClient = useQueryClient();
  const stage = filter?.stage;
  const state = filter?.state;
  const queryKey = ['jobs', stage ?? null, state ?? null];

  const query = useQuery({
    queryKey,
    queryFn: async () => {
      let q = supabase.from('jobs').select('*');
      if (stage) q = q.eq('stage', stage);
      if (state) q = q.eq('state', state);
      const { data, error } = await q;
      if (error) throw error;
      return (data ?? []) as Job[];
    },
    refetchInterval: connected ? false : POLL_INTERVAL_MS,
  });

  useEffect(() => {
    const channel = supabase
      .channel(`jobs-realtime-${stage ?? 'all'}-${state ?? 'all'}`)
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'jobs' },
        (payload: RealtimePostgresChangesPayload<Job>) => {
          queryClient.setQueryData<Job[]>(queryKey, (prev) => mergePayload(prev ?? [], payload));
        },
      )
      .subscribe((status: string) => {
        setConnected(status === 'SUBSCRIBED');
      });

    // Reset on teardown (filter change or unmount) — not in the effect
    // body's setup path, so a stale "connected" from the previous channel
    // never lingers across a re-subscribe.
    return () => {
      setConnected(false);
      supabase.removeChannel(channel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage, state]);

  return { jobs: query.data ?? [], connected };
}

function mergePayload(prev: Job[], payload: RealtimePostgresChangesPayload<Job>): Job[] {
  if (payload.eventType === 'DELETE') {
    const oldId = (payload.old as Partial<Job>).id;
    if (oldId === undefined) return prev;
    return prev.filter((j) => j.id !== oldId);
  }
  const newRow = payload.new;
  const idx = prev.findIndex((j) => j.id === newRow.id);
  if (idx === -1) return [...prev, newRow];
  const next = [...prev];
  next[idx] = newRow;
  return next;
}
