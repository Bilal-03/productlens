import { afterEach, describe, expect, it, vi } from "vitest";
import { api, getAccessHeaders, getAccessToken, setAccessToken } from "@/lib/api";

describe("workspace access client", () => {
  afterEach(() => {
    setAccessToken(null);
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
});
