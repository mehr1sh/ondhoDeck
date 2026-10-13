import { describe, expect, it } from "vitest";
import { decideAuthRedirect, loginUrlFor, safeNextPath } from "./authGuard";

describe("decideAuthRedirect", () => {
  it("redirects unauthenticated users on protected routes to login with next", () => {
    expect(decideAuthRedirect("/households/abc", "?tab=1", false)).toBe(
      "/login?next=%2Fhouseholds%2Fabc%3Ftab%3D1",
    );
    expect(decideAuthRedirect("/", "", false)).toBe("/login");
    expect(decideAuthRedirect("/settings", "", false)).toBe("/login?next=%2Fsettings");
  });
  it("lets authenticated users through protected routes", () => {
    expect(decideAuthRedirect("/households/abc", "", true)).toBeNull();
  });
  it("keeps auth pages public and sends signed-in users onward", () => {
    expect(decideAuthRedirect("/login", "", false)).toBeNull();
    expect(decideAuthRedirect("/register", "", false)).toBeNull();
    expect(decideAuthRedirect("/reset-password", "", false)).toBeNull();
    expect(decideAuthRedirect("/login", "?next=/settings", true, "/settings")).toBe("/settings");
  });
  it("never redirects the password-update page", () => {
    expect(decideAuthRedirect("/update-password", "", false)).toBeNull();
    expect(decideAuthRedirect("/update-password", "", true)).toBeNull();
  });
});

describe("safeNextPath", () => {
  it("rejects external and protocol-relative targets", () => {
    expect(safeNextPath("https://evil.example")).toBe("/");
    expect(safeNextPath("//evil.example")).toBe("/");
    expect(safeNextPath("/\\evil.example")).toBe("/");
    expect(safeNextPath("/login")).toBe("/");
    expect(safeNextPath("/households/1")).toBe("/households/1");
    expect(safeNextPath(null)).toBe("/");
  });
  it("builds login URLs with a reason", () => {
    expect(loginUrlFor("/settings", "", "expired")).toBe("/login?next=%2Fsettings&reason=expired");
  });
});
