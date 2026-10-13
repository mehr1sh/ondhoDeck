-- One-time local/CI setup, run as a PostgreSQL superuser. NOT for Supabase (which provides these).
-- Creates the application role, databases and the Supabase-equivalent API roles used by RLS policies.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'slipslopes') THEN
    CREATE ROLE slipslopes LOGIN PASSWORD 'slipslopes' CREATEDB;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
END $$;
-- Lets the application role switch into `authenticated` in RLS tests (SET ROLE).
GRANT anon, authenticated TO slipslopes;
