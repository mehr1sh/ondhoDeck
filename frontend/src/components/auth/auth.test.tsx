import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeAuthMock } from "@/test/utils";

const { auth, nav } = vi.hoisted(() => ({
  auth: {} as Record<string, ReturnType<typeof vi.fn>>,
  nav: { replace: vi.fn(), push: vi.fn(), refresh: vi.fn(), params: new URLSearchParams() },
}));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));
vi.mock("next/navigation", () => ({
  useRouter: () => nav,
  useSearchParams: () => nav.params,
  usePathname: () => "/login",
}));

import { LoginForm } from "./LoginForm";
import { RegisterForm } from "./RegisterForm";

beforeEach(() => {
  Object.assign(
    auth,
    makeAuthMock({ getSession: vi.fn(async () => ({ data: { session: null }, error: null })) }),
  );
  nav.replace.mockReset();
  nav.params = new URLSearchParams();
});

describe("LoginForm", () => {
  it("validates required fields without calling Supabase", async () => {
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your email address.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Email/)).toHaveAttribute("aria-invalid", "true");
    expect(auth.signInWithPassword).not.toHaveBeenCalled();
  });

  it("rejects a malformed email", async () => {
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText(/Email/), "not-an-email");
    await user.type(screen.getByLabelText(/Password/), "secret123");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(auth.signInWithPassword).not.toHaveBeenCalled();
  });

  it("shows the auth error from Supabase", async () => {
    auth.signInWithPassword.mockResolvedValue({ data: {}, error: { message: "Invalid login credentials", status: 400 } });
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText(/Email/), "pat@example.com");
    await user.type(screen.getByLabelText(/Password/), "wrongpass");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
    expect(auth.signInWithPassword).toHaveBeenCalledWith({ email: "pat@example.com", password: "wrongpass" });
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("redirects to the safe next path after sign-in", async () => {
    nav.params = new URLSearchParams("next=/households/h1");
    auth.signInWithPassword.mockResolvedValue({ data: { session: {} }, error: null });
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText(/Email/), "pat@example.com");
    await user.type(screen.getByLabelText(/Password/), "rightpass");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/households/h1"));
  });

  it("explains an expired session", () => {
    nav.params = new URLSearchParams("reason=expired");
    render(<LoginForm />);
    expect(screen.getByText(/Your session expired/)).toBeInTheDocument();
  });
});

describe("RegisterForm", () => {
  it("shows the check-your-email state when confirmation is required", async () => {
    auth.signUp.mockResolvedValue({ data: { user: { id: "u1" }, session: null }, error: null });
    const user = userEvent.setup();
    render(<RegisterForm />);
    await user.type(screen.getByLabelText(/^Email/), "new@example.com");
    await user.type(screen.getByLabelText(/^Password/), "longenough");
    await user.type(screen.getByLabelText(/Confirm password/), "longenough");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(screen.getByText("new@example.com")).toBeInTheDocument();
    const args = auth.signUp.mock.calls[0]![0];
    expect(args.email).toBe("new@example.com");
    expect(args.options.emailRedirectTo).toMatch(/\/login$/);
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("validates password length and confirmation", async () => {
    const user = userEvent.setup();
    render(<RegisterForm />);
    await user.type(screen.getByLabelText(/^Email/), "new@example.com");
    await user.type(screen.getByLabelText(/^Password/), "short");
    await user.type(screen.getByLabelText(/Confirm password/), "different");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Use at least 8 characters.")).toBeInTheDocument();
    expect(screen.getByText("Passwords do not match.")).toBeInTheDocument();
    expect(auth.signUp).not.toHaveBeenCalled();
  });
});
