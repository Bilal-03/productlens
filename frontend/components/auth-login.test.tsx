import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthLogin } from "@/components/auth-login";
import { useAuth } from "@/components/auth-provider";

const push = vi.fn();

vi.mock("@/components/auth-provider", () => ({ useAuth: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next/link", () => ({ default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a> }));

function authValue(overrides: Partial<ReturnType<typeof useAuth>> = {}): ReturnType<typeof useAuth> {
  return {
    configured: true,
    loading: false,
    session: null,
    user: null,
    error: null,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
    ...overrides,
  };
}

describe("workspace authentication surface", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("submits credentials through the auth provider and redirects", async () => {
    const signIn = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useAuth).mockReturnValue(authValue({ signIn }));
    render(<AuthLogin />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "analyst@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password123" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(signIn).toHaveBeenCalledWith("analyst@example.com", "password123"));
    expect(push).toHaveBeenCalledWith("/");
  });

  it("keeps the anonymous demo path visible when Auth is not configured", () => {
    vi.mocked(useAuth).mockReturnValue(authValue({ configured: false }));
    render(<AuthLogin />);

    expect(screen.getByText("Supabase Auth is optional")).toBeVisible();
    expect(screen.getByRole("link", { name: /Back to demo/ })).toHaveAttribute("href", "/");
  });
});
