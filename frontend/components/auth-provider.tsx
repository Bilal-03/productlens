"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getAccessToken, setAccessToken } from "@/lib/api";
import { createSupabaseAuthClient, type AuthSession, type AuthUser, SupabaseAuthClient } from "@/lib/supabase";

type AuthContextValue = {
  configured: boolean;
  loading: boolean;
  session: AuthSession | null;
  user: AuthUser | null;
  error: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<boolean>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [client] = useState<SupabaseAuthClient | null>(() => createSupabaseAuthClient());
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loading, setLoading] = useState(() => client !== null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client) {
      setAccessToken(null);
      return;
    }
    let active = true;
    // The API helper can synchronously read the same Supabase session from
    // localStorage. Start with that value so session hydration does not clear
    // and refetch an already correctly authenticated query tree.
    const lastToken = { value: getAccessToken() };
    const applySession = (next: AuthSession | null) => {
      const accessToken = next?.access_token ?? null;
      if (lastToken.value !== accessToken) {
        lastToken.value = accessToken;
        queryClient.clear();
      }
      if (!active) return;
      setSession(next);
      setAccessToken(accessToken);
    };
    void client.getSession().then((next) => {
      if (active) {
        setLoading(false);
        applySession(next);
      }
    });
    const unsubscribe = client.onAuthStateChange((next) => {
      if (!active) return;
      applySession(next);
      setError(null);
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [client, queryClient]);

  const value = useMemo<AuthContextValue>(() => ({
    configured: client !== null,
    loading,
    session,
    user: session?.user ?? null,
    error,
    async signIn(email, password) {
      if (!client) throw new Error("Supabase Auth is not configured for this deployment.");
      setError(null);
      try {
        const next = await client.signIn(email, password);
        setSession(next);
        setAccessToken(next.access_token);
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : "Sign-in failed.";
        setError(message);
        throw new Error(message);
      }
    },
    async signUp(email, password) {
      if (!client) throw new Error("Supabase Auth is not configured for this deployment.");
      setError(null);
      try {
        const next = await client.signUp(email, password);
        setSession(next);
        setAccessToken(next?.access_token ?? null);
        return next !== null;
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : "Sign-up failed.";
        setError(message);
        throw new Error(message);
      }
    },
    async signOut() {
      if (client) await client.signOut();
      setSession(null);
      setAccessToken(null);
    },
  }), [client, error, loading, session]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}
