import { afterEach, describe, expect, it, vi } from "vitest";
import { SupabaseAuthClient, type AuthSession } from "@/lib/supabase";

const session: AuthSession = {
  access_token: "eyJ.access.token",
  refresh_token: "refresh-token",
  expires_in: 3600,
  expires_at: Math.floor(Date.now() / 1000) + 3600,
  user: { id: "user-123", email: "analyst@example.com" },
};

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("native Supabase Auth client", () => {
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("signs in, persists the session, notifies listeners, and logs out", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(session))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const client = new SupabaseAuthClient("https://project.supabase.co/", "public-anon-key");
    const listener = vi.fn();
    client.onAuthStateChange(listener);

    const signedIn = await client.signIn("analyst@example.com", "password123");

    expect(signedIn.user.id).toBe("user-123");
    expect(JSON.parse(localStorage.getItem("productlens-supabase-session") ?? "null")).toMatchObject({
      access_token: session.access_token,
    });
    expect(listener).toHaveBeenCalledWith(signedIn);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://project.supabase.co/auth/v1/token?grant_type=password");
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("apikey")).toBe("public-anon-key");

    await client.signOut();

    expect(localStorage.getItem("productlens-supabase-session")).toBeNull();
    expect(listener).toHaveBeenLastCalledWith(null);
  });

  it("refreshes an expired session and safely handles email confirmation sign-up", async () => {
    localStorage.setItem(
      "productlens-supabase-session",
      JSON.stringify({ ...session, expires_at: 0 }),
    );
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(session))
      .mockResolvedValueOnce(jsonResponse({ user: { id: "pending-user" } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const client = new SupabaseAuthClient("https://project.supabase.co", "public-anon-key");

    const refreshed = await client.getSession();
    const pending = await client.signUp("new@example.com", "password123");

    expect(refreshed?.access_token).toBe(session.access_token);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://project.supabase.co/auth/v1/token?grant_type=refresh_token");
    expect(pending).toBeNull();
    expect(JSON.parse(localStorage.getItem("productlens-supabase-session") ?? "null").user.id).toBe("user-123");
    await client.signOut();
  });
});
