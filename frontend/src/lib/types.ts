/**
 * TypeScript mirror of the SlipSlopes API models (backend/app/api_schemas.py).
 *
 * Conventions:
 *  - UUIDs and datetimes arrive as strings.
 *  - Pydantic `Decimal` fields are serialized as JSON strings (e.g. "250000.00"); they are typed
 *    as `Decimal` (string) here and must be parsed with `parseDecimal` before arithmetic/display.
 *  - Request models accept decimals as strings or numbers; we send strings to avoid float drift.
 */

export type UUID = string;
export type ISODateTime = string;
export type ISODate = string;
/** Decimal serialized as a JSON string. */
export type Decimal = string;
/** Decimal accepted in requests (string preferred). */
export type DecimalInput = string | number;

export type Role = "owner" | "editor" | "viewer";

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id: string;
    details?: unknown;
  };
}

// ----------------------------------------------------------------------------- profile

export interface ProfileOut {
  id: UUID;
  email: string | null;
  display_name: string | null;
  reporting_currency: string;
  created_at: ISODateTime;
}

export interface ProfileUpdate {
  display_name?: string | null;
  reporting_currency?: string | null;
}

export interface AccountDelete {
  confirm: "DELETE MY ACCOUNT";
}

// ----------------------------------------------------------------------------- households

export interface HouseholdIn {
  name: string;
  reporting_currency?: string;
  start_calendar_month?: number;
  notes?: string | null;
}

export interface HouseholdUpdate {
  name?: string | null;
  reporting_currency?: string | null;
  start_calendar_month?: number | null;
  notes?: string | null;
}

export interface HouseholdOut {
  id: UUID;
  name: string;
  reporting_currency: string;
  start_calendar_month: number;
  notes: string | null;
  is_demo: boolean;
  role: Role;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface HouseholdSummary {
  household: HouseholdOut;
  /** kind -> currency -> amount */
  totals_by_kind: Record<string, Record<string, Decimal>>;
  liabilities_by_kind: Record<string, Record<string, Decimal>>;
  /** currency -> amount */
  monthly_income: Record<string, Decimal>;
  monthly_expenses: Record<string, Decimal>;
  counts: Record<string, number>;
  latest_run?: RunSummary | null;
}

// ----------------------------------------------------------------------------- financial records

export type AssetKind =
  | "cash"
  | "brokerage"
  | "non_traded_reit"
  | "interval_fund"
  | "private_fund_commitment"
  | "vested_rsu"
  | "other";
export type LiabilityKind = "sbl" | "mortgage" | "other_loan" | "other";
export type CashFlowKind = "income" | "core_expense" | "discretionary_expense";
export type EventKind =
  | "capital_call"
  | "rsu_vest"
  | "tax_payment"
  | "other_outflow"
  | "other_inflow"
  | "reit_redemption_request"
  | "interval_redemption_request";

export const ASSET_KINDS: AssetKind[] = [
  "cash",
  "brokerage",
  "non_traded_reit",
  "interval_fund",
  "private_fund_commitment",
  "vested_rsu",
  "other",
];
export const LIABILITY_KINDS: LiabilityKind[] = ["sbl", "mortgage", "other_loan", "other"];
export const CASH_FLOW_KINDS: CashFlowKind[] = ["income", "core_expense", "discretionary_expense"];
export const EVENT_KINDS: EventKind[] = [
  "capital_call",
  "rsu_vest",
  "tax_payment",
  "other_outflow",
  "other_inflow",
  "reit_redemption_request",
  "interval_redemption_request",
];

export interface AssetIn {
  kind: AssetKind;
  name: string;
  amount: DecimalInput;
  currency?: string;
  as_of?: ISODate | null;
  pledged_to_sbl?: boolean;
  unfunded_commitment?: DecimalInput | null;
  liquidity_notes?: string | null;
}
export type AssetUpdate = Partial<AssetIn>;

export interface AssetOut {
  id: UUID;
  household_id: UUID;
  kind: string;
  name: string;
  amount: Decimal;
  currency: string;
  as_of: ISODate | null;
  pledged_to_sbl: boolean;
  unfunded_commitment: Decimal | null;
  liquidity_notes: string | null;
  updated_at: ISODateTime;
}

export interface LiabilityIn {
  kind: LiabilityKind;
  name: string;
  balance: DecimalInput;
  currency?: string;
  /** Decimal fraction, e.g. 0.0725 */
  annual_rate?: DecimalInput | null;
  monthly_payment?: DecimalInput | null;
  notes?: string | null;
}
export type LiabilityUpdate = Partial<LiabilityIn>;

export interface LiabilityOut {
  id: UUID;
  household_id: UUID;
  kind: string;
  name: string;
  balance: Decimal;
  currency: string;
  annual_rate: Decimal | null;
  monthly_payment: Decimal | null;
  notes: string | null;
  updated_at: ISODateTime;
}

export interface CashFlowIn {
  kind: CashFlowKind;
  name: string;
  monthly_amount: DecimalInput;
  currency?: string;
}
export type CashFlowUpdate = Partial<CashFlowIn>;

export interface CashFlowOut {
  id: UUID;
  household_id: UUID;
  kind: string;
  name: string;
  monthly_amount: Decimal;
  currency: string;
  updated_at: ISODateTime;
}

export interface EventIn {
  kind: EventKind;
  /** Projection month (1 = first month) */
  month: number;
  amount: DecimalInput;
  currency?: string;
  tax_due_month?: number | null;
  label?: string | null;
}
export type EventUpdate = Partial<EventIn>;

export interface EventOut {
  id: UUID;
  household_id: UUID;
  kind: string;
  month: number;
  amount: Decimal;
  currency: string;
  tax_due_month: number | null;
  label: string | null;
  updated_at: ISODateTime;
}

// ----------------------------------------------------------------------------- documents

export type DocCategory =
  | "prospectus"
  | "interval_fund"
  | "private_fund_agreement"
  | "sbl_agreement"
  | "rsu_grant"
  | "other";
export const DOC_CATEGORIES: DocCategory[] = [
  "prospectus",
  "interval_fund",
  "private_fund_agreement",
  "sbl_agreement",
  "rsu_grant",
  "other",
];

export interface DocumentInitiate {
  filename: string;
  category: DocCategory;
  size_bytes: number;
  sha256?: string | null;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface JobOut {
  id: UUID;
  document_id: UUID;
  status: JobStatus;
  attempt: number;
  max_attempts: number;
  progress: number;
  stage: string | null;
  extraction_method: string | null;
  provider: string | null;
  model: string | null;
  error_code: string | null;
  error_message: string | null;
  stats: Record<string, unknown>;
  created_at: ISODateTime;
  started_at: ISODateTime | null;
  finished_at: ISODateTime | null;
}

export type DocumentStatus =
  | "pending_upload"
  | "uploaded"
  | "queued"
  | "processing"
  | "extracted"
  | "failed"
  | "deleted";

export interface DocumentOut {
  id: UUID;
  household_id: UUID;
  category: string;
  original_filename: string;
  content_type: string;
  size_bytes: number | null;
  sha256: string | null;
  page_count: number | null;
  pages_without_text: number | null;
  ocr_pages: number | null;
  status: DocumentStatus;
  is_demo_fixture: boolean;
  error_code: string | null;
  error_message: string | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  latest_job?: JobOut | null;
  constraint_count?: number;
}

export interface UploadTarget {
  method: "PUT";
  /** Relative to the API base (e.g. "/api/v1/documents/{id}/content") or absolute. */
  url: string;
  content_type: string;
  max_bytes: number;
}

export interface DocumentInitiateOut {
  document: DocumentOut;
  upload: UploadTarget | null;
  duplicate: boolean;
}

export interface SignedUrlOut {
  url: string;
  expires_in: number;
}

export interface PageOut {
  document_id: UUID;
  pdf_page: number;
  printed_page: string | null;
  section: string | null;
  ocr: boolean;
  text: string;
}

// ----------------------------------------------------------------------------- constraints

export type ReviewStatus = "needs_review" | "confirmed" | "edited" | "rejected";
export const REVIEW_STATUSES: ReviewStatus[] = ["needs_review", "confirmed", "edited", "rejected"];

export interface ConstraintOut {
  id: UUID;
  household_id: UUID;
  document_id: UUID;
  document_name: string;
  revision: number;
  constraint_type: string;
  asset_key: string;
  description: string;
  value: Decimal | null;
  lower_bound: Decimal | null;
  upper_bound: Decimal | null;
  original_value: Decimal | null;
  unit: string | null;
  timing: string | null;
  conditions: string | null;
  pdf_page: number;
  printed_page: string | null;
  document_section: string | null;
  evidence_quote: string;
  quote_verified: boolean;
  corroborating_pages: number[];
  interpretation: string;
  confidence: string;
  /** source_backed | synthetic_document | user_confirmed | scenario_assumption */
  source_type: string;
  review_status: ReviewStatus;
  extraction_method: string;
  provider: string | null;
  model: string | null;
  is_qualitative: boolean;
  reviewed_at: ISODateTime | null;
  updated_at: ISODateTime;
}

export interface ConstraintUpdate {
  expected_revision: number;
  value?: DecimalInput | null;
  lower_bound?: DecimalInput | null;
  upper_bound?: DecimalInput | null;
  unit?: string | null;
  timing?: string | null;
  conditions?: string | null;
  interpretation?: string | null;
  review_status?: ReviewStatus | null;
  note?: string | null;
}

export interface ConstraintDecision {
  expected_revision: number;
  note?: string | null;
}

export interface RevisionOut {
  revision: number;
  changed_by: UUID | null;
  change: Record<string, unknown>;
  note: string | null;
  created_at: ISODateTime;
}

export interface ConstraintDetail extends ConstraintOut {
  revisions: RevisionOut[];
}

// ----------------------------------------------------------------------------- scenarios

/** Every value is a modelling assumption, not a contract term. */
export interface ScenarioAssumptions {
  horizon_months: number;
  fx_rates: Record<string, number>;
  equity_drawdown: number;
  months_to_trough: number;
  trough_hold_months: number;
  recovery_share: number;
  beta_brokerage: number;
  beta_rsu: number;
  beta_reit_nav: number;
  beta_interval_nav: number;
  rsu_effective_tax_rate: number;
  rsu_window_months: number[];
  rsu_window_cash_floor_months: number;
  reit_shares_held_over_one_year: boolean;
  reit_base_demand_pct: number;
  reit_demand_sensitivity: number;
  reit_board_fill_factor: number;
  interval_base_demand_pct: number;
  interval_demand_sensitivity: number;
  naive_liquid_fraction: Record<string, number>;
  sale_tax_drag: number;
  lever_reserve_prefund: number;
  lever_sbl_paydown: number;
  lever_rsu_extra_withholding: number;
  lever_rsu_window_presale: number;
  lever_discretionary_cut: number;
  lever_reit_prestress_request: number;
  assumption_sources: Record<string, string>;
}

export interface ScenarioIn {
  name: string;
  description?: string | null;
  assumptions?: Partial<ScenarioAssumptions>;
}

export interface ScenarioUpdate {
  name?: string | null;
  description?: string | null;
  assumptions?: Partial<ScenarioAssumptions> | null;
}

export interface ScenarioOut {
  id: UUID;
  household_id: UUID;
  name: string;
  description: string | null;
  assumptions: Record<string, unknown>;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export type AssumptionKind = "percent" | "number" | "money" | "months" | "boolean" | "list";

export interface AssumptionField {
  key: string;
  label: string;
  group: string;
  kind: AssumptionKind;
  help: string;
}

export interface ScenarioDefaults {
  assumptions: ScenarioAssumptions;
  fields: AssumptionField[];
}

// ----------------------------------------------------------------------------- runs

export type ModelName = "naive" | "contract_aware";

export interface ModelSummary {
  model: ModelName;
  first_shortfall_month: number | null;
  shortfall_amount: number;
  peak_shortfall: number;
  min_cash: number;
}

export interface TermProvenance {
  term: string;
  value: unknown;
  provenance: string;
  source_backed: boolean;
}

export interface RunSummary {
  id: UUID;
  household_id: UUID;
  scenario_id: UUID;
  scenario_name: string;
  engine_version: string;
  reporting_currency: string;
  horizon_months: number;
  /** Shape of ModelSummary (typed loosely by the API). */
  naive_summary: Partial<ModelSummary> & Record<string, unknown>;
  aware_summary: Partial<ModelSummary> & Record<string, unknown>;
  /** Stress-usable liquidity breakdown (e.g. total, cash, naive_total, window_months, ...). */
  liquidity: Record<string, unknown>;
  warnings: string[];
  created_at: ISODateTime;
}

export interface MonthOut {
  model: ModelName | string;
  month: number;
  label: string;
  beginning_cash: Decimal;
  income: Decimal;
  expenses: Decimal;
  taxes: Decimal;
  debt_service: Decimal;
  collateral_call: Decimal;
  capital_call: Decimal;
  redemption_requested: Decimal;
  redemption_proceeds: Decimal;
  other_proceeds: Decimal;
  ending_cash: Decimal;
  shortfall: Decimal;
  reit_fill_rate: Decimal | null;
  binding_constraints: string[];
}

export interface RunDetail extends RunSummary {
  inputs_snapshot: Record<string, unknown>;
  household_snapshot: Record<string, unknown>;
  terms: TermProvenance[];
  constraint_versions: Record<string, unknown>[];
  months: MonthOut[];
}

export interface StressRequest {
  max_drawdown?: number;
  step?: number;
  tolerance?: number;
}

export interface StressGridPoint {
  equity_drawdown: number;
  min_cash: number;
  fails: boolean;
  first_shortfall_month?: number | null;
}

export interface StressOut {
  id: UUID;
  scenario_id: UUID;
  engine_version: string;
  /** Search parameters and grid: { grid?: StressGridPoint[], max_drawdown?, step?, tolerance? } */
  search: Record<string, unknown>;
  found: boolean;
  boundary_drawdown: Decimal | null;
  last_safe_drawdown: Decimal | null;
  first_shortfall_month: number | null;
  shortfall_amount: Decimal;
  grid_monotone: boolean;
  method: string;
  binding_constraints: string[];
  attribution: Record<string, unknown>[];
  key_events: Record<string, unknown>[];
  created_at: ISODateTime;
}

export interface CostAssumptionsIn {
  sale_tax_drag?: number;
  cash_drag?: number;
  reit_forgone_return?: number;
  withholding_time_value?: number;
  discretionary_weight?: number;
}

export interface PreventionRequest {
  costs?: CostAssumptionsIn;
  cash_buffer?: number;
}

export type RecommendationStatus = "proposed" | "approved" | "rejected";

export interface RecommendationOut {
  id: UUID;
  rank: number;
  kind: "single" | "combined";
  lever: string;
  name: string;
  amount: Decimal;
  unit: string;
  cost: Decimal;
  cost_basis: string;
  liquidity_benefit: Decimal | null;
  min_cash_after: Decimal | null;
  first_shortfall_after: number | null;
  feasible_alone: boolean | null;
  constraints_note: string;
  status: RecommendationStatus;
  decided_at: ISODateTime | null;
}

export interface PreventionOut {
  id: UUID;
  scenario_id: UUID;
  engine_version: string;
  cost_assumptions: Record<string, unknown>;
  baseline_first_shortfall: number | null;
  baseline_peak_shortfall: Decimal;
  forced_liquidation_cost: Decimal;
  forced_liquidation_note: string;
  combined_cost: Decimal;
  combined_verified: boolean;
  combined_source: string;
  combined_min_cash: Decimal;
  combined_first_shortfall: number | null;
  lp_status: string;
  method: string;
  created_at: ISODateTime;
  recommendations: RecommendationOut[];
}

export interface RecommendationDecision {
  decision: "approved" | "rejected";
}

export interface ApplyOut {
  scenario: ScenarioOut;
}

// ----------------------------------------------------------------------------- exports & audit

export type ExportKind =
  | "constraints_csv"
  | "constraints_json"
  | "simulation_csv"
  | "results_json"
  | "report_pdf";
export const EXPORT_KINDS: ExportKind[] = [
  "constraints_csv",
  "constraints_json",
  "simulation_csv",
  "results_json",
  "report_pdf",
];
export const EXPORT_KINDS_REQUIRING_RUN: ExportKind[] = ["simulation_csv", "results_json", "report_pdf"];

export interface ExportIn {
  kind: ExportKind;
  run_id?: UUID | null;
}

export type ExportStatus = "queued" | "running" | "ready" | "failed";

export interface ExportOut {
  id: UUID;
  household_id: UUID;
  run_id: UUID | null;
  kind: string;
  status: ExportStatus;
  filename: string | null;
  size_bytes: number | null;
  error_message: string | null;
  created_at: ISODateTime;
  completed_at: ISODateTime | null;
}

export interface AuditOut {
  id: UUID;
  actor_id: UUID | null;
  action: string;
  entity_type: string;
  entity_id: UUID | null;
  details: Record<string, unknown>;
  created_at: ISODateTime;
}

export interface HealthOut {
  status: "ok" | "degraded" | "unavailable";
  version: string;
  checks: Record<string, string>;
}
