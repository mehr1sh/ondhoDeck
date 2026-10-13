"""Turn parsed documents into evidence-linked `ContractConstraint`s.

Two extraction paths share the same output schema:

* `extract_rule_based` - deterministic regex patterns for the clause families
  used in the demo. Needs no API key. Every quote is the sentence actually found
  on the cited page.
* `extract_with_llm` - retrieves the top excerpts, asks the LLM for structured
  terms, validates them with Pydantic (one bounded retry), then *verifies* each
  evidence quote against the cited page text. Unverified or ambiguous terms are
  flagged for review, never silently accepted.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from pydantic import ValidationError

from .document_parser import ParsedDocument, normalize_text
from .llm_service import LLMError, call_structured
from .retrieval import Excerpt, retrieve_excerpts
from .schemas import (
    LLM_OUTPUT_JSON_SCHEMA,
    AssetKey,
    Confidence,
    ConstraintType,
    ContractConstraint,
    ExtractionMethod,
    ExtractionReport,
    LLMExtractionOutput,
    ReviewStatus,
    SourceType,
)
from .synthetic_docs import is_synthetic_document

# Types whose meaning is a condition, not a number. A numeric value on one of
# these would turn discretionary legal language into an unsupported "fact".
QUALITATIVE_TYPES = {
    ConstraintType.PRO_RATA_FULFILLMENT,
    ConstraintType.BOARD_DISCRETION,
    ConstraintType.RESUBMISSION_REQUIRED,
    ConstraintType.TRADING_WINDOW,
}

_WORD_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10, "fourteen": 14, "fifteen": 15, "thirty": 30}


def _num(s: str) -> float:
    s = s.strip().lower()
    return float(_WORD_NUMS[s]) if s in _WORD_NUMS else float(s)


# --- quote handling ----------------------------------------------------------

def verify_quote(quote: str, page_text: str) -> bool:
    q, t = normalize_text(quote), normalize_text(page_text)
    if not q:
        return False
    return q in t or q.lower() in t.lower()


def find_quote_page(quote: str, doc: ParsedDocument, preferred: int | None = None) -> int | None:
    if preferred is not None:
        p = doc.page(preferred)
        if p and verify_quote(quote, p.text):
            return preferred
    for p in doc.pages:
        if verify_quote(quote, p.text):
            return p.pdf_page
    return None


def _sentence_around(text: str, start: int, end: int, max_len: int = 900) -> str:
    """Expand a match span to whole sentences within normalized page text."""
    left = start
    while left > 0:
        k = text.rfind(". ", 0, left)
        if k == -1:
            left = 0
            break
        # skip abbreviations like "Inc." / "U.S."
        if re.search(r"(Inc|Co|U\.S|No|e\.g|i\.e)\.$", text[max(0, k - 4):k + 1]):
            left = k
            continue
        left = k + 2
        break
    right = text.find(". ", end)
    right = len(text) if right == -1 else right + 1
    return text[left:right].strip()[:max_len]


# --- rule-based patterns -----------------------------------------------------

@dataclass
class RulePattern:
    key: str
    regex: str
    constraint_type: ConstraintType
    asset_key: AssetKey
    description: str
    interpretation: str
    value_fn: Optional[Callable[[re.Match], float]] = None
    unit: Optional[str] = None
    timing: Optional[str] = None
    conditions: Optional[str] = None
    confidence: Confidence = Confidence.HIGH
    extend_next_sentence_if: Optional[str] = None  # include following sentence if it contains this


RULES: list[RulePattern] = [
    # ---- Non-traded REIT share repurchase plan (BREIT prospectus) ----
    RulePattern(
        "reit_monthly", r"no more than (\d+(?:\.\d+)?)% of (?:our|the Company's) aggregate NAV per month",
        ConstraintType.REDEMPTION_MONTHLY_CAP, AssetKey.NON_TRADED_REIT,
        "Fund-level cap on total repurchases per month",
        "Total repurchases across all investors are capped at this % of aggregate NAV (prior month-end) "
        "each month. A single household's fill depends on how much other investors request.",
        lambda m: float(m.group(1)), "% of aggregate NAV", "per month",
        "Measured using aggregate NAV as of the end of the immediately preceding month"),
    RulePattern(
        "reit_quarterly", r"no more than (\d+(?:\.\d+)?)% of (?:our|the Company's) aggregate NAV per calendar quarter",
        ConstraintType.REDEMPTION_QUARTERLY_CAP, AssetKey.NON_TRADED_REIT,
        "Fund-level cap on total repurchases per calendar quarter",
        "Repurchases within a calendar quarter cannot exceed this % of average aggregate NAV; because both "
        "limits are assessed each month, the third month of a quarter can have less than the full monthly "
        "capacity remaining.",
        lambda m: float(m.group(1)), "% of average aggregate NAV", "per calendar quarter",
        "Measured using average aggregate NAV as of the end of the immediately preceding three months",
        extend_next_sentence_if="both of these limits are assessed"),
    RulePattern(
        "reit_pro_rata",
        r"(?:repurchase requests will be satisfied on a pro rata basis|will be repurchased on a pro rata basis)",
        ConstraintType.PRO_RATA_FULFILLMENT, AssetKey.NON_TRADED_REIT,
        "Oversubscribed months are filled pro rata",
        "When aggregate requests exceed available capacity, each request is filled in the same proportion "
        "(after death/disability/divorce and other limited exceptions). The fill % itself is NOT disclosed "
        "in advance - it depends on aggregate demand, which the simulator treats as a scenario assumption.",
        timing="monthly, at repurchase date"),
    RulePattern(
        "reit_board", r"may determine to repurchase fewer shares than have been requested to be repurchased[^.]*?or none at all",
        ConstraintType.BOARD_DISCRETION, AssetKey.NON_TRADED_REIT,
        "Board may repurchase fewer shares than requested, or none",
        "Discretionary: the board can repurchase below the 2%/5% limits or suspend entirely. No guaranteed "
        "fill rate exists; any stressed fill reduction must be an explicit scenario assumption.",
        confidence=Confidence.HIGH),
    RulePattern(
        "reit_resubmit", r"All unsatisfied repurchase requests must be resubmitted",
        ConstraintType.RESUBMISSION_REQUIRED, AssetKey.NON_TRADED_REIT,
        "Unfilled requests do not carry over automatically",
        "The unfilled portion of a request must be resubmitted next month/quarter; the simulator assumes "
        "the household resubmits its remaining target every month."),
    RulePattern(
        "reit_early_deduction",
        r"repurchased at (\d+(?:\.\d+)?)% of the transaction price \(the \"Early Repurchase Deduction\"\)",
        ConstraintType.EARLY_REDEMPTION_DEDUCTION, AssetKey.NON_TRADED_REIT,
        "Shares held under one year are repurchased at a discount",
        "Quoted as a % of transaction price paid; deduction = 100% minus that figure. Applies only to "
        "shares outstanding less than one year.",
        lambda m: round(100.0 - float(m.group(1)), 4), "% of transaction price (deduction)",
        "if held < 1 year"),
    RulePattern(
        "reit_settlement", r"Settlements of share repurchases will generally be made within (\w+) business days of the Repurchase Date",
        ConstraintType.SETTLEMENT_TIMING, AssetKey.NON_TRADED_REIT,
        "Cash settles a few business days after the month-end repurchase date",
        "Repurchases occur at month-end, so proceeds typically arrive early the following month. The "
        "simulator models a one-month settlement lag (modelling interpretation).",
        lambda m: _num(m.group(1)), "business days", "after Repurchase Date"),
    # ---- Synthetic interval fund ----
    RulePattern(
        "if_offer", r"currently expects to offer to repurchase (\d+(?:\.\d+)?)% of its outstanding Shares in each quarterly repurchase offer",
        ConstraintType.REPURCHASE_OFFER_SIZE, AssetKey.INTERVAL_FUND,
        "Quarterly repurchase offer size",
        "Each quarterly offer is for this % of outstanding shares; tenders above it are prorated.",
        lambda m: float(m.group(1)), "% of outstanding shares", "quarterly"),
    RulePattern(
        "if_months", r"Repurchase offers will be made in ([A-Z][a-z]+(?:, [A-Z][a-z]+)*,? and [A-Z][a-z]+) of each year",
        ConstraintType.REPURCHASE_OFFER_FREQUENCY, AssetKey.INTERVAL_FUND,
        "Repurchase offers only in quarter-end months",
        "Interval-fund liquidity is only available in the listed offer months.",
        timing="March, June, September, December"),
    RulePattern(
        "if_pro_rata", r"the Fund will repurchase tendered Shares on a pro rata basis",
        ConstraintType.PRO_RATA_FULFILLMENT, AssetKey.INTERVAL_FUND,
        "Oversubscribed offers are prorated",
        "Fill % depends on aggregate tenders, treated as a scenario assumption."),
    RulePattern(
        "if_fee", r"repurchase fee of (\d+(?:\.\d+)?)% of the net asset value",
        ConstraintType.REPURCHASE_FEE, AssetKey.INTERVAL_FUND,
        "Repurchase fee on tendered shares", "Deducted from proceeds.",
        lambda m: float(m.group(1)), "% of NAV repurchased"),
    RulePattern(
        "if_payment", r"Payment for repurchased Shares will be made no later than (\w+) days after the Repurchase Pricing Date",
        ConstraintType.PAYMENT_TIMING, AssetKey.INTERVAL_FUND,
        "Payment lag after pricing date",
        "Pricing up to 14 days after the deadline plus up to 7 days to pay: modelled as a one-month lag.",
        lambda m: _num(m.group(1)), "days", "after Repurchase Pricing Date"),
    # ---- Synthetic securities-backed line ----
    RulePattern(
        "sbl_advance", r"extend credit up to an amount equal to (\d+(?:\.\d+)?)% of the market value of Eligible Collateral",
        ConstraintType.SBL_ADVANCE_RATE, AssetKey.SBL,
        "Maximum loan as % of pledged collateral",
        "Borrowing capacity = advance rate x collateral value; it shrinks as markets fall.",
        lambda m: float(m.group(1)), "% of collateral market value"),
    RulePattern(
        "sbl_maint", r"Loan Balance exceeds (\d+(?:\.\d+)?)% of the market value of the Collateral",
        ConstraintType.SBL_MAINTENANCE_THRESHOLD, AssetKey.SBL,
        "Loan-to-value that triggers a collateral call",
        "Above this LTV the borrower must restore the loan to the advance rate.",
        lambda m: float(m.group(1)), "% loan-to-value"),
    RulePattern(
        "sbl_cure", r"Upon a Collateral Call, the Borrower must, within (\w+) business days",
        ConstraintType.SBL_CURE_PERIOD, AssetKey.SBL,
        "Time to cure a collateral call",
        "Shorter than one month: the cure is due in the same simulated month as the call.",
        lambda m: _num(m.group(1)), "business days"),
    RulePattern(
        "sbl_rate", r"fixed annual rate of (\d+(?:\.\d+)?)%",
        ConstraintType.SBL_INTEREST_RATE, AssetKey.SBL,
        "Interest rate on the line", "Interest paid monthly in cash.",
        lambda m: float(m.group(1)), "% per annum", "monthly in arrears"),
    # ---- Synthetic private fund LPA ----
    RulePattern(
        "pf_notice", r"upon not less than (\w+) business days' prior written notice",
        ConstraintType.CAPITAL_CALL_NOTICE, AssetKey.PRIVATE_FUND,
        "Capital-call notice period",
        "A call can be due within ~2 weeks of notice: effectively same-month cash demand.",
        lambda m: _num(m.group(1)), "business days"),
    RulePattern(
        "pf_discretion", r"timing and amount of capital calls are at the sole discretion of the General Partner",
        ConstraintType.CAPITAL_CALL_SCHEDULE, AssetKey.PRIVATE_FUND,
        "Call timing/amount at GP discretion; not deferred for market conditions",
        "No contractual schedule: the demo's call amount and month are scenario assumptions.",
        confidence=Confidence.HIGH),
    RulePattern(
        "pf_default", r"charge interest at (\d+(?:\.\d+)?)% per annum on the unpaid amount",
        ConstraintType.DEFAULT_PENALTY, AssetKey.PRIVATE_FUND,
        "Default penalty on unfunded calls",
        "Missing a call is costly (interest plus possible forfeiture of up to 50% of the capital account), "
        "so the simulator treats calls as mandatory.",
        lambda m: float(m.group(1)), "% per annum", conditions="Possible forfeiture of up to 50% of capital account"),
    # ---- Synthetic RSU grant / trading policy ----
    RulePattern(
        "rsu_withholding", r"at the federal supplemental wage rate of (\d+(?:\.\d+)?)%",
        ConstraintType.RSU_WITHHOLDING_RATE, AssetKey.RSU,
        "Default withholding on vesting RSUs",
        "Shares are withheld at this rate; tax above it is paid later in cash.",
        lambda m: float(m.group(1)), "% of vest value", "at vest"),
    RulePattern(
        "rsu_max_withholding", r"elect a withholding rate up to the maximum individual statutory rate of (\d+(?:\.\d+)?)%",
        ConstraintType.RSU_MAX_WITHHOLDING_RATE, AssetKey.RSU,
        "Maximum electable withholding",
        "Upper bound for the 'adjust RSU withholding' prevention option.",
        lambda m: float(m.group(1)), "% of vest value", "at vest"),
    RulePattern(
        "rsu_window", r"may trade Company securities only during an open trading window",
        ConstraintType.TRADING_WINDOW, AssetKey.RSU,
        "Vested shares can be sold only in open windows",
        "Windows open after quarterly earnings (released the month after quarter-end) and close on the 15th "
        "of the quarter's third month: modelled as open in Feb, May, Aug, Nov (interpretation).",
        extend_next_sentence_if="trading window opens"),
]


def _source_type_for(doc: ParsedDocument) -> SourceType:
    first = doc.pages[0].text if doc.pages else ""
    return SourceType.SYNTHETIC_DOCUMENT if is_synthetic_document(doc.name, first) else SourceType.SOURCE_BACKED


def extract_rule_based(doc: ParsedDocument) -> ExtractionReport:
    report = ExtractionReport(document_id=doc.document_id, document_name=doc.name,
                              method=ExtractionMethod.RULE_BASED, pages_total=doc.page_count,
                              pages_failed=list(doc.failed_pages))
    src = _source_type_for(doc)
    norm_pages = [(p, normalize_text(p.text)) for p in doc.pages]
    for rule in RULES:
        rx = re.compile(rule.regex)
        first = None
        others: list[int] = []
        for p, text in norm_pages:
            m = rx.search(text)
            if not m:
                continue
            if first is None:
                first = (p, text, m)
            else:
                others.append(p.pdf_page)
        if first is None:
            continue
        p, text, m = first
        quote = _sentence_around(text, m.start(), m.end())
        if rule.extend_next_sentence_if:
            after = text[text.find(quote) + len(quote):].strip()
            nxt_end = after.find(". ")
            nxt = after[: nxt_end + 1] if nxt_end != -1 else after
            if rule.extend_next_sentence_if in nxt:
                quote = f"{quote} {nxt}"
        value = rule.value_fn(m) if rule.value_fn else None
        report.constraints.append(ContractConstraint(
            constraint_id=f"{doc.document_id}:{rule.key}",
            constraint_type=rule.constraint_type, asset_key=rule.asset_key,
            description=rule.description, value=value, original_value=value, unit=rule.unit,
            timing=rule.timing, conditions=rule.conditions, document_id=doc.document_id,
            document_name=doc.name, pdf_page=p.pdf_page, printed_page=p.printed_page,
            document_section=p.section, evidence_quote=quote, quote_verified=verify_quote(quote, p.text),
            interpretation=rule.interpretation, confidence=rule.confidence, source_type=src,
            review_status=ReviewStatus.NEEDS_REVIEW, extraction_method=ExtractionMethod.RULE_BASED,
            corroborating_pages=sorted(set(others))[:25],
        ))
    if not report.constraints:
        report.messages.append("No known clause patterns matched. Try LLM extraction or manual review.")
    if doc.failed_pages:
        report.messages.append(f"{len(doc.failed_pages)} page(s) had no extractable text: "
                               f"{doc.failed_pages[:20]}{'...' if len(doc.failed_pages) > 20 else ''}")
    return report


# --- LLM path -----------------------------------------------------------------

SYSTEM_PROMPT = """You extract liquidity-relevant contractual terms from financial documents \
(fund prospectuses, interval-fund repurchase policies, securities-backed lending agreements, \
limited partnership agreements, RSU grant documents).

Your output feeds a deterministic cash-flow simulator that advisors audit, so fidelity to the text \
matters more than coverage:
- Report only terms stated in the excerpts. The evidence_quote must be copied verbatim from a single \
excerpt (one or two consecutive sentences), and excerpt_id must name that excerpt.
- Numeric fields hold numbers stated in the quote (e.g. 2 for "2%"). Keep the unit in `unit`.
- Discretionary or conditional language ("may", "up to", "at the board's discretion", "or none at \
all") is a condition, not a number: leave value/lower_bound/upper_bound null for pro-rata, board \
discretion, resubmission and trading-window terms, describe the condition in `conditions`, and set \
ambiguous=true when the effect on available cash cannot be determined from the text alone.
- Do not infer historical fill rates, demand levels or anything not in the excerpts.
- If the same term appears in several excerpts, report it once, from the clearest excerpt."""


def _format_excerpts(excerpts: list[Excerpt]) -> str:
    blocks = []
    for e in excerpts:
        pp = f", printed page {e.printed_page}" if e.printed_page else ""
        blocks.append(f'<excerpt id="{e.excerpt_id}" document="{e.document_name}" pdf_page="{e.pdf_page}"{pp}>\n'
                      f"{normalize_text(e.text)}\n</excerpt>")
    return "\n\n".join(blocks)


def extract_with_llm(doc: ParsedDocument, top_k: int = 8,
                     call: Callable[[str, str, dict], dict] | None = None) -> ExtractionReport:
    """LLM extraction over retrieved excerpts. Raises LLMError if the provider is unavailable.

    `call(system, user, json_schema) -> dict` performs one schema-constrained request; it defaults
    to the environment-configured client in llm_service and is injected by the web worker/tests.
    """
    call = call or call_structured
    report = ExtractionReport(document_id=doc.document_id, document_name=doc.name,
                              method=ExtractionMethod.LLM, pages_total=doc.page_count,
                              pages_failed=list(doc.failed_pages))
    excerpts = retrieve_excerpts(doc, top_k=top_k)
    report.excerpts_used = len(excerpts)
    if not excerpts:
        report.messages.append("No liquidity-relevant excerpts found by retrieval.")
        return report
    by_id = {e.excerpt_id: e for e in excerpts}
    user = ("Extract every liquidity constraint stated in these excerpts.\n\n" + _format_excerpts(excerpts))

    parsed: LLMExtractionOutput | None = None
    last_err = ""
    for attempt in range(2):  # one bounded retry on malformed/invalid output
        prompt = user if attempt == 0 else (
            user + f"\n\nYour previous answer failed validation ({last_err}). Return JSON matching the schema.")
        try:
            raw = call(SYSTEM_PROMPT, prompt, LLM_OUTPUT_JSON_SCHEMA)
            parsed = LLMExtractionOutput.model_validate(raw)
            break
        except ValidationError as exc:
            last_err = str(exc)[:300]
        except LLMError as exc:
            if "malformed JSON" in str(exc) or "truncated" in str(exc):
                last_err = str(exc)
                continue
            raise
    if parsed is None:
        raise LLMError(f"LLM output failed validation twice: {last_err}")

    src = _source_type_for(doc)
    for i, t in enumerate(parsed.terms):
        ex = by_id.get(t.excerpt_id)
        preferred = ex.pdf_page if ex else None
        page_no = find_quote_page(t.evidence_quote, doc, preferred)
        verified = page_no is not None
        if page_no is None:
            page_no = preferred or 1
        page = doc.page(page_no)
        value, lo, hi = t.value, t.lower_bound, t.upper_bound
        notes = []
        if t.constraint_type in QUALITATIVE_TYPES and any(v is not None for v in (value, lo, hi)):
            notes.append("numeric value removed: qualitative clause")
            value = lo = hi = None
        confidence = t.confidence
        if not verified:
            notes.append("evidence quote not found verbatim in document")
            confidence = Confidence.LOW
        if t.ambiguous:
            notes.append("model flagged as ambiguous")
        report.constraints.append(ContractConstraint(
            constraint_id=f"{doc.document_id}:llm{i}", constraint_type=t.constraint_type,
            asset_key=t.asset_key, description=t.description, value=value, original_value=value,
            lower_bound=lo, upper_bound=hi, unit=t.unit, timing=t.timing,
            conditions="; ".join(x for x in (t.conditions, *notes) if x) or None,
            document_id=doc.document_id, document_name=doc.name, pdf_page=page_no,
            printed_page=page.printed_page if page else None,
            document_section=page.section if page else None, evidence_quote=t.evidence_quote,
            quote_verified=verified, interpretation=t.interpretation, confidence=confidence,
            source_type=src, review_status=ReviewStatus.NEEDS_REVIEW,
            extraction_method=ExtractionMethod.LLM,
            corroborating_pages=sorted(ex.duplicate_pages)[:25] if ex else [],
        ))
    unverified = sum(not c.quote_verified for c in report.constraints)
    if unverified:
        report.messages.append(f"{unverified} quote(s) could not be verified against the PDF text - review required.")
    return report
