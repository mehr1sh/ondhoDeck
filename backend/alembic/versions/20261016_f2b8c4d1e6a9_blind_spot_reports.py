"""blind spot reports

Persisted results of the deterministic liquidity blind-spot battery, and a PDF export kind for them.
Household-scoped, with the same RLS policy as the other household tables.

Revision ID: f2b8c4d1e6a9
Revises: e5f1a9c2d7b3
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2b8c4d1e6a9"
down_revision: Union[str, None] = "e5f1a9c2d7b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_KINDS = "'constraints_csv', 'constraints_json', 'simulation_csv', 'results_json', 'report_pdf'"


def upgrade() -> None:
    op.create_table(
        "blind_spot_reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("scenario_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("engine_version", sa.String(16), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("inputs_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("terms_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("constraint_versions", postgresql.JSONB(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("risk_count", sa.Integer(), nullable=False),
        sa.Column("blind_spot_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_blind_spot_reports_household_id", "blind_spot_reports", ["household_id"])
    op.create_index("ix_blind_spot_reports_scenario_id", "blind_spot_reports", ["scenario_id"])
    op.add_column("exports", sa.Column("blind_spot_report_id", sa.UUID()))
    op.create_foreign_key("exports_blind_spot_report_id_fkey", "exports", "blind_spot_reports",
                          ["blind_spot_report_id"], ["id"], ondelete="CASCADE")
    op.drop_constraint("ck_exports_kind", "exports", type_="check")
    op.create_check_constraint("ck_exports_kind", "exports", f"kind IN ({OLD_KINDS}, 'blind_spot_pdf')")

    op.execute("ALTER TABLE public.blind_spot_reports ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON public.blind_spot_reports FROM anon, authenticated")
    op.execute("GRANT SELECT ON public.blind_spot_reports TO authenticated")
    op.execute("CREATE POLICY blind_spot_reports_select_member ON public.blind_spot_reports FOR SELECT "
               "TO authenticated USING (public.is_household_member(household_id))")


def downgrade() -> None:
    n = op.get_bind().execute(sa.text("SELECT count(*) FROM exports WHERE kind = 'blind_spot_pdf'")).scalar_one()
    if n:
        raise RuntimeError(f"Refusing to downgrade: {n} blind-spot PDF export record(s) exist.")
    op.drop_constraint("ck_exports_kind", "exports", type_="check")
    op.create_check_constraint("ck_exports_kind", "exports", f"kind IN ({OLD_KINDS})")
    op.drop_constraint("exports_blind_spot_report_id_fkey", "exports", type_="foreignkey")
    op.drop_column("exports", "blind_spot_report_id")
    op.execute("DROP POLICY IF EXISTS blind_spot_reports_select_member ON public.blind_spot_reports")
    op.drop_index("ix_blind_spot_reports_scenario_id", table_name="blind_spot_reports")
    op.drop_index("ix_blind_spot_reports_household_id", table_name="blind_spot_reports")
    op.drop_table("blind_spot_reports")
