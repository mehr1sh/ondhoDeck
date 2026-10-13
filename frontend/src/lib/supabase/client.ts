"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";
import { getPublicEnv } from "@/lib/env";

let client: SupabaseClient | null = null;

/** Lazily-created singleton browser client. Throws ConfigError if env is missing. */
export function getSupabaseBrowserClient(): SupabaseClient {
  if (client) return client;
  const env = getPublicEnv();
  client = createBrowserClient(env.supabaseUrl, env.supabaseAnonKey);
  return client;
}
