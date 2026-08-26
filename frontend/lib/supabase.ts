"use client";

export type AuthUser = { id: string; email?: string | null };
export type AuthSession = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  expires_at: number;
  user: AuthUser;
};
type AuthListener = (session: AuthSession | null) => void;

const SESSION_KEY = "productlens-supabase-session";

export class SupabaseAuthClient {
  private readonly baseUrl: string;
  private readonly anonKey: string;
  private refreshTimer: number | null = null;
  private readonly listeners = new Set<AuthListener>();

  constructor(baseUrl: string, anonKey: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.anonKey = anonKey;
  }

  async getSession(): Promise<AuthSession | null> {
    const stored = this.readSession();
    if (!stored) return null;
    if (stored.expires_at > Math.floor(Date.now() / 1000) + 60) {
      this.scheduleRefresh(stored);
      return stored;
    }
    if (!stored.refresh_token) return null;
    try {
      return await this.refresh(stored.refresh_token);
    } catch {
      this.clearSession();
      return null;
    }
  }

  async signIn(email: string, password: string): Promise<AuthSession> {
    return this.requestSession("/auth/v1/token?grant_type=password", { email, password });
  }

  async signUp(email: string, password: string): Promise<AuthSession | null> {
    const response = await this.request<{ access_token?: string; refresh_token?: string; expires_in?: number; user?: AuthUser }>(
      "/auth/v1/signup",
      { email, password },
    );
    if (!response.access_token || !response.refresh_token || !response.user) return null;
    return this.persist({
      access_token: response.access_token,
      refresh_token: response.refresh_token,
      expires_in: response.expires_in ?? 3600,
      expires_at: Math.floor(Date.now() / 1000) + (response.expires_in ?? 3600),
      user: response.user,
    });
  }

  async signOut(): Promise<void> {
    const session = this.readSession();
    if (session) {
      await fetch(`${this.baseUrl}/auth/v1/logout`, {
        method: "POST",
        headers: this.headers(session.access_token),
      }).catch(() => undefined);
    }
    this.clearSession();
  }

  onAuthStateChange(listener: AuthListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private async refresh(refreshToken: string): Promise<AuthSession> {
    const response = await this.requestSession("/auth/v1/token?grant_type=refresh_token", {
      refresh_token: refreshToken,
    });
    return response;
  }

  private async requestSession(path: string, body: Record<string, string>): Promise<AuthSession> {
    const response = await this.request<{ access_token: string; refresh_token: string; expires_in?: number; user: AuthUser }>(path, body);
    const expiresIn = response.expires_in ?? 3600;
    return this.persist({
      access_token: response.access_token,
      refresh_token: response.refresh_token,
      expires_in: expiresIn,
      expires_at: Math.floor(Date.now() / 1000) + expiresIn,
      user: response.user,
    });
  }

  private async request<T>(path: string, body: Record<string, string>): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.msg ?? payload?.error_description ?? payload?.message ?? "Authentication request failed.");
    return payload as T;
  }

  private persist(session: AuthSession): AuthSession {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    this.scheduleRefresh(session);
    for (const listener of this.listeners) listener(session);
    return session;
  }

  private scheduleRefresh(session: AuthSession): void {
    if (this.refreshTimer !== null) window.clearTimeout(this.refreshTimer);
    const delay = Math.max(5_000, (session.expires_at - Math.floor(Date.now() / 1000) - 60) * 1000);
    this.refreshTimer = window.setTimeout(() => {
      void this.getSession();
    }, delay);
  }

  private clearSession(): void {
    localStorage.removeItem(SESSION_KEY);
    if (this.refreshTimer !== null) window.clearTimeout(this.refreshTimer);
    this.refreshTimer = null;
    for (const listener of this.listeners) listener(null);
  }

  private readSession(): AuthSession | null {
    try {
      const raw = localStorage.getItem(SESSION_KEY);
      if (!raw) return null;
      const value = JSON.parse(raw) as AuthSession;
      return value.access_token && value.refresh_token && value.user?.id ? value : null;
    } catch {
      return null;
    }
  }

  private headers(accessToken?: string): Record<string, string> {
    return {
      apikey: this.anonKey,
      Authorization: `Bearer ${accessToken ?? this.anonKey}`,
      "Content-Type": "application/json",
    };
  }
}

export function createSupabaseAuthClient(): SupabaseAuthClient | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  return url && anonKey ? new SupabaseAuthClient(url, anonKey) : null;
}
