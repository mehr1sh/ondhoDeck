/**
 * Public runtime configuration. Values are read lazily (never at import time) so the app can
 * build and render a configuration-error screen when they are missing.
 *
 * NEXT_PUBLIC_* values are inlined by Next.js at build time, so each must be referenced literally.
 */
export interface PublicEnv {
  supabaseUrl: string;
  supabaseAnonKey: string;
  apiBaseUrl: string;
}

export type EnvCheck = { ok: true; env: PublicEnv } | { ok: false; missing: string[] };

export function checkPublicEnv(): EnvCheck {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
  const missing: string[] = [];
  if (!supabaseUrl.trim()) missing.push("NEXT_PUBLIC_SUPABASE_URL");
  if (!supabaseAnonKey.trim()) missing.push("NEXT_PUBLIC_SUPABASE_ANON_KEY");
  if (!apiBaseUrl.trim()) missing.push("NEXT_PUBLIC_API_BASE_URL");
  if (missing.length) return { ok: false, missing };
  return {
    ok: true,
    env: {
      supabaseUrl: supabaseUrl.trim(),
      supabaseAnonKey: supabaseAnonKey.trim(),
      apiBaseUrl: apiBaseUrl.trim().replace(/\/+$/, ""),
    },
  };
}

export class ConfigError extends Error {
  constructor(public missing: string[]) {
    super(`Missing configuration: ${missing.join(", ")}`);
    this.name = "ConfigError";
  }
}

export function getPublicEnv(): PublicEnv {
  const check = checkPublicEnv();
  if (!check.ok) throw new ConfigError(check.missing);
  return check.env;
}
