"""Pydantic request/response models for /api/v1 (also the source of the OpenAPI document)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .engine.simulator import HORIZON_MONTHS, MAX_HORIZON_MONTHS

T = TypeVar("T")
Currency = str  # ISO 4217, validated below
Role = Literal["owner", "editor", "viewer"]


def _currency(v: str) -> str:
    v = v.strip().upper()
    if len(v) != 3 or not v.isalpha():
        raise ValueError("currency must be a 3-letter ISO 4217 code")
    return v


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ----------------------------------------------------------------------------- profile

class ProfileOut(ORM):
    id: uuid.UUID
    email: Optional[str]
    display_name: Optional[str]
    reporting_currency: str
    created_at: datetime


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=120)
    reporting_currency: Optional[str] = None
    _c = field_validator("reporting_currency")(lambda cls, v: _currency(v) if v else v)


class AccountDelete(BaseModel):
    confirm: Literal["DELETE MY ACCOUNT"]


# ----------------------------------------------------------------------------- households

class HouseholdIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    reporting_currency: str = "USD"
    start_calendar_month: int = Field(1, ge=1, le=12, description="Calendar month of projection month 1")
    notes: Optional[str] = Field(None, max_length=4000)
    _c = field_validator("reporting_currency")(lambda cls, v: _currency(v))


class HouseholdUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=160)
    reporting_currency: Optional[str] = None
    start_calendar_month: Optional[int] = Field(None, ge=1, le=12)
    notes: Optional[str] = Field(None, max_length=4000)
    _c = field_validator("reporting_currency")(lambda cls, v: _currency(v) if v else v)


class HouseholdOut(ORM):
    id: uuid.UUID
    name: str
    reporting_currency: str
    start_calendar_month: int
    notes: Optional[str]
    is_demo: bool
    role: Role
    created_at: datetime
    updated_at: datetime


class HouseholdSummary(BaseModel):
    household: HouseholdOut
    totals_by_kind: dict[str, dict[str, Decimal]]  # kind -> currency -> amount
    liabilities_by_kind: dict[str, dict[str, Decimal]]
    monthly_income: dict[str, Decimal]
    monthly_expenses: dict[str, Decimal]
    counts: dict[str, int]
    latest_run: Optional[RunSummary] = None


# ----------------------------------------------------------------------------- financial records

AssetKind = Literal["cash", "brokerage", "non_traded_reit", "interval_fund", "private_fund_commitment", "vested_rsu",
                    "other"]
LiabilityKind = Literal["sbl", "mortgage", "other_loan", "other"]
CashFlowKind = Literal["income", "core_expense", "discretionary_expense"]
EventKind = Literal["capital_call", "rsu_vest", "tax_payment", "other_outflow", "other_inflow",
                    "reit_redemption_request", "interval_redemption_request"]


class AssetIn(BaseModel):
    kind: AssetKind
    name: str = Field(min_length=1, max_length=160)
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    currency: str = "USD"
    as_of: Optional[date] = None
    pledged_to_sbl: bool = False
    unfunded_commitment: Optional[Decimal] = Field(None, ge=0, max_digits=18, decimal_places=2)
    liquidity_notes: Optional[str] = Field(None, max_length=2000)
    _c = field_validator("currency")(lambda cls, v: _currency(v))


class AssetUpdate(BaseModel):
    kind: Optional[AssetKind] = None
    name: Optional[str] = Field(None, min_length=1, max_length=160)
    amount: Optional[Decimal] = Field(None, ge=0, max_digits=18, decimal_places=2)
    currency: Optional[str] = None
    as_of: Optional[date] = None
    pledged_to_sbl: Optional[bool] = None
    unfunded_commitment: Optional[Decimal] = Field(None, ge=0, max_digits=18, decimal_places=2)
    liquidity_notes: Optional[str] = Field(None, max_length=2000)
    _c = field_validator("currency")(lambda cls, v: _currency(v) if v else v)


class AssetOut(ORM):
    id: uuid.UUID
    household_id: uuid.UUID
    kind: str
    name: str
    amount: Decimal
    currency: str
    as_of: Optional[date]
    pledged_to_sbl: bool
    unfunded_commitment: Optional[Decimal]
    liquidity_notes: Optional[str]
    updated_at: datetime


class LiabilityIn(BaseModel):
    kind: LiabilityKind
    name: str = Field(min_length=1, max_length=160)
    balance: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    currency: str = "USD"
    annual_rate: Optional[Decimal] = Field(None, ge=0, le=1, description="Decimal, e.g. 0.0725")
    monthly_payment: Optional[Decimal] = Field(None, ge=0, max_digits=18, decimal_places=2)
    notes: Optional[str] = Field(None, max_length=2000)
    _c = field_validator("currency")(lambda cls, v: _currency(v))


class LiabilityUpdate(BaseModel):
    kind: Optional[LiabilityKind] = None
    name: Optional[str] = Field(None, min_length=1, max_length=160)
    balance: Optional[Decimal] = Field(None, ge=0, max_digits=18, decimal_places=2)
    currency: Optional[str] = None
    annual_rate: Optional[Decimal] = Field(None, ge=0, le=1)
    monthly_payment: Optional[Decimal] = Field(None, ge=0, max_digits=18, decimal_places=2)
    notes: Optional[str] = Field(None, max_length=2000)
    _c = field_validator("currency")(lambda cls, v: _currency(v) if v else v)


class LiabilityOut(ORM):
    id: uuid.UUID
    household_id: uuid.UUID
    kind: str
    name: str
    balance: Decimal
    currency: str
    annual_rate: Optional[Decimal]
    monthly_payment: Optional[Decimal]
    notes: Optional[str]
    updated_at: datetime


class CashFlowIn(BaseModel):
    kind: CashFlowKind
    name: str = Field(min_length=1, max_length=160)
    monthly_amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    currency: str = "USD"
    _c = field_validator("currency")(lambda cls, v: _currency(v))


class CashFlowUpdate(BaseModel):
    kind: Optional[CashFlowKind] = None
    name: Optional[str] = Field(None, min_length=1, max_length=160)
    monthly_amount: Optional[Decimal] = Field(None, ge=0, max_digits=18, decimal_places=2)
    currency: Optional[str] = None
    _c = field_validator("currency")(lambda cls, v: _currency(v) if v else v)


class CashFlowOut(ORM):
    id: uuid.UUID
    household_id: uuid.UUID
    kind: str
    name: str
    monthly_amount: Decimal
    currency: str
    updated_at: datetime


class EventIn(BaseModel):
    kind: EventKind
    month: int = Field(ge=1, le=MAX_HORIZON_MONTHS, description="Projection month (1 = first month)")
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    currency: str = "USD"
    tax_due_month: Optional[int] = Field(None, ge=1, le=MAX_HORIZON_MONTHS)
    label: Optional[str] = Field(None, max_length=160)
    _c = field_validator("currency")(lambda cls, v: _currency(v))


class EventUpdate(BaseModel):
    kind: Optional[EventKind] = None
    month: Optional[int] = Field(None, ge=1, le=MAX_HORIZON_MONTHS)
    amount: Optional[Decimal] = Field(None, ge=0, max_digits=18, decimal_places=2)
    currency: Optional[str] = None
    tax_due_month: Optional[int] = Field(None, ge=1, le=MAX_HORIZON_MONTHS)
    label: Optional[str] = Field(None, max_length=160)
    _c = field_validator("currency")(lambda cls, v: _currency(v) if v else v)


class EventOut(ORM):
    id: uuid.UUID
    household_id: uuid.UUID
    kind: str
    month: int
    amount: Decimal
    currency: str
    tax_due_month: Optional[int]
    label: Optional[str]
    updated_at: datetime


# ----------------------------------------------------------------------------- documents

DocCategory = Literal["prospectus", "interval_fund", "private_fund_agreement", "sbl_agreement", "rsu_grant", "other"]


class DocumentInitiate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    category: DocCategory
    size_bytes: int = Field(gt=0)
    sha256: Optional[str] = Field(None, pattern="^[a-f0-9]{64}$")


class JobOut(ORM):
    id: uuid.UUID
    document_id: uuid.UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    attempt: int
    max_attempts: int
    progress: int
    stage: Optional[str]
    extraction_method: Optional[str]
    provider: Optional[str]
    model: Optional[str]
    error_code: Optional[str]
    error_message: Optional[str]
    stats: dict[str, Any]
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class DocumentOut(ORM):
    id: uuid.UUID
    household_id: uuid.UUID
    category: str
    original_filename: str
    content_type: str
    size_bytes: Optional[int]
    sha256: Optional[str]
    page_count: Optional[int]
    pages_without_text: Optional[int]
    ocr_pages: Optional[int]
    status: Literal["pending_upload", "uploaded", "queued", "processing", "extracted", "failed", "deleted"]
    is_demo_fixture: bool
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    latest_job: Optional[JobOut] = None
    constraint_count: int = 0


class UploadTarget(BaseModel):
    method: Literal["PUT"] = "PUT"
    url: str
    content_type: str = "application/pdf"
    max_bytes: int


class DocumentInitiateOut(BaseModel):
    document: DocumentOut
    upload: Optional[UploadTarget]
    duplicate: bool = False


class SignedUrlOut(BaseModel):
    url: str
    expires_in: int


class PageOut(BaseModel):
    document_id: uuid.UUID
    pdf_page: int
    printed_page: Optional[str]
    section: Optional[str]
    ocr: bool
    text: str


# ----------------------------------------------------------------------------- constraints

ReviewStatus = Literal["needs_review", "confirmed", "edited", "rejected"]


class ConstraintOut(ORM):
    id: uuid.UUID
    household_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str = ""
    revision: int
    constraint_type: str
    asset_key: str
    description: str
    value: Optional[Decimal]
    lower_bound: Optional[Decimal]
    upper_bound: Optional[Decimal]
    original_value: Optional[Decimal]
    unit: Optional[str]
    timing: Optional[str]
    conditions: Optional[str]
    pdf_page: int
    printed_page: Optional[str]
    document_section: Optional[str]
    evidence_quote: str
    quote_verified: bool
    corroborating_pages: list[int]
    interpretation: str
    confidence: str
    source_type: str
    review_status: ReviewStatus
    extraction_method: str
    provider: Optional[str]
    model: Optional[str]
    is_qualitative: bool = False
    reviewed_at: Optional[datetime]
    updated_at: datetime


class ConstraintUpdate(BaseModel):
    expected_revision: int = Field(ge=1, description="Optimistic concurrency: the revision you edited")
    value: Optional[Decimal] = None
    lower_bound: Optional[Decimal] = None
    upper_bound: Optional[Decimal] = None
    unit: Optional[str] = Field(None, max_length=80)
    timing: Optional[str] = Field(None, max_length=160)
    conditions: Optional[str] = Field(None, max_length=4000)
    interpretation: Optional[str] = Field(None, max_length=4000)
    review_status: Optional[ReviewStatus] = None
    note: Optional[str] = Field(None, max_length=500)


class ConstraintDecision(BaseModel):
    expected_revision: int = Field(ge=1)
    note: Optional[str] = Field(None, max_length=500)


class RevisionOut(ORM):
    revision: int
    changed_by: Optional[uuid.UUID]
    change: dict[str, Any]
    note: Optional[str]
    created_at: datetime


class ConstraintDetail(ConstraintOut):
    revisions: list[RevisionOut] = []


# ----------------------------------------------------------------------------- scenarios

class ScenarioAssumptions(BaseModel):
    """Every value here is a modelling assumption, not a contract term. Household balances and
    scheduled obligations come from the household's records at run time."""
    model_config = ConfigDict(extra="forbid")
    horizon_months: int = Field(HORIZON_MONTHS, ge=12, le=MAX_HORIZON_MONTHS)
    fx_rates: dict[str, float] = Field(default_factory=dict,
                                       description="Units of reporting currency per 1 unit of each other currency")
    equity_drawdown: float = Field(0.25, ge=0, le=0.95)
    months_to_trough: int = Field(3, ge=1, le=12)
    trough_hold_months: int = Field(9, ge=0, le=18)
    recovery_share: float = Field(0.5, ge=0, le=1)
    beta_brokerage: float = Field(1.0, ge=0, le=3)
    beta_rsu: float = Field(1.3, ge=0, le=3)
    beta_reit_nav: float = Field(0.3, ge=0, le=3)
    beta_interval_nav: float = Field(0.4, ge=0, le=3)
    rsu_effective_tax_rate: float = Field(0.47, ge=0, le=0.75)
    rsu_window_months: list[int] = Field(default_factory=lambda: [2, 5, 8, 11, 14, 17, 20, 23])
    rsu_window_cash_floor_months: float = Field(3.0, ge=0, le=24)
    reit_shares_held_over_one_year: bool = True
    reit_base_demand_pct: float = Field(1.5, ge=0, le=100)
    reit_demand_sensitivity: float = Field(50.0, ge=0, le=500)
    reit_board_fill_factor: float = Field(1.0, ge=0, le=1)
    interval_base_demand_pct: float = Field(3.0, ge=0, le=100)
    interval_demand_sensitivity: float = Field(40.0, ge=0, le=500)
    naive_liquid_fraction: dict[str, float] = Field(default_factory=lambda: {
        "brokerage": 0.90, "reit": 0.70, "interval_fund": 0.70, "rsu_vested": 0.85})
    sale_tax_drag: float = Field(0.08, ge=0, le=0.6)
    lever_reserve_prefund: float = Field(0.0, ge=0)
    lever_sbl_paydown: float = Field(0.0, ge=0)
    lever_rsu_extra_withholding: float = Field(0.0, ge=0, le=0.6)
    lever_rsu_window_presale: float = Field(0.0, ge=0)
    lever_discretionary_cut: float = Field(0.0, ge=0)
    lever_reit_prestress_request: float = Field(0.0, ge=0)
    assumption_sources: dict[str, str] = Field(
        default_factory=dict, description="Optional citation per assumption key; unsourced if absent")

    @field_validator("fx_rates")
    @classmethod
    def _fx(cls, v: dict[str, float]) -> dict[str, float]:
        out = {}
        for k, rate in v.items():
            if rate <= 0:
                raise ValueError(f"fx rate for {k} must be positive")
            out[_currency(k)] = rate
        return out


class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: Optional[str] = Field(None, max_length=4000)
    assumptions: ScenarioAssumptions = Field(default_factory=ScenarioAssumptions)


class ScenarioUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=160)
    description: Optional[str] = Field(None, max_length=4000)
    assumptions: Optional[ScenarioAssumptions] = None


class ScenarioOut(ORM):
    id: uuid.UUID
    household_id: uuid.UUID
    name: str
    description: Optional[str]
    assumptions: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AssumptionField(BaseModel):
    key: str
    label: str
    group: str
    kind: Literal["percent", "number", "money", "months", "boolean", "list"]
    help: str


class ScenarioDefaults(BaseModel):
    assumptions: ScenarioAssumptions
    fields: list[AssumptionField]


# ----------------------------------------------------------------------------- runs

class ModelSummary(BaseModel):
    model: Literal["naive", "contract_aware"]
    first_shortfall_month: Optional[int]
    shortfall_amount: float
    peak_shortfall: float
    min_cash: float


class TermProvenance(BaseModel):
    term: str
    value: Any
    provenance: str
    source_backed: bool


class RunSummary(ORM):
    id: uuid.UUID
    household_id: uuid.UUID
    scenario_id: uuid.UUID
    scenario_name: str = ""
    engine_version: str
    reporting_currency: str
    horizon_months: int
    naive_summary: dict[str, Any]
    aware_summary: dict[str, Any]
    liquidity: dict[str, Any]
    warnings: list[str]
    created_at: datetime


class MonthOut(ORM):
    model: str
    month: int
    label: str
    beginning_cash: Decimal
    income: Decimal
    expenses: Decimal
    taxes: Decimal
    debt_service: Decimal
    collateral_call: Decimal
    capital_call: Decimal
    redemption_requested: Decimal
    redemption_proceeds: Decimal
    other_proceeds: Decimal
    ending_cash: Decimal
    shortfall: Decimal
    reit_fill_rate: Optional[Decimal]
    binding_constraints: list[str]


class RunDetail(RunSummary):
    inputs_snapshot: dict[str, Any]
    household_snapshot: dict[str, Any]
    terms: list[TermProvenance]
    constraint_versions: list[dict[str, Any]]
    months: list[MonthOut]


class StressRequest(BaseModel):
    max_drawdown: float = Field(0.60, gt=0, le=0.95)
    step: float = Field(0.01, ge=0.0025, le=0.1)
    tolerance: float = Field(0.0005, ge=0.0001, le=0.01)


class StressOut(ORM):
    id: uuid.UUID
    scenario_id: uuid.UUID
    engine_version: str
    search: dict[str, Any]
    found: bool
    boundary_drawdown: Optional[Decimal]
    last_safe_drawdown: Optional[Decimal]
    first_shortfall_month: Optional[int]
    shortfall_amount: Decimal
    grid_monotone: bool
    method: str
    binding_constraints: list[str]
    attribution: list[dict[str, Any]]
    key_events: list[dict[str, Any]]
    created_at: datetime


class CostAssumptionsIn(BaseModel):
    sale_tax_drag: float = Field(0.08, ge=0, le=0.6)
    cash_drag: float = Field(0.04, ge=0, le=0.5)
    reit_forgone_return: float = Field(0.03, ge=0, le=0.5)
    withholding_time_value: float = Field(0.01, ge=0, le=0.5)
    discretionary_weight: float = Field(0.25, ge=0, le=5)


class PreventionRequest(BaseModel):
    costs: CostAssumptionsIn = Field(default_factory=CostAssumptionsIn)
    cash_buffer: float = Field(0.0, ge=0)


class RecommendationOut(ORM):
    id: uuid.UUID
    rank: int
    kind: Literal["single", "combined"]
    lever: str
    name: str
    amount: Decimal
    unit: str
    cost: Decimal
    cost_basis: str
    liquidity_benefit: Optional[Decimal]
    min_cash_after: Optional[Decimal]
    first_shortfall_after: Optional[int]
    feasible_alone: Optional[bool]
    constraints_note: str
    status: Literal["proposed", "approved", "rejected"]
    decided_at: Optional[datetime]


class PreventionOut(ORM):
    id: uuid.UUID
    scenario_id: uuid.UUID
    engine_version: str
    cost_assumptions: dict[str, Any]
    baseline_first_shortfall: Optional[int]
    baseline_peak_shortfall: Decimal
    forced_liquidation_cost: Decimal
    forced_liquidation_note: str
    combined_cost: Decimal
    combined_verified: bool
    combined_source: str
    combined_min_cash: Decimal
    combined_first_shortfall: Optional[int]
    lp_status: str
    method: str
    created_at: datetime
    recommendations: list[RecommendationOut]


class RecommendationDecision(BaseModel):
    decision: Literal["approved", "rejected"]


class ApplyOut(BaseModel):
    scenario: ScenarioOut


# ----------------------------------------------------------------------------- exports & audit

ExportKind = Literal["constraints_csv", "constraints_json", "simulation_csv", "results_json", "report_pdf"]


class ExportIn(BaseModel):
    kind: ExportKind
    run_id: Optional[uuid.UUID] = None


class ExportOut(ORM):
    id: uuid.UUID
    household_id: uuid.UUID
    run_id: Optional[uuid.UUID]
    kind: str
    status: Literal["queued", "running", "ready", "failed"]
    filename: Optional[str]
    size_bytes: Optional[int]
    error_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]


class AuditOut(ORM):
    id: uuid.UUID
    actor_id: Optional[uuid.UUID]
    action: str
    entity_type: str
    entity_id: Optional[uuid.UUID]
    details: dict[str, Any]
    created_at: datetime


class HealthOut(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    version: str
    checks: dict[str, str] = {}


HouseholdSummary.model_rebuild()
