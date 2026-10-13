"""row level security

Defense in depth for data reachable through Supabase's auto-generated APIs (PostgREST).
The application backend connects as the table owner and enforces authorization itself;
these policies ensure that a browser holding a Supabase session can, at most, *read*
rows of households it is a member of, and can never write directly.

On Supabase the `anon`/`authenticated` roles and `auth.uid()` already exist and are reused.
On plain PostgreSQL (local development, CI) equivalents are created so the same policies
can be tested.

Revision ID: a7c3e1f20b11
Revises: 1d861e394495
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a7c3e1f20b11"
down_revision: Union[str, None] = "1d861e394495"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HOUSEHOLD_SCOPED = [
    "household_members", "assets", "liabilities", "cash_flows", "scheduled_events", "documents",
    "document_pages", "processing_jobs", "extracted_constraints", "constraint_revisions", "scenarios",
    "simulation_runs", "stress_results", "prevention_plans", "prevention_recommendations", "exports",
    "audit_events",
]
ALL_TABLES = ["profiles", "households", "simulation_months", *HOUSEHOLD_SCOPED]


def upgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
      END IF;
    END $$;
    """)
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")
    # Supabase-compatible auth.uid(); only created when the platform has not provided one.
    op.execute("""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname = 'auth' AND p.proname = 'uid') THEN
        EXECUTE $f$
          CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $body$
            SELECT nullif(coalesce(current_setting('request.jwt.claim.sub', true),
                                   current_setting('request.jwt.claims', true)::jsonb ->> 'sub'), '')::uuid
          $body$
        $f$;
      END IF;
    END $$;
    """)
    op.execute("GRANT USAGE ON SCHEMA auth TO anon, authenticated")
    op.execute("GRANT USAGE ON SCHEMA public TO anon, authenticated")
    # SECURITY DEFINER so the membership lookup is not itself filtered by RLS (avoids recursion).
    op.execute("""
    CREATE OR REPLACE FUNCTION public.is_household_member(hid uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT EXISTS (SELECT 1 FROM public.household_members m WHERE m.household_id = hid AND m.user_id = auth.uid())
    $$;
    """)
    op.execute("REVOKE ALL ON FUNCTION public.is_household_member(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.is_household_member(uuid) TO authenticated")

    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON public.{table} FROM anon, authenticated")
        op.execute(f"GRANT SELECT ON public.{table} TO authenticated")

    op.execute("CREATE POLICY profiles_select_own ON public.profiles FOR SELECT TO authenticated "
               "USING (id = auth.uid())")
    op.execute("CREATE POLICY households_select_member ON public.households FOR SELECT TO authenticated "
               "USING (public.is_household_member(id))")
    for table in HOUSEHOLD_SCOPED:
        op.execute(f"CREATE POLICY {table}_select_member ON public.{table} FOR SELECT TO authenticated "
                   f"USING (public.is_household_member(household_id))")
    op.execute("""
    CREATE POLICY simulation_months_select_member ON public.simulation_months FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.simulation_runs r
                   WHERE r.id = run_id AND public.is_household_member(r.household_id)))
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS simulation_months_select_member ON public.simulation_months")
    for table in HOUSEHOLD_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS {table}_select_member ON public.{table}")
    op.execute("DROP POLICY IF EXISTS households_select_member ON public.households")
    op.execute("DROP POLICY IF EXISTS profiles_select_own ON public.profiles")
    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS public.is_household_member(uuid)")
