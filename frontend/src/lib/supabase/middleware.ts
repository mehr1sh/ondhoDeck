import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { decideAuthRedirect } from "@/lib/authGuard";
import { checkPublicEnv } from "@/lib/env";

/** Refreshes the Supabase session cookie and applies protected-route redirects. */
export async function updateSession(request: NextRequest): Promise<NextResponse> {
  const check = checkPublicEnv();
  // Without configuration the client renders a configuration-error screen.
  if (!check.ok) return NextResponse.next({ request });

  let response = NextResponse.next({ request });
  const supabase = createServerClient(check.env.supabaseUrl, check.env.supabaseAnonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet: { name: string; value: string; options?: CookieOptions }[]) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });

  let authenticated = false;
  try {
    const { data } = await supabase.auth.getUser();
    authenticated = Boolean(data.user);
  } catch {
    authenticated = false;
  }

  const { pathname, search, searchParams } = request.nextUrl;
  const target = decideAuthRedirect(pathname, search, authenticated, searchParams.get("next"));
  if (!target) return response;

  const url = request.nextUrl.clone();
  const [path, query] = target.split("?");
  url.pathname = path ?? "/";
  url.search = query ? `?${query}` : "";
  const redirect = NextResponse.redirect(url);
  // Preserve refreshed auth cookies on the redirect.
  response.cookies.getAll().forEach((c) => redirect.cookies.set(c));
  return redirect;
}
