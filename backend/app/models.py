"""SQLAlchemy ORM models.

Ownership model: every financial record belongs to a household; access to a household is
granted only through an explicit `household_members` row linking it to an authenticated
profile (the Supabase Auth user id). Households belong to a firm. Public fund offering
documents and their terms belong to a firm's shared fund library (`funds`) instead of a
household: documents, pages, jobs, constraints and revisions carry exactly one owner
(`household_id` XOR `fund_id`). Library access is granted through `firm_members`.
Enumerations are stored as constrained strings so that adding a value is a plain migration.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

MONEY = Numeric(18, 2)


def _enum_check(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    quoted = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=name)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now(), nullable=False)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                         server_default=text("gen_random_uuid()"))


def household_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), nullable=False,
                         index=True)


def owner_household_fk() -> Mapped[Optional[uuid.UUID]]:
    """Household owner of a row that may instead belong to a library fund."""
    return mapped_column(UUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), index=True)


def owner_fund_fk() -> Mapped[Optional[uuid.UUID]]:
    """Library fund owner. RESTRICT: funds are archived, never deleted, so run history stays resolvable."""
    return mapped_column(UUID(as_uuid=True), ForeignKey("funds.id", ondelete="RESTRICT"), index=True)


def _one_owner(table: str) -> CheckConstraint:
    return CheckConstraint("num_nonnulls(household_id, fund_id) = 1", name=f"ck_{table}_one_owner")


# ----------------------------------------------------------------------------- identities

class Profile(TimestampMixin, Base):
    __tablename__ = "profiles"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)  # = auth.users.id (JWT sub)
    email: Mapped[Optional[str]] = mapped_column(String(320))
    display_name: Mapped[Optional[str]] = mapped_column(String(120))
    reporting_currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")


FIRM_ROLES = ("admin", "reviewer", "advisor")


class Firm(TimestampMixin, Base):
    """Access boundary for the shared fund library. Every profile has at least one firm."""
    __tablename__ = "firms"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True),
                                                            ForeignKey("profiles.id", ondelete="SET NULL"))


class FirmMember(Base):
    """admin: manage members and library; reviewer: approve/supersede library terms; advisor: read, add funds
    and documents, link holdings."""
    __tablename__ = "firm_members"
    id: Mapped[uuid.UUID] = uuid_pk()
    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("firm_id", "user_id", name="uq_firm_members_firm_user"),
                      _enum_check("role", FIRM_ROLES, "ck_firm_members_role"))


FUND_TYPES = ("non_traded_reit", "interval_fund", "private_fund", "other")
FUND_METADATA_STATUSES = ("needs_review", "verified")
FUND_STATUSES = ("active", "archived")


class Fund(TimestampMixin, Base):
    """Canonical record of a publicly offered fund in a firm's library. Holdings reference it via assets.fund_id."""
    __tablename__ = "funds"
    id: Mapped[uuid.UUID] = uuid_pk()
    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id", ondelete="RESTRICT"),
                                               nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    fund_type: Mapped[str] = mapped_column(String(24), nullable=False)
    issuer: Mapped[Optional[str]] = mapped_column(String(200))
    ticker: Mapped[Optional[str]] = mapped_column(String(16))
    share_class: Mapped[Optional[str]] = mapped_column(String(40))
    sec_cik: Mapped[Optional[str]] = mapped_column(String(10))
    aliases: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    metadata_status: Mapped[str] = mapped_column(String(16), default="needs_review", server_default="needs_review",
                                                 nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active", nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True),
                                                            ForeignKey("profiles.id", ondelete="SET NULL"))
    __table_args__ = (
        _enum_check("fund_type", FUND_TYPES, "ck_funds_type"),
        _enum_check("metadata_status", FUND_METADATA_STATUSES, "ck_funds_metadata_status"),
        _enum_check("status", FUND_STATUSES, "ck_funds_status"),
        CheckConstraint("sec_cik IS NULL OR sec_cik ~ '^[0-9]{1,10}$'", name="ck_funds_cik"),
        Index("uq_funds_firm_name_class", "firm_id", text("lower(name)"), text("coalesce(share_class, '')"),
              unique=True),
    )


CREDENTIAL_PROVIDERS = ("anthropic", "openai")
CREDENTIAL_STATUSES = ("untested", "valid", "invalid", "quota_exceeded", "error")


class ProviderCredential(TimestampMixin, Base):
    """A user's own LLM provider API key (BYOK). Only ciphertext is stored; it is never returned by the API."""
    __tablename__ = "provider_credentials"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(120))
    # Anthropic keys not scoped to a workspace must send this ID in the anthropic-workspace-id header.
    # An identifier, not a secret.
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="untested", server_default="untested", nullable=False)
    last_tested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[Optional[str]] = mapped_column(String(40))
    last_error: Mapped[Optional[str]] = mapped_column(String(300))
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_provider_credentials_user_provider"),
        Index("uq_provider_credentials_one_active", "user_id", unique=True, postgresql_where=text("is_active")),
        _enum_check("provider", CREDENTIAL_PROVIDERS, "ck_provider_credentials_provider"),
        _enum_check("status", CREDENTIAL_STATUSES, "ck_provider_credentials_status"),
    )


ROLES = ("owner", "editor", "viewer")


class Household(TimestampMixin, Base):
    __tablename__ = "households"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD", nullable=False)
    start_calendar_month: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id", ondelete="RESTRICT"),
                                               nullable=False, index=True)
    members: Mapped[list[HouseholdMember]] = relationship(back_populates="household", cascade="all, delete-orphan")
    __table_args__ = (CheckConstraint("start_calendar_month BETWEEN 1 AND 12", name="ck_households_start_month"),
                      CheckConstraint("reporting_currency ~ '^[A-Z]{3}$'", name="ck_households_currency"))


class HouseholdMember(Base):
    __tablename__ = "household_members"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = household_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    household: Mapped[Household] = relationship(back_populates="members")
    __table_args__ = (UniqueConstraint("household_id", "user_id", name="uq_household_members_household_user"),
                      _enum_check("role", ROLES, "ck_household_members_role"))


# ----------------------------------------------------------------------------- financial profile

ASSET_KINDS = ("cash", "brokerage", "non_traded_reit", "interval_fund", "private_fund_commitment", "vested_rsu",
               "other")


class Asset(TimestampMixin, Base):
    __tablename__ = "assets"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = household_fk()
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    as_of: Mapped[Optional[date]] = mapped_column(Date)
    pledged_to_sbl: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    unfunded_commitment: Mapped[Optional[Decimal]] = mapped_column(MONEY)
    liquidity_notes: Mapped[Optional[str]] = mapped_column(Text)
    # Holding of a shared library fund (same firm as the household); its approved terms apply to this asset.
    fund_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funds.id", ondelete="RESTRICT"), index=True)
    fund: Mapped[Optional[Fund]] = relationship(lazy="select")

    @property
    def fund_name(self) -> Optional[str]:
        return self.fund.name if self.fund is not None else None

    __table_args__ = (_enum_check("kind", ASSET_KINDS, "ck_assets_kind"),
                      CheckConstraint("amount >= 0", name="ck_assets_amount"),
                      CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_assets_currency"))


LIABILITY_KINDS = ("sbl", "mortgage", "other_loan", "other")


class Liability(TimestampMixin, Base):
    __tablename__ = "liabilities"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = household_fk()
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    annual_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    monthly_payment: Mapped[Optional[Decimal]] = mapped_column(MONEY)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    __table_args__ = (_enum_check("kind", LIABILITY_KINDS, "ck_liabilities_kind"),
                      CheckConstraint("balance >= 0", name="ck_liabilities_balance"),
                      CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_liabilities_currency"))


CASH_FLOW_KINDS = ("income", "core_expense", "discretionary_expense")


class CashFlow(TimestampMixin, Base):
    """Recurring monthly income or expense (constant over the projection)."""
    __tablename__ = "cash_flows"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = household_fk()
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    monthly_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    __table_args__ = (_enum_check("kind", CASH_FLOW_KINDS, "ck_cash_flows_kind"),
                      CheckConstraint("monthly_amount >= 0", name="ck_cash_flows_amount"),
                      CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_cash_flows_currency"))


EVENT_KINDS = ("capital_call", "rsu_vest", "tax_payment", "other_outflow", "other_inflow",
               "reit_redemption_request", "interval_redemption_request")


class ScheduledEvent(TimestampMixin, Base):
    """A dated obligation or plan item, expressed as a projection month (1 = first month)."""
    __tablename__ = "scheduled_events"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = household_fk()
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    tax_due_month: Mapped[Optional[int]] = mapped_column(Integer)  # rsu_vest only
    label: Mapped[Optional[str]] = mapped_column(String(160))
    __table_args__ = (_enum_check("kind", EVENT_KINDS, "ck_scheduled_events_kind"),
                      CheckConstraint("month BETWEEN 1 AND 120", name="ck_scheduled_events_month"),
                      CheckConstraint("amount >= 0", name="ck_scheduled_events_amount"),
                      CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_scheduled_events_currency"))


# ----------------------------------------------------------------------------- documents

DOC_CATEGORIES = ("prospectus", "prospectus_supplement", "statement_of_additional_information", "interval_fund",
                  "private_fund_agreement", "sbl_agreement", "rsu_grant", "other")
# Public offering documents that may live in the shared fund library.
FUND_DOC_CATEGORIES = ("prospectus", "prospectus_supplement", "statement_of_additional_information", "interval_fund",
                       "other")
DOC_STATUSES = ("pending_upload", "uploaded", "queued", "processing", "extracted", "failed", "deleted")


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[Optional[uuid.UUID]] = owner_household_fk()
    fund_id: Mapped[Optional[uuid.UUID]] = owner_fund_fk()
    # Library documents: date the document (or supplement) takes effect, and the document it replaces.
    effective_date: Mapped[Optional[date]] = mapped_column(Date)
    supersedes_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    storage_path: Mapped[Optional[str]] = mapped_column(String(512), unique=True)
    content_type: Mapped[str] = mapped_column(String(100), default="application/pdf", nullable=False)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    pages_without_text: Mapped[Optional[int]] = mapped_column(Integer)
    ocr_pages: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_upload")
    is_demo_fixture: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    error_message: Mapped[Optional[str]] = mapped_column(String(500))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        _enum_check("category", DOC_CATEGORIES, "ck_documents_category"),
        _enum_check("status", DOC_STATUSES, "ck_documents_status"),
        # The same file may be uploaded once per household (re-uploads return the existing record).
        Index("uq_documents_household_sha256_live", "household_id", "sha256", unique=True,
              postgresql_where=text("deleted_at IS NULL AND sha256 IS NOT NULL")),
        # ...and once per library fund (deduplication of public offering documents).
        Index("uq_documents_fund_sha256_live", "fund_id", "sha256", unique=True,
              postgresql_where=text("deleted_at IS NULL AND sha256 IS NOT NULL AND fund_id IS NOT NULL")),
        _one_owner("documents"),
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"
    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"),
                                                   nullable=False)
    household_id: Mapped[Optional[uuid.UUID]] = owner_household_fk()
    fund_id: Mapped[Optional[uuid.UUID]] = owner_fund_fk()
    pdf_page: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_page: Mapped[Optional[str]] = mapped_column(String(16))
    section: Mapped[Optional[str]] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    ocr: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    __table_args__ = (UniqueConstraint("document_id", "pdf_page", name="uq_document_pages_doc_page"),
                      _one_owner("document_pages"))


JOB_STATUSES = ("queued", "running", "succeeded", "failed")


class ProcessingJob(TimestampMixin, Base):
    __tablename__ = "processing_jobs"
    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"),
                                                   nullable=False, index=True)
    household_id: Mapped[Optional[uuid.UUID]] = owner_household_fk()
    fund_id: Mapped[Optional[uuid.UUID]] = owner_fund_fk()
    kind: Mapped[str] = mapped_column(String(32), default="extract_constraints", nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(64))
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    stage: Mapped[Optional[str]] = mapped_column(String(40))
    extraction_method: Mapped[Optional[str]] = mapped_column(String(20))
    provider: Mapped[Optional[str]] = mapped_column(String(40))
    model: Mapped[Optional[str]] = mapped_column(String(80))
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"))
    credential_source: Mapped[Optional[str]] = mapped_column(String(16))  # user_byok | server | none
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    error_message: Mapped[Optional[str]] = mapped_column(String(500))
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    __table_args__ = (
        _enum_check("status", JOB_STATUSES, "ck_processing_jobs_status"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_processing_jobs_progress"),
        # At most one active (queued/running) job per document.
        Index("uq_processing_jobs_active_per_document", "document_id", unique=True,
              postgresql_where=text("status IN ('queued', 'running')")),
        _one_owner("processing_jobs"),
    )


REVIEW_STATUSES = ("needs_review", "confirmed", "edited", "rejected")
SOURCE_TYPES = ("source_backed", "synthetic_document", "user_confirmed", "scenario_assumption")


class ExtractedConstraint(TimestampMixin, Base):
    __tablename__ = "extracted_constraints"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[Optional[uuid.UUID]] = owner_household_fk()
    fund_id: Mapped[Optional[uuid.UUID]] = owner_fund_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"),
                                                   nullable=False, index=True)
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True),
                                                        ForeignKey("processing_jobs.id", ondelete="SET NULL"))
    extraction_key: Mapped[str] = mapped_column(String(160), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    constraint_type: Mapped[str] = mapped_column(String(48), nullable=False)
    asset_key: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6))
    lower_bound: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6))
    upper_bound: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6))
    original_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6))
    unit: Mapped[Optional[str]] = mapped_column(String(80))
    timing: Mapped[Optional[str]] = mapped_column(String(160))
    conditions: Mapped[Optional[str]] = mapped_column(Text)
    pdf_page: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_page: Mapped[Optional[str]] = mapped_column(String(16))
    document_section: Mapped[Optional[str]] = mapped_column(String(120))
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    quote_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    corroborating_pages: Mapped[list[int]] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    interpretation: Mapped[str] = mapped_column(Text, nullable=False)
    value_kind: Mapped[Optional[str]] = mapped_column(String(16))
    exceptions: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    discretion: Mapped[Optional[str]] = mapped_column(Text)
    effective_period: Mapped[Optional[str]] = mapped_column(String(160))
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    validation_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]",
                                                                    nullable=False)
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="needs_review")
    extraction_method: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(40))
    model: Mapped[Optional[str]] = mapped_column(String(80))
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Validity window (library terms). effective_to is exclusive; set when a later term supersedes this one.
    effective_from: Mapped[Optional[date]] = mapped_column(Date)
    effective_to: Mapped[Optional[date]] = mapped_column(Date)
    superseded_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_constraints.id", ondelete="SET NULL"))
    __table_args__ = (
        _one_owner("extracted_constraints"),
        CheckConstraint("effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from",
                        name="ck_extracted_constraints_window"),
        _enum_check("review_status", REVIEW_STATUSES, "ck_extracted_constraints_review"),
        _enum_check("source_type", SOURCE_TYPES, "ck_extracted_constraints_source"),
        _enum_check("confidence", ("high", "medium", "low"), "ck_extracted_constraints_confidence"),
        CheckConstraint("pdf_page >= 1", name="ck_extracted_constraints_page"),
        # Re-running extraction for a document cannot duplicate a term.
        UniqueConstraint("document_id", "extraction_key", name="uq_extracted_constraints_doc_key"),
    )


class ConstraintRevision(Base):
    __tablename__ = "constraint_revisions"
    id: Mapped[uuid.UUID] = uuid_pk()
    constraint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_constraints.id", ondelete="CASCADE"), nullable=False)
    household_id: Mapped[Optional[uuid.UUID]] = owner_household_fk()
    fund_id: Mapped[Optional[uuid.UUID]] = owner_fund_fk()
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    change: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # {"field": {"from": x, "to": y}}
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # full state after the change
    note: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("constraint_id", "revision", name="uq_constraint_revisions_rev"),
                      _one_owner("constraint_revisions"))


# ----------------------------------------------------------------------------- analysis

class ScenarioDefinition(TimestampMixin, Base):
    __tablename__ = "scenarios"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = household_fk()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = household_fk()
    scenario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scenarios.id", ondelete="CASCADE"),
                                                   nullable=False, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    horizon_months: Mapped[int] = mapped_column(Integer, nullable=False)
    inputs_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    household_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    terms_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    constraint_versions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    naive_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    aware_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    liquidity: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    months: Mapped[list[SimulationMonth]] = relationship(cascade="all, delete-orphan",
                                                           order_by="SimulationMonth.month")
    __table_args__ = (Index("ix_simulation_runs_household_created", "household_id", "created_at"),
                      UniqueConstraint("household_id", "idempotency_key", name="uq_simulation_runs_idempotency"))


class SimulationMonth(Base):
    __tablename__ = "simulation_months"
    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"),
                                              nullable=False)
    model: Mapped[str] = mapped_column(String(16), nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(16), nullable=False)
    beginning_cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    income: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    expenses: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    taxes: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    debt_service: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    collateral_call: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    capital_call: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    redemption_requested: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    redemption_proceeds: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    other_proceeds: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    ending_cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    shortfall: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reit_fill_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 6))
    binding_constraints: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    __table_args__ = (UniqueConstraint("run_id", "model", "month", name="uq_simulation_months_run_model_month"),
                      _enum_check("model", ("naive", "contract_aware"), "ck_simulation_months_model"))


class StressResult(Base):
    __tablename__ = "stress_results"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = household_fk()
    scenario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scenarios.id", ondelete="CASCADE"),
                                                   nullable=False, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    inputs_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    terms_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    search: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # grid, bounds, step, tolerance
    found: Mapped[bool] = mapped_column(Boolean, nullable=False)
    boundary_drawdown: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 6))
    last_safe_drawdown: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 6))
    first_shortfall_month: Mapped[Optional[int]] = mapped_column(Integer)
    shortfall_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    grid_monotone: Mapped[bool] = mapped_column(Boolean, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    binding_constraints: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    attribution: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    key_events: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BlindSpotReport(Base):
    """Persisted result of the deterministic blind-spot battery for one scenario (see services/blind_spots)."""
    __tablename__ = "blind_spot_reports"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = household_fk()
    scenario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scenarios.id", ondelete="CASCADE"),
                                                   nullable=False, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    inputs_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    terms_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    constraint_versions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # method, risks, comparison, summary
    risk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    blind_spot_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PreventionPlan(Base):
    __tablename__ = "prevention_plans"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = household_fk()
    scenario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scenarios.id", ondelete="CASCADE"),
                                                   nullable=False, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    inputs_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    terms_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    cost_assumptions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    baseline_first_shortfall: Mapped[Optional[int]] = mapped_column(Integer)
    baseline_peak_shortfall: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    forced_liquidation_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    forced_liquidation_note: Mapped[str] = mapped_column(Text, nullable=False)
    combined_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    combined_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    combined_source: Mapped[str] = mapped_column(Text, nullable=False)
    combined_min_cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    combined_first_shortfall: Mapped[Optional[int]] = mapped_column(Integer)
    lp_status: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    recommendations: Mapped[list[PreventionRecommendation]] = relationship(
        cascade="all, delete-orphan", order_by="PreventionRecommendation.rank")


RECOMMENDATION_STATUSES = ("proposed", "approved", "rejected")


class PreventionRecommendation(Base):
    __tablename__ = "prevention_recommendations"
    id: Mapped[uuid.UUID] = uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                               ForeignKey("prevention_plans.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    household_id: Mapped[uuid.UUID] = household_fk()
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # single | combined
    lever: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cost_basis: Mapped[str] = mapped_column(Text, nullable=False)
    liquidity_benefit: Mapped[Optional[Decimal]] = mapped_column(MONEY)
    min_cash_after: Mapped[Optional[Decimal]] = mapped_column(MONEY)
    first_shortfall_after: Mapped[Optional[int]] = mapped_column(Integer)
    feasible_alone: Mapped[Optional[bool]] = mapped_column(Boolean)
    constraints_note: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (_enum_check("status", RECOMMENDATION_STATUSES, "ck_prevention_recommendations_status"),
                      _enum_check("kind", ("single", "combined"), "ck_prevention_recommendations_kind"),
                      UniqueConstraint("plan_id", "kind", "rank", name="uq_prevention_recommendations_rank"))


EXPORT_KINDS = ("constraints_csv", "constraints_json", "simulation_csv", "results_json", "report_pdf",
                "blind_spot_pdf")
EXPORT_STATUSES = ("queued", "running", "ready", "failed")


class ExportRecord(Base):
    __tablename__ = "exports"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = household_fk()
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True),
                                                        ForeignKey("simulation_runs.id", ondelete="CASCADE"))
    blind_spot_report_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("blind_spot_reports.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")
    storage_path: Mapped[Optional[str]] = mapped_column(String(512))
    filename: Mapped[Optional[str]] = mapped_column(String(160))
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    error_message: Mapped[Optional[str]] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (_enum_check("kind", EXPORT_KINDS, "ck_exports_kind"),
                      _enum_check("status", EXPORT_STATUSES, "ck_exports_status"))


class AuditEvent(Base):
    """Append-only record of user and financial-data changes. Never stores document text or secrets."""
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id", ondelete="SET NULL"))
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id",
                                                                                          ondelete="SET NULL"))
    firm_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id",
                                                                                         ondelete="SET NULL"))
    fund_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("funds.id",
                                                                                         ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (Index("ix_audit_events_household_created", "household_id", "created_at"),
                      Index("ix_audit_events_fund_created", "fund_id", "created_at"))
