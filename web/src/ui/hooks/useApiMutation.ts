import { useMutation, useQueryClient, type QueryKey, type UseMutationResult } from '@tanstack/react-query';
import { ApiError } from '../../api';

interface UseApiMutationOptions {
  /** Query keys to invalidate after a successful mutation. */
  invalidate?: QueryKey[];
}

// Thin react-query useMutation wrapper over an API call, so every mutating
// /ops action (runs, reviews, taxonomy edits) shares one error shape
// (ApiError) and one invalidation convention.
export function useApiMutation<A, R = unknown>(
  fn: (args: A) => Promise<R>,
  opts?: UseApiMutationOptions,
): UseMutationResult<R, ApiError, A> {
  const queryClient = useQueryClient();
  return useMutation<R, ApiError, A>({
    mutationFn: (args: A) => fn(args),
    onSuccess: () => {
      for (const key of opts?.invalidate ?? []) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });
}
