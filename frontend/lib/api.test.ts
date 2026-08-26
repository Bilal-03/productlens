import { afterEach, describe, expect, it, vi } from "vitest";
import { api, getAccessHeaders, getAccessToken, setAccessToken } from "@/lib/api";

describe("workspace access client", () => {
  afterEach(() => {
    setAccessToken(null);
    localStorage.removeItem("productlens-supabase-session");
    vi.restoreAllMocks();
  });

  it("keeps the optional access assertion in session storage", () => {
    expect(getAccessToken()).toBeNull();
    setAccessToken("signed-access-assertion");
    expect(getAccessToken()).toBe("signed-access-assertion");
    expect(getAccessHeaders()).toEqual({ "X-ProductLens-Access": "signed-access-assertion" });
    setAccessToken(null);
    expect(getAccessToken()).toBeNull();
  });

  it("attaches the assertion to every JSON API request", async () => {
    setAccessToken("signed-access-assertion");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );

    await api<{ ok: boolean }>("/access/context");

    const requestInit = fetchMock.mock.calls[0]?.[1];
    expect(new Headers(requestInit?.headers).get("X-ProductLens-Access")).toBe("signed-access-assertion");
    expect(new Headers(requestInit?.headers).get("Content-Type")).toBe("application/json");
  });

  it("uses the standard bearer header for OIDC-shaped tokens", () => {
    setAccessToken("eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature");

    expect(getAccessHeaders()).toEqual({
      Authorization: "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature",
    });
  });

  it("reuses a valid persisted Supabase token before auth state hydrates", () => {
    localStorage.setItem(
      "productlens-supabase-session",
      JSON.stringify({
        access_token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature",
        expires_at: Math.floor(Date.now() / 1000) + 3600,
      }),
    );

    expect(getAccessToken()).toBe("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature");
    expect(getAccessHeaders()).toEqual({
      Authorization: "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature",
    });
  });

  it("does not reuse an expired persisted Supabase token", () => {
    localStorage.setItem(
      "productlens-supabase-session",
      JSON.stringify({
        access_token: "expired.header.signature",
        expires_at: Math.floor(Date.now() / 1000) - 1,
      }),
    );

    expect(getAccessToken()).toBeNull();
  });
});
