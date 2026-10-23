import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

// The signed-in operator, as /api/auth/me reports it.
export type Operator = {
  id: number;
  handle: string;
  display_name: string;
  is_admin: boolean;
};

export type MeResponse = {
  operator: Operator | null;
  /** True while no operator exists yet: the first passkey registration is open. */
  setup_required: boolean;
};

type AuthContextValue = {
  user: Operator | null;
  loading: boolean;
  setupRequired: boolean;
  /** Re-read the session from the server (after a passkey login/registration). */
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const queryClient = useQueryClient();

  const refresh = useCallback(async () => {
    let next: MeResponse;
    try {
      next = await api<MeResponse>('/api/auth/me');
    } catch {
      next = { operator: null, setup_required: false };
    }
    setMe(next);
    setLoading(false);
  }, []);

  useEffect(() => {
    // The probe is async, so these setState calls land after the effect
    // returns — not the synchronous-setState cascade the rule guards against.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  const signOut = useCallback(async () => {
    try {
      await api('/api/auth/logout', { method: 'POST' });
    } finally {
      setMe((prev) => ({ operator: null, setup_required: prev?.setup_required ?? false }));
      queryClient.clear();
    }
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: me?.operator ?? null,
      loading,
      setupRequired: me?.setup_required ?? false,
      refresh,
      signOut,
    }),
    [me, loading, refresh, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
