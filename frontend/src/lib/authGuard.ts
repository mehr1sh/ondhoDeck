/** Routing rules shared by the middleware and the client-side guard. */

export const PUBLIC_AUTH_PATHS = ["/login", "/register", "/reset-password"] as const;
/** Reachable with or without a session (the recovery link creates a short-lived session). */
export const NEUTRAL_PATHS = ["/update-password"] as const;

function matches(pathname: string, list: readonly string[]): boolean {
  return list.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function isPublicAuthPath(pathname: string): boolean {
  return matches(pathname, PUBLIC_AUTH_PATHS);
}

export function isNeutralPath(pathname: string): boolean {
  return matches(pathname, NEUTRAL_PATHS);
}

/** Only allow same-site relative redirects (prevents open redirects via ?next=). */
export function safeNextPath(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/";
  if (isPublicAuthPath(next.split("?")[0] ?? "")) return "/";
  return next;
}

export function loginUrlFor(pathname: string, search = "", reason?: string): string {
  const params = new URLSearchParams();
  const next = `${pathname}${search}`;
  if (next && next !== "/") params.set("next", next);
  if (reason) params.set("reason", reason);
  const qs = params.toString();
  return qs ? `/login?${qs}` : "/login";
}

/**
 * Decide whether a request should be redirected.
 * Returns the redirect target (path + query) or null to continue.
 */
export function decideAuthRedirect(
  pathname: string,
  search: string,
  isAuthenticated: boolean,
  nextParam?: string | null,
): string | null {
  if (isNeutralPath(pathname)) return null;
  if (isPublicAuthPath(pathname)) {
    return isAuthenticated ? safeNextPath(nextParam) : null;
  }
  return isAuthenticated ? null : loginUrlFor(pathname, search);
}
