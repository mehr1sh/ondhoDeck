/**
 * TypeScript mirror of the OndhoDeck API models (backend/app/api_schemas.py).
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
  firm_id?: UUID;
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
  /** Library fund this holding is an instance of; null unlinks. */
  fund_id?: UUID | null;
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
  fund_id?: UUID | null;
  fund_name?: string | null;
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
  | "prospectus_supplement"
  | "statement_of_additional_information"
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
  /** Whose credentials ran the extraction: "user_byok" | "server" | "injected" | "none"; null for old jobs. */
  credential_source?: string | null;
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
  /** Null for Fund Library documents. */
  household_id: UUID | null;
  fund_id?: UUID | null;
  effective_date?: ISODate | null;
  supersedes_document_id?: UUID | null;
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

/** How a clause's number should be read. A maximum is a cap the counterparty may fill less of. */
export type ValueKind = "maximum" | "minimum" | "exact" | "range" | "qualitative";
export const VALUE_KINDS: ValueKind[] = ["maximum", "minimum", "exact", "range", "qualitative"];

export interface ValidationIssue {
  code: string;
  message: string;
  /** "error" | "warning" (backend/app/engine/contract_validation.py) */
  severity?: string;
}

export interface ConstraintOut {
  id: UUID;
  /** Null for Fund Library terms. */
  household_id: UUID | null;
  fund_id?: UUID | null;
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
  value_kind?: ValueKind | string | null;
  exceptions?: string[];
  discretion?: string | null;
  effective_period?: string | null;
  /** Discretion or conditions in the clause were not fully captured. */
  ambiguous?: boolean;
  validation_issues?: ValidationIssue[];
  confidence: string;
  /** source_backed | synthetic_document | user_confirmed | scenario_assumption */
  source_type: string;
  review_status: ReviewStatus;
  extraction_method: string;
  provider: string | null;
  model: string | null;
  is_qualitative: boolean;
  reviewed_by?: UUID | null;
  reviewed_at: ISODateTime | null;
  /** First date the term applies (inclusive); null = no start limit. */
  effective_from?: ISODate | null;
  /** Last date the term applies (inclusive); null = open-ended. */
  effective_to?: ISODate | null;
  superseded_by_id?: UUID | null;
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
  value_kind?: ValueKind | null;
  exceptions?: string[] | null;
  discretion?: string | null;
  effective_period?: string | null;
  effective_from?: ISODate | null;
  effective_to?: ISODate | null;
  review_status?: ReviewStatus | null;
  note?: string | null;
}

export interface ConstraintSupersede {
  expected_revision: number;
  superseded_id: UUID;
  superseded_expected_revision: number;
  effective_date?: ISODate | null;
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
  /** Date of projection month 1; selects the library terms in force. Null = the run date. */
  as_of_date?: ISODate | null;
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

/** GET /scenario-presets item. `assumptions` is a complete assumption set (defaults + overrides). */
export interface ScenarioPreset {
  id: string;
  name: string;
  description: string;
  /** e.g. "Scenario assumption - not a contract term or forecast" */
  label: string;
  overrides?: Partial<ScenarioAssumptions>;
  assumptions: Partial<ScenarioAssumptions> & Record<string, unknown>;
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
  /** contract_clause | derived_from_clause | default_assumption | household_record | other (absent on old runs). */
  basis?: string | null;
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

export interface ExplanationEvidence {
  id: UUID;
  revision: number;
  type: string;
  asset_key: string;
  document: string;
  pdf_page: number;
  quote: string;
  value: unknown;
}

export interface ExplanationTerm {
  term: string;
  value: unknown;
  provenance: string;
}

export interface ContributingRule {
  rule: string;
  relaxation: string;
  peak_shortfall_reduction: number;
  removes_shortfall: boolean;
  first_shortfall_month_without_rule: number | null;
  terms: ExplanationTerm[];
  evidence: ExplanationEvidence[];
  basis: string;
}

export interface AssumptionVariant {
  direction: "lower" | "higher" | string;
  value: number;
  first_shortfall_month: number | null;
  peak_shortfall: number;
  material: boolean;
}

export interface MaterialAssumption {
  assumption: string;
  label: string;
  base_value: number;
  material: boolean;
  variants: AssumptionVariant[];
}

/** Deterministic, counterfactual explanation of a run (no LLM). */
export interface RunExplanation {
  method: string;
  first_shortfall_month: number | null;
  shortfall_amount: number;
  peak_shortfall: number;
  binding_in_first_shortfall_month: string[];
  contributing_rules: ContributingRule[];
  material_assumptions: MaterialAssumption[];
  /** Approved terms the engine does not model numerically (shown as risks, never as causes). */
  not_modelled?: Array<ExplanationEvidence & { reason: string }>;
  /** Approved terms left out because their evidence does not support them. */
  excluded_unsupported?: Array<{ constraint_id: string; type: string; document: string; pdf_page: number; reasons: string[] }>;
}

export interface RunDetail extends RunSummary {
  /** Null or {} for runs created before explanations existed. */
  explanation?: RunExplanation | Record<string, never> | null;
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
  | "report_pdf"
  | "blind_spot_pdf";
export const EXPORT_KINDS: ExportKind[] = [
  "constraints_csv",
  "constraints_json",
  "simulation_csv",
  "results_json",
  "report_pdf",
  "blind_spot_pdf",
];
export const EXPORT_KINDS_REQUIRING_RUN: ExportKind[] = ["simulation_csv", "results_json", "report_pdf"];
export const EXPORT_KINDS_REQUIRING_BLIND_SPOT: ExportKind[] = ["blind_spot_pdf"];

export interface ExportIn {
  kind: ExportKind;
  run_id?: UUID | null;
  blind_spot_report_id?: UUID | null;
}

export type ExportStatus = "queued" | "running" | "ready" | "failed";

export interface ExportOut {
  id: UUID;
  household_id: UUID;
  run_id: UUID | null;
  blind_spot_report_id?: UUID | null;
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

// ----------------------------------------------------------------------------- AI providers (BYOK)

export type AIProvider = "anthropic" | "openai";
export type CredentialStatus = "untested" | "valid" | "invalid" | "quota_exceeded" | "error";

export interface ProviderInfo {
  provider: AIProvider;
  label: string;
  default_model: string | null;
}

/** A stored key is never returned; only the masked `key_hint` (e.g. "…abcd"). */
export interface CredentialOut {
  provider: AIProvider;
  key_hint: string;
  model: string | null;
  /** Anthropic workspace ID for keys not scoped to a workspace (an identifier, not a secret). */
  workspace_id?: string | null;
  is_active: boolean;
  status: CredentialStatus | string;
  last_tested_at: ISODateTime | null;
  last_error_code: string | null;
  last_error: string | null;
  updated_at: ISODateTime;
}

export interface ServerFallback {
  configured: boolean;
  provider: string | null;
  model: string | null;
}

export interface AIProvidersOut {
  storage_available: boolean;
  storage_message: string | null;
  providers: ProviderInfo[];
  credentials: CredentialOut[];
  active_provider: AIProvider | null;
  server_fallback: ServerFallback;
  extraction_order: string;
}

export interface CredentialIn {
  api_key: string;
  model?: string | null;
  workspace_id?: string | null;
  activate: boolean;
}

export interface CredentialUpdate {
  model?: string | null;
  workspace_id?: string | null;
  is_active?: boolean | null;
}

export interface CredentialTestOut {
  ok: boolean;
  code: string;
  message: string;
  credential: CredentialOut;
}

export interface ProviderModelsOut {
  provider: AIProvider;
  models: string[];
}

export interface HealthOut {
  status: "ok" | "degraded" | "unavailable";
  version: string;
  checks: Record<string, string>;
}

// ----------------------------------------------------------------------------- firms

export type FirmRole = "admin" | "reviewer" | "advisor";
export const FIRM_ROLES: FirmRole[] = ["admin", "reviewer", "advisor"];

export interface FirmOut {
  id: UUID;
  name: string;
  role: FirmRole;
  created_at: ISODateTime;
}

export interface FirmMemberOut {
  user_id: UUID;
  email: string | null;
  display_name: string | null;
  role: FirmRole;
  created_at: ISODateTime;
}

export interface FirmMemberIn {
  email: string;
  role: FirmRole;
}

// ----------------------------------------------------------------------------- fund library

export type FundType = "non_traded_reit" | "interval_fund" | "private_fund" | "other";
export const FUND_TYPES: FundType[] = ["non_traded_reit", "interval_fund", "private_fund", "other"];
export type FundMetadataStatus = "needs_review" | "verified";
export type FundStatus = "active" | "archived";

/** Household asset kind -> library fund type it may link to. */
export const ASSET_KIND_FUND_TYPE: Partial<Record<AssetKind, FundType>> = {
  non_traded_reit: "non_traded_reit",
  interval_fund: "interval_fund",
  private_fund_commitment: "private_fund",
  other: "other",
};

export interface FundIn {
  firm_id?: UUID | null;
  name: string;
  fund_type: FundType;
  issuer?: string | null;
  ticker?: string | null;
  share_class?: string | null;
  sec_cik?: string | null;
  aliases?: string[];
  description?: string | null;
}

export interface FundUpdate {
  name?: string | null;
  fund_type?: FundType | null;
  issuer?: string | null;
  ticker?: string | null;
  share_class?: string | null;
  sec_cik?: string | null;
  aliases?: string[] | null;
  description?: string | null;
  metadata_status?: FundMetadataStatus | null;
  status?: FundStatus | null;
}

export interface FundOut {
  id: UUID;
  firm_id: UUID;
  name: string;
  fund_type: FundType;
  issuer: string | null;
  ticker: string | null;
  share_class: string | null;
  sec_cik: string | null;
  aliases: string[];
  description: string | null;
  metadata_status: FundMetadataStatus;
  status: FundStatus;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  document_count?: number;
  approved_term_count?: number;
  pending_term_count?: number;
}

export interface FundHoldingOut {
  asset_id: UUID;
  asset_name: string;
  household_id: UUID;
  household_name: string;
}

export interface FundDetail extends FundOut {
  your_role: FirmRole;
  documents: DocumentOut[];
  linked_holdings: FundHoldingOut[];
  linked_holdings_total: number;
}

export type FundDocCategory =
  | "prospectus"
  | "prospectus_supplement"
  | "statement_of_additional_information"
  | "interval_fund"
  | "other";
export const FUND_DOC_CATEGORIES: FundDocCategory[] = [
  "prospectus",
  "prospectus_supplement",
  "statement_of_additional_information",
  "interval_fund",
  "other",
];

export interface FundDocumentInitiate {
  filename: string;
  category: FundDocCategory;
  size_bytes: number;
  sha256?: string | null;
  effective_date?: ISODate | null;
  supersedes_document_id?: UUID | null;
}

export interface FundDocumentUpdate {
  effective_date?: ISODate | null;
  supersedes_document_id?: UUID | null;
}

export interface FundTermsOut {
  as_of: ISODate;
  terms: ConstraintOut[];
  /** Ids of approved terms in force on `as_of` (what a simulation on that date would use). */
  applicable_ids: UUID[];
}

// ----------------------------------------------------------------------------- workspace

export interface ReviewItem {
  constraint: ConstraintOut;
  owner_type: "household" | "fund";
  owner_id: UUID;
  owner_name: string;
}

export interface ReviewQueueOut {
  items: ReviewItem[];
  total: number;
  household_items: number;
  library_items: number;
}

export interface ScenarioListItem {
  id: UUID;
  name: string;
  household_id: UUID;
  household_name: string;
  updated_at: ISODateTime;
  latest_run_id: UUID | null;
  latest_run_at: ISODateTime | null;
  latest_first_shortfall_month: number | null;
  latest_peak_shortfall: Decimal | null;
}

// ----------------------------------------------------------------------------- term conflicts (409)

export interface TermConflictCandidate {
  constraint_id: UUID;
  value: number;
  unit: string | null;
  document: string;
  pdf_page: number;
  review_status: string;
}

export interface TermConflict {
  term: string;
  constraint_type: string;
  asset_key: string;
  candidates: TermConflictCandidate[];
}

export interface TermConflictDetails {
  conflicts: TermConflict[];
  as_of_date?: ISODate;
}

// ----------------------------------------------------------------------------- blind spots

export type BlindSpotSeverity = "critical" | "high" | "moderate";

export interface BlindSpotEvidence {
  document: string;
  pdf_page: number;
  quote: string;
  id?: UUID;
  type?: string;
}

export interface BlindSpotRule {
  rule: string;
  peak_shortfall_reduction: number;
  removes_shortfall: boolean;
  basis: string;
  relaxation?: string;
  evidence: BlindSpotEvidence[];
}

export interface BlindSpotRisk {
  rank: number;
  variant: string;
  label: string;
  tier: string | number;
  changes: string[];
  severity: BlindSpotSeverity | string;
  blind_spot: boolean;
  first_shortfall_month: number | null;
  shortfall_amount: number;
  peak_shortfall: number;
  peak_in_months_of_spending: number | null;
  paper_wealth_first_shortfall_month: number | null;
  binding_in_first_shortfall_month: string[];
  contributing_rules: BlindSpotRule[];
}

export interface BlindSpotModelSummary {
  first_shortfall_month: number | null;
  shortfall_amount: number;
  peak_shortfall: number;
  min_cash: number;
}

export interface BlindSpotComparison {
  variant: string;
  label: string;
  tier?: string | number;
  changes: string[];
  contract_aware: BlindSpotModelSummary;
  paper_wealth: BlindSpotModelSummary;
  monthly_cash: number[];
  monthly_cash_paper_wealth: number[];
}

export interface BlindSpotResult {
  method: string;
  disclaimer: string;
  monthly_spending: number;
  summary: { variants: number; risks: number; blind_spots: number; critical: number };
  risks: BlindSpotRisk[];
  comparison: BlindSpotComparison[];
}

export interface BlindSpotSummary {
  id: UUID;
  household_id: UUID;
  scenario_id: UUID;
  engine_version: string;
  as_of_date: ISODate;
  risk_count: number;
  blind_spot_count: number;
  created_at: ISODateTime;
}

export interface BlindSpotOut extends BlindSpotSummary {
  warnings: string[];
  constraint_versions: Record<string, unknown>[];
  result: BlindSpotResult;
}

// ----------------------------------------------------------------------------- reports (GET /me/reports)

export interface ReportExportItem extends ExportOut {
  household_name: string;
}

export interface ReportBlindSpotItem extends BlindSpotSummary {
  household_name: string;
  scenario_name: string;
}

export interface ReportsOut {
  exports: ReportExportItem[];
  blind_spot_reports: ReportBlindSpotItem[];
}

/** One entry of RunDetail.constraint_versions (backend/app/services/engine_adapter.py). */
export interface RunConstraintVersion {
  id: UUID;
  revision: number;
  type: string;
  asset_key: string;
  value: Decimal | null;
  document: string;
  pdf_page: number;
  owner?: "household" | "fund" | string;
  fund_id?: UUID | null;
  effective_from?: ISODate | null;
  effective_to?: ISODate | null;
}
