-- Local development database bootstrap (docker-compose). NOT used on Supabase.
CREATE ROLE slipslopes LOGIN PASSWORD 'slipslopes' CREATEDB;
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
GRANT anon, authenticated TO slipslopes;
CREATE DATABASE slipslopes OWNER slipslopes;
CREATE DATABASE slipslopes_test OWNER slipslopes;

-- Local Supabase Auth (GoTrue) keeps its own database, like the hosted platform's auth schema.
CREATE ROLE supabase_auth_admin LOGIN PASSWORD 'auth-local-only' NOINHERIT CREATEROLE;
ALTER ROLE supabase_auth_admin SET search_path = auth;
CREATE DATABASE slipslopes_auth OWNER supabase_auth_admin;
\connect slipslopes_auth
CREATE SCHEMA auth AUTHORIZATION supabase_auth_admin;
