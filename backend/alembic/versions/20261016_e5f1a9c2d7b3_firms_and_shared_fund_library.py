"""firms and shared fund library

Adds firms (access boundary), firm members (admin / reviewer / advisor), canonical library funds, and
lets documents, pages, jobs, constraints and constraint revisions belong to a library fund instead of
a household (exactly one owner, enforced by CHECK). Library terms gain an effective window and an
explicit supersession link; library documents gain an effective date and a "supersedes" link.

Data steps (no rows are deleted or rewritten):
- every existing profile gets one firm ("My firm") with itself as admin;
- every household is assigned to the firm of the profile that created it.

RLS: library rows are readable by members of the fund's firm; household rows keep the existing
membership policy. Downgrade refuses to run while any library fund or added firm member exists,
because it would destroy that data.

Revision ID: e5f1a9c2d7b3
Revises: c3d9e2b7a4f1
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5f1a9c2d7b3"
down_revision: Union[str, None] = "c3d9e2b7a4f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DUAL_OWNED = ["documents", "document_pages", "processing_jobs", "extracted_constraints", "constraint_revisions"]
OLD_CATEGORIES = ("prospectus", "interval_fund", "private_fund_agreement", "sbl_agreement", "rsu_grant", "other")
NEW_CATEGORIES = ("prospectus", "prospectus_supplement", "statement_of_additional_information", "interval_fund",
                  "private_fund_agreement", "sbl_agreement", "rsu_grant", "other")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _uuid(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.UUID(), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "firms",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        _uuid("created_by"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "firm_members",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        _uuid("firm_id", False), _uuid("user_id", False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'reviewer', 'advisor')", name="ck_firm_members_role"),
        sa.ForeignKeyConstraint(["firm_id"], ["firms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("firm_id", "user_id", name="uq_firm_members_firm_user"),
    )
    op.create_index("ix_firm_members_firm_id", "firm_members", ["firm_id"])
    op.create_index("ix_firm_members_user_id", "firm_members", ["user_id"])
    op.create_table(
        "funds",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        _uuid("firm_id", False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("fund_type", sa.String(24), nullable=False),
        sa.Column("issuer", sa.String(200)),
        sa.Column("ticker", sa.String(16)),
        sa.Column("share_class", sa.String(40)),
        sa.Column("sec_cik", sa.String(10)),
        sa.Column("aliases", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("metadata_status", sa.String(16), server_default="needs_review", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        _uuid("created_by"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("fund_type IN ('non_traded_reit', 'interval_fund', 'private_fund', 'other')",
                           name="ck_funds_type"),
        sa.CheckConstraint("metadata_status IN ('needs_review', 'verified')", name="ck_funds_metadata_status"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_funds_status"),
        sa.CheckConstraint("sec_cik IS NULL OR sec_cik ~ '^[0-9]{1,10}$'", name="ck_funds_cik"),
        sa.ForeignKeyConstraint(["firm_id"], ["firms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_funds_firm_id", "funds", ["firm_id"])
    op.execute("CREATE UNIQUE INDEX uq_funds_firm_name_class ON funds (firm_id, lower(name), "
               "coalesce(share_class, ''))")

    # --- data: one firm per existing profile; households join their creator's firm -----------------
    op.execute("INSERT INTO firms (name, created_by) SELECT 'My firm', p.id FROM profiles p")
    op.execute("INSERT INTO firm_members (firm_id, user_id, role) SELECT f.id, f.created_by, 'admin' FROM firms f")
    op.add_column("households", _uuid("firm_id"))
    op.execute("UPDATE households h SET firm_id = f.id FROM firms f WHERE f.created_by = h.created_by")
    op.alter_column("households", "firm_id", nullable=False)
    op.create_foreign_key("households_firm_id_fkey", "households", "firms", ["firm_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_households_firm_id", "households", ["firm_id"])

    op.add_column("assets", _uuid("fund_id"))
    op.create_foreign_key("assets_fund_id_fkey", "assets", "funds", ["fund_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_assets_fund_id", "assets", ["fund_id"])

    # --- dual ownership ------------------------------------------------------------------------------
    for table in DUAL_OWNED:
        op.alter_column(table, "household_id", nullable=True)
        op.add_column(table, _uuid("fund_id"))
        op.create_foreign_key(f"{table}_fund_id_fkey", table, "funds", ["fund_id"], ["id"], ondelete="RESTRICT")
        op.create_index(f"ix_{table}_fund_id", table, ["fund_id"])
        op.create_check_constraint(f"ck_{table}_one_owner", table, "num_nonnulls(household_id, fund_id) = 1")

    op.add_column("documents", sa.Column("effective_date", sa.Date()))
    op.add_column("documents", _uuid("supersedes_document_id"))
    op.create_foreign_key("documents_supersedes_document_id_fkey", "documents", "documents",
                          ["supersedes_document_id"], ["id"], ondelete="SET NULL")
    op.drop_constraint("ck_documents_category", "documents", type_="check")
    op.create_check_constraint("ck_documents_category", "documents", f"category IN ({_in(NEW_CATEGORIES)})")
    op.create_index("uq_documents_fund_sha256_live", "documents", ["fund_id", "sha256"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL AND sha256 IS NOT NULL AND fund_id IS NOT NULL"))

    op.add_column("extracted_constraints", sa.Column("effective_from", sa.Date()))
    op.add_column("extracted_constraints", sa.Column("effective_to", sa.Date()))
    op.add_column("extracted_constraints", _uuid("superseded_by_id"))
    op.create_foreign_key("extracted_constraints_superseded_by_id_fkey", "extracted_constraints",
                          "extracted_constraints", ["superseded_by_id"], ["id"], ondelete="SET NULL")
    op.create_check_constraint("ck_extracted_constraints_window", "extracted_constraints",
                               "effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from")

    op.add_column("audit_events", _uuid("firm_id"))
    op.add_column("audit_events", _uuid("fund_id"))
    op.create_foreign_key("audit_events_firm_id_fkey", "audit_events", "firms", ["firm_id"], ["id"],
                          ondelete="SET NULL")
    op.create_foreign_key("audit_events_fund_id_fkey", "audit_events", "funds", ["fund_id"], ["id"],
                          ondelete="SET NULL")
    op.create_index("ix_audit_events_fund_created", "audit_events", ["fund_id", "created_at"])

    # --- RLS -----------------------------------------------------------------------------------------
    op.execute("""
    CREATE OR REPLACE FUNCTION public.is_firm_member(fid uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT EXISTS (SELECT 1 FROM public.firm_members m WHERE m.firm_id = fid AND m.user_id = auth.uid())
    $$;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION public.is_fund_reader(fund uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT EXISTS (SELECT 1 FROM public.funds f JOIN public.firm_members m ON m.firm_id = f.firm_id
                     WHERE f.id = fund AND m.user_id = auth.uid())
    $$;
    """)
    for fn in ("is_firm_member", "is_fund_reader"):
        op.execute(f"REVOKE ALL ON FUNCTION public.{fn}(uuid) FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{fn}(uuid) TO authenticated")
    for table in ("firms", "firm_members", "funds"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON public.{table} FROM anon, authenticated")
        op.execute(f"GRANT SELECT ON public.{table} TO authenticated")
    op.execute("CREATE POLICY firms_select_member ON public.firms FOR SELECT TO authenticated "
               "USING (public.is_firm_member(id))")
    op.execute("CREATE POLICY firm_members_select_member ON public.firm_members FOR SELECT TO authenticated "
               "USING (public.is_firm_member(firm_id))")
    op.execute("CREATE POLICY funds_select_member ON public.funds FOR SELECT TO authenticated "
               "USING (public.is_firm_member(firm_id))")
    for table in DUAL_OWNED:
        op.execute(f"DROP POLICY IF EXISTS {table}_select_member ON public.{table}")
        op.execute(f"CREATE POLICY {table}_select_member ON public.{table} FOR SELECT TO authenticated "
                   "USING (public.is_household_member(household_id) "
                   "OR (fund_id IS NOT NULL AND public.is_fund_reader(fund_id)))")
    op.execute("DROP POLICY IF EXISTS audit_events_select_member ON public.audit_events")
    op.execute("CREATE POLICY audit_events_select_member ON public.audit_events FOR SELECT TO authenticated "
               "USING (public.is_household_member(household_id) "
               "OR (fund_id IS NOT NULL AND public.is_fund_reader(fund_id)) "
               "OR (household_id IS NULL AND fund_id IS NULL AND firm_id IS NOT NULL "
               "AND public.is_firm_member(firm_id)))")


def downgrade() -> None:
    conn = op.get_bind()
    funds = conn.execute(sa.text("SELECT count(*) FROM funds")).scalar_one()
    extra_members = conn.execute(sa.text("SELECT count(*) FROM firm_members m JOIN firms f ON f.id = m.firm_id "
                                         "WHERE m.user_id IS DISTINCT FROM f.created_by")).scalar_one()
    if funds or extra_members:
        raise RuntimeError(f"Refusing to downgrade: {funds} library fund(s) and {extra_members} added firm "
                           "member(s) would be destroyed. Export or remove them explicitly first.")

    op.execute("DROP POLICY IF EXISTS audit_events_select_member ON public.audit_events")
    op.execute("CREATE POLICY audit_events_select_member ON public.audit_events FOR SELECT TO authenticated "
               "USING (public.is_household_member(household_id))")
    for table in DUAL_OWNED:
        op.execute(f"DROP POLICY IF EXISTS {table}_select_member ON public.{table}")
        op.execute(f"CREATE POLICY {table}_select_member ON public.{table} FOR SELECT TO authenticated "
                   "USING (public.is_household_member(household_id))")
    for name, table in (("funds_select_member", "funds"), ("firm_members_select_member", "firm_members"),
                        ("firms_select_member", "firms")):
        op.execute(f"DROP POLICY IF EXISTS {name} ON public.{table}")

    op.drop_index("ix_audit_events_fund_created", table_name="audit_events")
    op.drop_constraint("audit_events_fund_id_fkey", "audit_events", type_="foreignkey")
    op.drop_constraint("audit_events_firm_id_fkey", "audit_events", type_="foreignkey")
    op.drop_column("audit_events", "fund_id")
    op.drop_column("audit_events", "firm_id")

    op.drop_constraint("ck_extracted_constraints_window", "extracted_constraints", type_="check")
    op.drop_constraint("extracted_constraints_superseded_by_id_fkey", "extracted_constraints", type_="foreignkey")
    for col in ("superseded_by_id", "effective_to", "effective_from"):
        op.drop_column("extracted_constraints", col)

    op.drop_index("uq_documents_fund_sha256_live", table_name="documents")
    op.drop_constraint("ck_documents_category", "documents", type_="check")
    op.create_check_constraint("ck_documents_category", "documents", f"category IN ({_in(OLD_CATEGORIES)})")
    op.drop_constraint("documents_supersedes_document_id_fkey", "documents", type_="foreignkey")
    op.drop_column("documents", "supersedes_document_id")
    op.drop_column("documents", "effective_date")

    for table in DUAL_OWNED:
        op.drop_constraint(f"ck_{table}_one_owner", table, type_="check")
        op.drop_index(f"ix_{table}_fund_id", table_name=table)
        op.drop_constraint(f"{table}_fund_id_fkey", table, type_="foreignkey")
        op.drop_column(table, "fund_id")
        op.alter_column(table, "household_id", nullable=False)

    op.drop_index("ix_assets_fund_id", table_name="assets")
    op.drop_constraint("assets_fund_id_fkey", "assets", type_="foreignkey")
    op.drop_column("assets", "fund_id")
    op.drop_index("ix_households_firm_id", table_name="households")
    op.drop_constraint("households_firm_id_fkey", "households", type_="foreignkey")
    op.drop_column("households", "firm_id")

    op.drop_index("uq_funds_firm_name_class", table_name="funds")
    op.drop_index("ix_funds_firm_id", table_name="funds")
    op.drop_table("funds")
    op.drop_index("ix_firm_members_user_id", table_name="firm_members")
    op.drop_index("ix_firm_members_firm_id", table_name="firm_members")
    op.drop_table("firm_members")
    op.drop_table("firms")
    op.execute("DROP FUNCTION IF EXISTS public.is_fund_reader(uuid)")
    op.execute("DROP FUNCTION IF EXISTS public.is_firm_member(uuid)")
