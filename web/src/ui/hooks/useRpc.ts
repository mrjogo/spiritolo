import { useMutation, useQueryClient, type QueryKey, type UseMutationResult } from '@tanstack/react-query';
import { supabase } from '../../supabase';
import { unwrap, RpcError } from '../../components/taxonomy/rpcs';

export { RpcError };

interface UseRpcOptions {
  /** Query keys to invalidate after a successful mutation. */
  invalidate?: QueryKey[];
}

// Thin react-query useMutation wrapper around supabase.rpc, reusing the
// EXACT unwrap()/RpcError logic from taxonomy/rpcs.ts so every mutating
// /ops action (enqueue/approve/edit) throws the same error shape the
// taxonomy curation RPCs already do.
export function useRpc<A extends Record<string, unknown> = Record<string, unknown>, R = unknown>(
  fn: string,
  opts?: UseRpcOptions,
): UseMutationResult<R, RpcError, A> {
  const queryClient = useQueryClient();

  return useMutation<R, RpcError, A>({
    mutationFn: async (args: A) => {
      const { data, error } = await supabase.rpc(fn, args);
      return unwrap<R>(data as R, error, fn);
    },
    onSuccess: () => {
      for (const key of opts?.invalidate ?? []) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });
}
