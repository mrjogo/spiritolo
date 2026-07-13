import { useMutation, useQueryClient, type QueryKey, type UseMutationResult } from '@tanstack/react-query';
import { supabase } from '../../supabase';
import { RpcError } from '../../components/taxonomy/rpcs';

export { RpcError };

interface UseRpcOptions {
  /** Query keys to invalidate after a successful mutation. */
  invalidate?: QueryKey[];
}

// Thin react-query useMutation wrapper around supabase.rpc, reusing the
// EXACT RpcError shape from taxonomy/rpcs.ts so every mutating /ops action
// (enqueue/approve/edit) throws the same error shape the taxonomy curation
// RPCs already do. Deliberately does NOT route through taxonomy/rpcs'
// unwrap() — unwrap() treats a null `data` as itself an error, which is
// correct for the taxonomy RPCs (they always return an id/row) but wrong
// here: several /ops RPCs (approve_job) are `returns void` and legitimately
// respond with `data: null, error: null`. Only a real Postgrest error
// throws; a void RPC's null data passes through as-is.
export function useRpc<A extends Record<string, unknown> = Record<string, unknown>, R = unknown>(
  fn: string,
  opts?: UseRpcOptions,
): UseMutationResult<R, RpcError, A> {
  const queryClient = useQueryClient();

  return useMutation<R, RpcError, A>({
    mutationFn: async (args: A) => {
      const { data, error } = await supabase.rpc(fn, args);
      if (error) throw new RpcError(`${fn}: ${error.message}`, error);
      return data as R;
    },
    onSuccess: () => {
      for (const key of opts?.invalidate ?? []) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });
}
