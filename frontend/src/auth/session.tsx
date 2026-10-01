import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import * as api from '../api/client';
import type { User } from '../api/types';

interface Session {
  user: User | null;
  /** True until the refresh-cookie exchange on first mount has settled. */
  restoring: boolean;
  signIn: (email: string, password: string) => Promise<User>;
  signOut: () => Promise<void>;
  /** Re-read the account after a profile edit, so the header shows the new name. */
  refreshUser: () => Promise<void>;
}

const SessionContext = createContext<Session | null>(null);

export const SessionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [restoring, setRestoring] = useState(true);

  // A reload loses the in-memory access token. The httpOnly refresh cookie survives it,
  // so one exchange on mount decides whether there is still a session to return to.
  useEffect(() => {
    let cancelled = false;
    api.refresh().then((token) => {
      if (!cancelled) {
        setUser(token?.user ?? null);
        setRestoring(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const token = await api.login(email, password);
    setUser(token.user);
    return token.user;
  }, []);

  const signOut = useCallback(async () => {
    await api.logout();
    setUser(null);
  }, []);

  const refreshUser = useCallback(async () => {
    setUser(await api.request<User>('/api/auth/me'));
  }, []);

  const value = useMemo(
    () => ({ user, restoring, signIn, signOut, refreshUser }),
    [user, restoring, signIn, signOut, refreshUser],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
};

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (session === null) throw new Error('useSession must be used inside a SessionProvider');
  return session;
}
