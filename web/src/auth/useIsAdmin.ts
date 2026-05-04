import { useQuery } from '@tanstack/react-query';
import { supabase } from '../supabase';
import { useAuth } from './AuthProvider';

export const isAdminQueryKey = (userId?: string | null) =>
  userId ? (['isAdmin', userId] as const) : (['isAdmin'] as const);

async function fetchIsAdmin(userId: string): Promise<boolean> {
  const { data, error } = await supabase
    .from('profiles')
    .select('is_admin')
    .eq('id', userId)
    .maybeSingle();
  if (error) throw error;
  return Boolean(data?.is_admin);
}

export function useIsAdmin(): { isAdmin: boolean; isLoading: boolean } {
  const { user, loading: sessionLoading } = useAuth();
  const userId = user?.id ?? null;

  const query = useQuery({
    queryKey: isAdminQueryKey(userId),
    queryFn: () => fetchIsAdmin(userId as string),
    enabled: !!userId,
  });

  if (sessionLoading) return { isAdmin: false, isLoading: true };
  if (!userId) return { isAdmin: false, isLoading: false };
  return { isAdmin: Boolean(query.data), isLoading: query.isPending };
}
