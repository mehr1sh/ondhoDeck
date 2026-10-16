"""Contract-specific validation of extracted constraints (applied to rule-based and LLM output alike).

Validation never changes a value. It records issues on the constraint (`validation_issues`), sets
`ambiguous` when discretion or conditions in the clause were not captured, lowers confidence for
errors, and fills a default `value_kind`. Every candidate still requires human review.

Severity: "error" means the evidence does not support the term as extracted, so it cannot be approved as a
source-backed value (a reviewer must edit or reject it); "warning" asks the reviewer to check something;
"info" records a relationship (e.g. a related clause of the same type) without judging either clause.
"""
from __future__ import annotations

import re

from .document_parser import normalize_text
from .schemas import Confidence, ConstraintType, ContractConstraint, ValueKind

T = ConstraintType
DEFAULT_VALUE_KIND = {
    T.REDEMPTION_MONTHLY_CAP: ValueKind.MAXIMUM, T.REDEMPTION_QUARTERLY_CAP: ValueKind.MAXIMUM,
    T.REPURCHASE_OFFER_SIZE: ValueKind.EXACT, T.EARLY_REDEMPTION_DEDUCTION: ValueKind.EXACT,
    T.REPURCHASE_FEE: ValueKind.EXACT, T.SETTLEMENT_TIMING: ValueKind.MAXIMUM, T.PAYMENT_TIMING: ValueKind.MAXIMUM,
    T.SBL_ADVANCE_RATE: ValueKind.MAXIMUM, T.SBL_MAINTENANCE_THRESHOLD: ValueKind.EXACT,
    T.SBL_CURE_PERIOD: ValueKind.MAXIMUM, T.SBL_INTEREST_RATE: ValueKind.EXACT,
    T.CAPITAL_CALL_NOTICE: ValueKind.MINIMUM, T.DEFAULT_PENALTY: ValueKind.EXACT,
    T.RSU_WITHHOLDING_RATE: ValueKind.EXACT, T.RSU_MAX_WITHHOLDING_RATE: ValueKind.MAXIMUM,
    T.REDEMPTION_NOTICE_PERIOD: ValueKind.MINIMUM,
}
PERCENT_TYPES = {T.REDEMPTION_MONTHLY_CAP, T.REDEMPTION_QUARTERLY_CAP, T.REPURCHASE_OFFER_SIZE,
                 T.EARLY_REDEMPTION_DEDUCTION, T.REPURCHASE_FEE, T.SBL_ADVANCE_RATE, T.SBL_MAINTENANCE_THRESHOLD,
                 T.RSU_WITHHOLDING_RATE, T.RSU_MAX_WITHHOLDING_RATE}
DURATION_TYPES = {T.SETTLEMENT_TIMING, T.PAYMENT_TIMING, T.SBL_CURE_PERIOD, T.CAPITAL_CALL_NOTICE,
                  T.REDEMPTION_NOTICE_PERIOD}
CAP_TYPES = {T.REDEMPTION_MONTHLY_CAP, T.REDEMPTION_QUARTERLY_CAP}
# Values legitimately derived from the quoted number rather than appearing in it.
DERIVED_OK = {T.EARLY_REDEMPTION_DEDUCTION}

_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
          10: "ten", 12: "twelve", 14: "fourteen", 15: "fifteen", 20: "twenty", 30: "thirty", 60: "sixty", 90: "ninety"}
DISCRETION_RE = re.compile(r"\b(may|sole (and absolute )?discretion|in its (reasonable )?judgment|at (its|the) option)\b", re.I)
CONDITION_RE = re.compile(r"\b(subject to|unless|provided that|except|other than|if and only if|in the event)\b", re.I)
# Wording that states an upper or lower limit rather than an exact amount.
MAX_WORDING = re.compile(r"\b(within|no later than|not later than|up to|no more than|not more than|not to exceed|"
                         r"may not exceed|limited to|at most|maximum of)\b", re.I)
MIN_WORDING = re.compile(r"\b(at least|not less than|no less than|no fewer than|not fewer than|minimum of)\b", re.I)
UNIT_WORDS = ("business day", "calendar day", "day", "week", "month", "quarter", "year")


def _issue(code: str, severity: str, message: str) -> dict:
    return {"code": code, "severity": severity, "message": message}


def _number_in_text(value: float, text: str) -> bool:
    flat = normalize_text(text).lower().replace(",", "")
    candidates = {f"{value:g}", f"{value:.2f}", f"{value:.1f}"}
    if float(value).is_integer():
        candidates.add(str(int(value)))
        word = _WORDS.get(int(value))
        if word:
            candidates.add(word)
    return any(re.search(rf"(?<![\d.]){re.escape(c)}(?![\d])", flat) for c in candidates)


def validate_constraint(c: ContractConstraint) -> list[dict]:
    issues: list[dict] = []
    t = c.constraint_type
    if c.value_kind is None:
        c.value_kind = DEFAULT_VALUE_KIND.get(t, ValueKind.QUALITATIVE if c.value is None else ValueKind.EXACT)
    if not c.quote_verified:
        issues.append(_issue("quote_not_found", "error", "The evidence quote was not found verbatim in the document."))
    for name in ("value", "lower_bound", "upper_bound"):
        v = getattr(c, name)
        if v is None:
            continue
        if t not in DERIVED_OK and not _number_in_text(v, c.evidence_quote):
            issues.append(_issue("value_not_in_quote", "error",
                                 f"{name}={v:g} does not appear in the quoted clause, so the quote does not support "
                                 "it as a contract value. Edit it with a reviewer note, or reject it."))
        if t in PERCENT_TYPES and not (0 < v <= 100):
            issues.append(_issue("percentage_out_of_range", "error", f"{name}={v:g} is not a percentage between 0 and 100."))
        if t in DURATION_TYPES and not (0 < v <= 3650):
            issues.append(_issue("duration_out_of_range", "error", f"{name}={v:g} is not a plausible period."))
    if t in DURATION_TYPES and c.value is not None and not re.search(r"day|week|month|year", c.unit or "", re.I):
        issues.append(_issue("duration_unit_missing", "warning", "A period needs a time unit (days, months, ...)."))
    quote = normalize_text(c.evidence_quote).lower()
    if c.value is not None and t in PERCENT_TYPES and t not in DERIVED_OK and "%" not in quote and "percent" not in quote:
        issues.append(_issue("unit_not_in_quote", "warning", "A percentage was extracted but the quote states no %."))
    if c.value is not None and t in DURATION_TYPES and c.unit:
        unit = next((u for u in UNIT_WORDS if u in c.unit.lower()), None)
        if unit and unit not in quote:
            issues.append(_issue("unit_not_in_quote", "warning",
                                 f"The unit '{c.unit}' does not appear in the quote; check the period's unit."))
    if c.value is None and c.lower_bound is None and c.upper_bound is None and c.unit:
        issues.append(_issue("unit_without_value", "info", f"A unit ('{c.unit}') was recorded without a value."))
    if c.value is not None and c.value_kind in (ValueKind.EXACT, ValueKind.MAXIMUM, ValueKind.MINIMUM):
        max_m, min_m = MAX_WORDING.search(quote), MIN_WORDING.search(quote)
        expected, words = ((ValueKind.MAXIMUM, max_m.group(0)) if max_m and not min_m else
                           (ValueKind.MINIMUM, min_m.group(0)) if min_m and not max_m else (None, ""))
        if expected is not None and c.value_kind != expected and t not in DERIVED_OK:
            issues.append(_issue("value_kind_conflicts_with_quote", "warning",
                                 f"The quote states a {expected.value} ('{words}'), "
                                 f"but the term is classified as {c.value_kind.value}."))
            c.ambiguous = True
    if t in CAP_TYPES and c.value_kind not in (ValueKind.MAXIMUM, ValueKind.QUALITATIVE):
        issues.append(_issue("cap_not_maximum", "error",
                             "A redemption cap is a maximum the issuer may fill less of, not a guaranteed amount."))
    if c.lower_bound is not None and c.upper_bound is not None and c.lower_bound > c.upper_bound:
        issues.append(_issue("bounds_inverted", "error", "Lower bound exceeds upper bound."))
    if DISCRETION_RE.search(c.evidence_quote) and not (c.discretion or c.conditions):
        issues.append(_issue("discretion_not_recorded", "warning",
                             "The clause contains discretionary language that is not captured in discretion/conditions."))
        c.ambiguous = True
    if CONDITION_RE.search(c.evidence_quote) and not (c.conditions or c.exceptions):
        issues.append(_issue("conditions_not_recorded", "warning",
                             "The clause contains conditional language that is not captured in conditions/exceptions."))
        c.ambiguous = True
    return issues


def _short(quote: str, n: int = 140) -> str:
    q = normalize_text(quote)
    return q if len(q) <= n else q[: n - 1] + "…"


def _same_type_checks(constraints: list[ContractConstraint]) -> None:
    """Clauses of the same type for the same position in one document are never merged here: differing values are
    a conflict for the reviewer; differing wording is recorded as a related clause on both, with its page."""
    groups: dict[tuple, list[ContractConstraint]] = {}
    for c in constraints:
        groups.setdefault((c.document_id, c.constraint_type, c.asset_key), []).append(c)
    for group in groups.values():
        if len(group) < 2:
            continue
        for c in group:
            for other in group:
                if other is c:
                    continue
                if c.value is not None and other.value is not None and abs(c.value - other.value) > 1e-9:
                    c.validation_issues.append(_issue(
                        "conflicting_values", "error",
                        f"Another {c.constraint_type.value} clause (PDF page {other.pdf_page}) states {other.value:g}; "
                        "decide which applies (or whether they apply at different times) before approving."))
                else:
                    c.validation_issues.append(_issue(
                        "related_clause", "info",
                        f"Related {c.constraint_type.value} clause on PDF page {other.pdf_page}: “{_short(other.evidence_quote)}” "
                        "Both are kept; review whether they are separate rules or the same rule."))


def dedupe_constraints(constraints: list[ContractConstraint]) -> list[ContractConstraint]:
    """Drop exact repeats (same document, type, position, values, unit and quote wording), keeping the first and
    recording the repeat's page as corroborating. Anything that differs is kept for review."""
    seen: dict[tuple, ContractConstraint] = {}
    out: list[ContractConstraint] = []
    for c in constraints:
        key = (c.document_id, c.constraint_type, c.asset_key, c.value, c.lower_bound, c.upper_bound,
               (c.unit or "").strip().lower(), normalize_text(c.evidence_quote).lower())
        first = seen.get(key)
        if first is None:
            seen[key] = c
            out.append(c)
        elif c.pdf_page != first.pdf_page and c.pdf_page not in first.corroborating_pages:
            first.corroborating_pages = sorted({*first.corroborating_pages, c.pdf_page})[:25]
    return out


def validate_constraints(constraints: list[ContractConstraint]) -> list[ContractConstraint]:
    """Validate each constraint plus cross-rule checks within the same document."""
    for c in constraints:
        c.validation_issues = validate_constraint(c)
    _same_type_checks(constraints)
    by_doc: dict[str, dict] = {}
    for c in constraints:
        by_doc.setdefault(c.document_id, {})[c.constraint_type] = c
    for doc in by_doc.values():
        adv, maint = doc.get(T.SBL_ADVANCE_RATE), doc.get(T.SBL_MAINTENANCE_THRESHOLD)
        if adv and maint and adv.value is not None and maint.value is not None and maint.value < adv.value:
            maint.validation_issues.append(_issue("maintenance_below_advance_rate", "error",
                                                  "The maintenance threshold is below the advance rate."))
        mon, qtr = doc.get(T.REDEMPTION_MONTHLY_CAP), doc.get(T.REDEMPTION_QUARTERLY_CAP)
        if mon and qtr and mon.value is not None and qtr.value is not None and qtr.value < mon.value:
            qtr.validation_issues.append(_issue("quarterly_cap_below_monthly", "error",
                                                "The quarterly cap is below the monthly cap."))
    for c in constraints:
        if any(i["severity"] == "error" for i in c.validation_issues):
            c.confidence = Confidence.LOW
    return constraints
