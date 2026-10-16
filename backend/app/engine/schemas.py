"""Typed contract-constraint schema shared by the extractor, UI and simulator.

A constraint is a single liquidity-relevant term found in a document. Numeric
terms carry a value (or a range); qualitative terms (e.g. board discretion)
carry `value=None` and a textual condition so that vague legal language is
never silently converted into a precise number.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ConstraintType(str, Enum):
    REDEMPTION_MONTHLY_CAP = "redemption_monthly_cap"
    REDEMPTION_QUARTERLY_CAP = "redemption_quarterly_cap"
    PRO_RATA_FULFILLMENT = "pro_rata_fulfillment"
    BOARD_DISCRETION = "board_discretion"
    RESUBMISSION_REQUIRED = "resubmission_required"
    EARLY_REDEMPTION_DEDUCTION = "early_redemption_deduction"
    SETTLEMENT_TIMING = "settlement_timing"
    REPURCHASE_OFFER_SIZE = "repurchase_offer_size"
    REPURCHASE_OFFER_FREQUENCY = "repurchase_offer_frequency"
    REPURCHASE_FEE = "repurchase_fee"
    PAYMENT_TIMING = "payment_timing"
    SBL_ADVANCE_RATE = "sbl_advance_rate"
    SBL_MAINTENANCE_THRESHOLD = "sbl_maintenance_threshold"
    SBL_CURE_PERIOD = "sbl_cure_period"
    SBL_INTEREST_RATE = "sbl_interest_rate"
    CAPITAL_CALL_NOTICE = "capital_call_notice"
    CAPITAL_CALL_SCHEDULE = "capital_call_schedule"
    DEFAULT_PENALTY = "default_penalty"
    RSU_WITHHOLDING_RATE = "rsu_withholding_rate"
    RSU_MAX_WITHHOLDING_RATE = "rsu_max_withholding_rate"
    TRADING_WINDOW = "trading_window"
    REDEMPTION_SUSPENSION = "redemption_suspension"
    REDEMPTION_NOTICE_PERIOD = "redemption_notice_period"
    CAPITAL_COMMITMENT = "capital_commitment"
    DEMAND_REPAYMENT = "demand_repayment"
    VESTING_SCHEDULE = "vesting_schedule"
    TERMINATION_CONDITION = "termination_condition"
    OTHER = "other"


class ValueKind(str, Enum):
    """How a number in a clause should be read. A maximum is a cap the counterparty may fill less of -
    never a guaranteed amount."""
    MAXIMUM = "maximum"
    MINIMUM = "minimum"
    EXACT = "exact"
    RANGE = "range"
    QUALITATIVE = "qualitative"


class SourceType(str, Enum):
    SOURCE_BACKED = "source_backed"            # quoted from a real, supplied document
    SYNTHETIC_DOCUMENT = "synthetic_document"  # quoted from a synthetic sample contract
    USER_CONFIRMED = "user_confirmed"          # value confirmed/edited by the advisor
    SCENARIO_ASSUMPTION = "scenario_assumption"  # modelling assumption, no source clause


class ReviewStatus(str, Enum):
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    EDITED = "edited"
    REJECTED = "rejected"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExtractionMethod(str, Enum):
    LLM = "llm"
    RULE_BASED = "rule_based"
    MANUAL = "manual"


class AssetKey(str, Enum):
    """Which household position a constraint governs."""
    NON_TRADED_REIT = "non_traded_reit"
    INTERVAL_FUND = "interval_fund"
    SBL = "sbl"
    PRIVATE_FUND = "private_fund"
    RSU = "rsu"
    OTHER = "other"


class ContractConstraint(BaseModel):
    constraint_id: str
    constraint_type: ConstraintType
    asset_key: AssetKey = AssetKey.OTHER
    description: str
    value: Optional[float] = None
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None
    unit: Optional[str] = None
    timing: Optional[str] = None
    conditions: Optional[str] = None
    document_id: str
    document_name: str
    pdf_page: int = Field(ge=1, description="1-indexed physical page in the PDF file")
    printed_page: Optional[str] = None
    document_section: Optional[str] = None  # e.g. which prospectus supplement the page belongs to
    evidence_quote: str
    quote_verified: bool = False
    interpretation: str
    confidence: Confidence = Confidence.MEDIUM
    source_type: SourceType
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW
    extraction_method: ExtractionMethod = ExtractionMethod.RULE_BASED
    corroborating_pages: list[int] = Field(default_factory=list)
    original_value: Optional[float] = None  # value as extracted, before any advisor edit
    value_kind: Optional[ValueKind] = None
    exceptions: list[str] = Field(default_factory=list)
    discretion: Optional[str] = None
    ambiguous: bool = False
    validation_issues: list[dict] = Field(default_factory=list)  # [{code, severity, message}]

    @property
    def is_qualitative(self) -> bool:
        return self.value is None and self.lower_bound is None and self.upper_bound is None


class ExtractionReport(BaseModel):
    document_id: str
    document_name: str
    method: ExtractionMethod
    constraints: list[ContractConstraint] = Field(default_factory=list)
    pages_total: int = 0
    pages_failed: list[int] = Field(default_factory=list)
    excerpts_used: int = 0
    messages: list[str] = Field(default_factory=list)


# --- LLM output schema -------------------------------------------------------
# A deliberately flat schema for schema-constrained JSON output. The model only
# reports what the excerpt says; document/page metadata is attached by our code
# from the excerpt the quote came from, never invented by the model.

class LLMExtractedTerm(BaseModel):
    excerpt_id: str
    constraint_type: ConstraintType
    asset_key: AssetKey
    description: str
    value: Optional[float]
    lower_bound: Optional[float]
    upper_bound: Optional[float]
    unit: Optional[str]
    timing: Optional[str]
    conditions: Optional[str]
    exceptions: list[str]
    discretion: Optional[str]
    value_kind: ValueKind
    evidence_quote: str
    interpretation: str
    confidence: Confidence
    ambiguous: bool


class LLMExtractionOutput(BaseModel):
    terms: list[LLMExtractedTerm]


def _nullable(t: str) -> dict:
    return {"anyOf": [{"type": t}, {"type": "null"}]}


LLM_OUTPUT_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "excerpt_id": {"type": "string"},
                    "constraint_type": {"type": "string", "enum": [c.value for c in ConstraintType]},
                    "asset_key": {"type": "string", "enum": [a.value for a in AssetKey]},
                    "description": {"type": "string"},
                    "value": _nullable("number"),
                    "lower_bound": _nullable("number"),
                    "upper_bound": _nullable("number"),
                    "unit": _nullable("string"),
                    "timing": _nullable("string"),
                    "conditions": _nullable("string"),
                    "exceptions": {"type": "array", "items": {"type": "string"}},
                    "discretion": _nullable("string"),
                    "value_kind": {"type": "string", "enum": [v.value for v in ValueKind]},
                    "evidence_quote": {"type": "string"},
                    "interpretation": {"type": "string"},
                    "confidence": {"type": "string", "enum": [c.value for c in Confidence]},
                    "ambiguous": {"type": "boolean"},
                },
                "required": [
                    "excerpt_id", "constraint_type", "asset_key", "description", "value",
                    "lower_bound", "upper_bound", "unit", "timing", "conditions", "exceptions",
                    "discretion", "value_kind", "evidence_quote", "interpretation", "confidence", "ambiguous",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["terms"],
    "additionalProperties": False,
}
