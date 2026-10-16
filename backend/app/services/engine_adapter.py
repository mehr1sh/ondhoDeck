"""Bridge between persisted household data and the deterministic engine.

Household balances and scheduled obligations come from the database; modelling assumptions come
from the scenario; contract terms come only from *approved* extracted constraints. Anything the
engine falls back to (e.g. a default 2% cap with no approved clause) is reported as a warning so it
is never mistaken for a sourced contract fact.

Contract terms come from two places: the household's own approved clauses, and the shared fund library
for holdings linked to a library fund (approved terms in force on the scenario's as-of date, matching the
fund's type). Both go through the same conflict check: agreeing clauses corroborate, disagreeing ones
block the run.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..api_schemas import ScenarioAssumptions
from ..engine.schemas import (
    AssetKey,
    Confidence,
    ConstraintType,
    ContractConstraint,
    ExtractionMethod,
    ReviewStatus,
    SourceType,
)
from ..engine.simulator import (
    APPROVED_STATUSES,
    TERM_MAP_KEYS,
    CapitalCall,
    ContractTerms,
    RsuVest,
    Scenario,
    ScheduledFlow,
    TermConflictError,
    terms_from_constraints,
)
from ..errors import ApiError
from ..models import (
    Asset,
    CashFlow,
    Document,
    ExtractedConstraint,
    Fund,
    Household,
    Liability,
    ScenarioDefinition,
    ScheduledEvent,
)
from .term_resolution import in_force

APPROVED = tuple(sorted(APPROVED_STATUSES))  # same rule as the engine: confirmed or edited only
# Library fund type -> the asset key of the terms that govern a holding of it.
FUND_TERM_ASSET = {"non_traded_reit": "non_traded_reit", "interval_fund": "interval_fund",
                   "private_fund": "private_fund", "other": "other"}
ASSET_FIELD = {"cash": "cash", "brokerage": "brokerage", "non_traded_reit": "reit", "interval_fund": "interval_fund",
               "vested_rsu": "rsu_vested"}


@dataclass
class EngineInputs:
    scenario: Scenario
    terms: ContractTerms
    assumptions: ScenarioAssumptions
    household_snapshot: dict[str, Any]
    constraint_versions: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


def _fx(amount: Decimal, currency: str, reporting: str, rates: dict[str, float], missing: set[str]) -> float:
    if currency == reporting:
        return float(amount)
    rate = rates.get(currency)
    if rate is None:
        missing.add(currency)
        return 0.0
    return float(amount) * rate


def approved_constraints(db: Session, household_id: uuid.UUID,
                         as_of: date | None = None) -> list[tuple[ExtractedConstraint, str]]:
    """The household's own approved clauses (in force on `as_of` when they carry an effective window)."""
    rows = db.execute(
        select(ExtractedConstraint, Document.safe_filename)
        .join(Document, Document.id == ExtractedConstraint.document_id)
        .where(ExtractedConstraint.household_id == household_id, ExtractedConstraint.review_status.in_(APPROVED),
               Document.status != "deleted")
        .order_by(ExtractedConstraint.created_at)
    ).all()
    return [(r[0], r[1]) for r in rows if as_of is None or in_force(r[0], as_of)]


def library_constraints(db: Session, assets: list[Asset], as_of: date
                        ) -> tuple[list[tuple[ExtractedConstraint, str]], list[str]]:
    """Approved library terms in force on `as_of` for funds linked to the household's holdings."""
    fund_ids = sorted({a.fund_id for a in assets if a.fund_id is not None})
    if not fund_ids:
        return [], []
    funds = {f.id: f for f in db.scalars(select(Fund).where(Fund.id.in_(fund_ids)))}
    rows = db.execute(
        select(ExtractedConstraint, Document.safe_filename)
        .join(Document, Document.id == ExtractedConstraint.document_id)
        .where(ExtractedConstraint.fund_id.in_(fund_ids), ExtractedConstraint.review_status.in_(APPROVED),
               Document.status != "deleted")
        .order_by(ExtractedConstraint.created_at)).all()
    used: list[tuple[ExtractedConstraint, str]] = []
    warnings: list[str] = []
    for fid in fund_ids:
        fund = funds[fid]
        mine = [(c, n) for c, n in rows if c.fund_id == fid]
        current = [(c, n) for c, n in mine if in_force(c, as_of)]
        applicable = [(c, n) for c, n in current if c.asset_key == FUND_TERM_ASSET[fund.fund_type]]
        if applicable:
            warnings.append(f"Library fund '{fund.name}': {len(applicable)} approved term(s) in force on "
                            f"{as_of.isoformat()} applied.")
        else:
            warnings.append(f"Library fund '{fund.name}' has no approved terms in force on {as_of.isoformat()}; "
                            "default modelling values apply to its holdings.")
        if len(mine) > len(current):
            warnings.append(f"{len(mine) - len(current)} approved term(s) of '{fund.name}' are outside their "
                            f"effective window on {as_of.isoformat()} (superseded or not yet effective) and were "
                            "not used.")
        if len(current) > len(applicable):
            warnings.append(f"{len(current) - len(applicable)} approved term(s) of '{fund.name}' govern a different "
                            f"asset type than a {fund.fund_type.replace('_', ' ')} holding and were not used.")
        if fund.status == "archived":
            warnings.append(f"Library fund '{fund.name}' is archived; its terms were still applied to linked holdings.")
        used += applicable
    return used, warnings


SIMULATOR_TYPES = {(t.value, a.value) for t, a in TERM_MAP_KEYS} | {
    ("pro_rata_fulfillment", "non_traded_reit"), ("settlement_timing", "non_traded_reit")}


def pending_simulator_terms(db: Session, household_id: uuid.UUID, assets: list[Asset]) -> int:
    """Unreviewed terms (household or linked library funds) of a type that would set a simulator input."""
    fund_ids = [a.fund_id for a in assets if a.fund_id is not None]
    owner = ExtractedConstraint.household_id == household_id
    if fund_ids:
        owner = or_(owner, ExtractedConstraint.fund_id.in_(fund_ids))
    rows = db.execute(select(ExtractedConstraint.constraint_type, ExtractedConstraint.asset_key)
                      .join(Document, Document.id == ExtractedConstraint.document_id)
                      .where(owner, ExtractedConstraint.review_status == "needs_review",
                             Document.status != "deleted")).all()
    return sum((t, a) in SIMULATOR_TYPES for t, a in rows)


def _bucket_warnings(assets: list[Asset]) -> list[str]:
    out = []
    for kind, label in (("non_traded_reit", "non-traded REIT"), ("interval_fund", "interval fund")):
        held = [a for a in assets if a.kind == kind]
        linked = {a.fund_id for a in held if a.fund_id is not None}
        if linked and any(a.fund_id is None for a in held):
            out.append(f"Some {label} holdings are not linked to a library fund; the engine models one {label} "
                       "allocation, so the linked fund's terms are applied to all of it.")
        if len(linked) > 1:
            out.append(f"{len(linked)} different library funds are linked to {label} holdings. The engine models one "
                       f"{label} allocation: their approved terms must agree, otherwise the run is blocked.")
    return out


def to_engine_constraint(c: ExtractedConstraint, document_name: str) -> ContractConstraint:
    f = lambda v: None if v is None else float(v)  # noqa: E731
    return ContractConstraint(
        constraint_id=str(c.id), constraint_type=ConstraintType(c.constraint_type), asset_key=AssetKey(c.asset_key),
        description=c.description, value=f(c.value), lower_bound=f(c.lower_bound), upper_bound=f(c.upper_bound),
        unit=c.unit, timing=c.timing, conditions=c.conditions, document_id=str(c.document_id),
        document_name=document_name, pdf_page=c.pdf_page, printed_page=c.printed_page,
        document_section=c.document_section, evidence_quote=c.evidence_quote, quote_verified=c.quote_verified,
        interpretation=c.interpretation, confidence=Confidence(c.confidence), source_type=SourceType(c.source_type),
        review_status=ReviewStatus(c.review_status), extraction_method=ExtractionMethod(c.extraction_method),
        original_value=f(c.original_value), validation_issues=list(c.validation_issues or []),
        ambiguous=bool(c.ambiguous))


def build_inputs(db: Session, household: Household, scenario_def: ScenarioDefinition) -> EngineInputs:
    a = ScenarioAssumptions.model_validate(scenario_def.assumptions)
    reporting = household.reporting_currency
    rates = {k.upper(): v for k, v in a.fx_rates.items()}
    missing: set[str] = set()
    warnings: list[str] = []
    hid = household.id

    assets = db.scalars(select(Asset).where(Asset.household_id == hid)).all()
    liabilities = db.scalars(select(Liability).where(Liability.household_id == hid)).all()
    flows = db.scalars(select(CashFlow).where(CashFlow.household_id == hid)).all()
    events = db.scalars(select(ScheduledEvent).where(ScheduledEvent.household_id == hid)).all()

    sums = {v: 0.0 for v in ASSET_FIELD.values()}
    unpledged_brokerage = 0.0
    for x in assets:
        amt = _fx(x.amount, x.currency, reporting, rates, missing)
        if x.kind in ASSET_FIELD:
            sums[ASSET_FIELD[x.kind]] += amt
            if x.kind == "brokerage" and not x.pledged_to_sbl:
                unpledged_brokerage += amt
        elif x.kind == "private_fund_commitment":
            pass  # illiquid; its cash impact enters through scheduled capital calls
        else:
            warnings.append(f"Asset '{x.name}' of kind '{x.kind}' is not modelled as a liquidity source.")
    if unpledged_brokerage > 0:
        warnings.append("The engine treats all brokerage as SBL collateral; unpledged brokerage "
                        f"({unpledged_brokerage:,.0f} {reporting}) is modelled as pledged (conservative).")

    sbl = sum(_fx(x.balance, x.currency, reporting, rates, missing) for x in liabilities if x.kind == "sbl")
    other_debt = sum(_fx(x.monthly_payment or Decimal(0), x.currency, reporting, rates, missing)
                     for x in liabilities if x.kind != "sbl")
    if any(x.kind != "sbl" and not x.monthly_payment for x in liabilities):
        warnings.append("Some non-SBL liabilities have no monthly payment; they add no debt service.")

    flow = lambda kind: sum(_fx(x.monthly_amount, x.currency, reporting, rates, missing)  # noqa: E731
                            for x in flows if x.kind == kind)
    capital_calls, vests, scheduled = [], [], []
    reit_requests: list[tuple[int, float]] = []
    interval_target = 0.0
    for e in events:
        amt = _fx(e.amount, e.currency, reporting, rates, missing)
        if e.month > a.horizon_months:
            warnings.append(f"Event '{e.label or e.kind}' in month {e.month} is beyond the horizon and ignored.")
            continue
        if e.kind == "capital_call":
            capital_calls.append(CapitalCall(month=e.month, amount=amt))
        elif e.kind == "rsu_vest":
            due = min(max(e.tax_due_month or e.month, e.month), a.horizon_months)
            vests.append(RsuVest(month=e.month, value_prestress=amt, tax_due_month=due))
        elif e.kind == "tax_payment":
            scheduled.append(ScheduledFlow(month=e.month, amount=amt, category="tax", label=e.label or "Tax"))
        elif e.kind == "other_outflow":
            scheduled.append(ScheduledFlow(month=e.month, amount=amt, category="outflow", label=e.label or ""))
        elif e.kind == "other_inflow":
            scheduled.append(ScheduledFlow(month=e.month, amount=amt, category="inflow", label=e.label or ""))
        elif e.kind == "reit_redemption_request":
            reit_requests.append((e.month, amt))
        elif e.kind == "interval_redemption_request":
            interval_target += amt
    if len({m for m, _ in reit_requests}) > 1:
        warnings.append("Multiple REIT request months were combined: the engine submits the total from the earliest "
                        "month and resubmits unfilled amounts monthly.")
    if missing:
        raise ApiError(422, "unprocessable", "Missing FX rates for: " + ", ".join(sorted(missing))
                       + f". Add them to the scenario's fx_rates (units of {reporting} per unit).",
                       details={"missing_currencies": sorted(missing)})

    engine_fields = {k: v for k, v in a.model_dump().items()
                     if k not in ("fx_rates", "assumption_sources", "as_of_date")}
    scenario = Scenario(
        **engine_fields, **sums,
        monthly_income=flow("income"), monthly_core_expenses=flow("core_expense"),
        monthly_discretionary=flow("discretionary_expense"), other_debt_service_monthly=other_debt,
        sbl_loan_balance=sbl, capital_calls=capital_calls, rsu_vests=vests, scheduled_flows=scheduled,
        reit_redemption_target=sum(x for _, x in reit_requests),
        reit_request_start_month=min((m for m, _ in reit_requests), default=1),
        interval_redemption_target=interval_target, start_calendar_month=household.start_calendar_month,
    )

    as_of = a.as_of_date or date.today()
    household_terms = approved_constraints(db, hid, as_of)
    library_terms, library_warnings = library_constraints(db, list(assets), as_of)
    warnings += library_warnings + _bucket_warnings(list(assets))
    approved = household_terms + library_terms
    try:
        terms = terms_from_constraints([to_engine_constraint(c, name) for c, name in approved])
    except TermConflictError as exc:
        raise ApiError(409, "term_conflict",
                       f"{exc}. Approved terms disagree, so no value is chosen automatically. Reject or edit the "
                       "clause that does not apply. If a newer library document replaces an older one, mark the "
                       "newer term as superseding the older one in the Fund Library. Then run again.",
                       details={"conflicts": exc.conflicts, "as_of_date": as_of.isoformat()}) from None
    for ex in terms.excluded_unsupported:
        warnings.append(f"Approved {ex['type']} term ({ex['document']} p.{ex['pdf_page']}) was NOT used: its evidence "
                        f"does not support it ({', '.join(ex['reasons'])}). Edit or reject it on the Terms page.")
    by_id = {str(c.id): c for c, _ in approved}
    for fname, ids in terms.applied.items():
        vague = [by_id[i] for i in ids if i in by_id and by_id[i].ambiguous]
        if vague:
            warnings.append(f"'{fname}' rests on a clause flagged as ambiguous and approved by a reviewer "
                            f"(p.{', p.'.join(str(c.pdf_page) for c in vague)}); treat the result as dependent on "
                            "that reading.")
    pending = pending_simulator_terms(db, hid, list(assets))
    if pending:
        warnings.append(f"{pending} extracted term(s) that would set simulator inputs are still awaiting review and "
                        "were not used; approve or reject them on the Terms page.")
    sbl_rates = [x.annual_rate for x in liabilities if x.kind == "sbl" and x.annual_rate is not None]
    if sbl_rates and terms.provenance["sbl_interest_rate"].startswith("default"):
        terms.sbl_interest_rate = float(sbl_rates[0])
        terms.provenance["sbl_interest_rate"] = "household liability record (user-provided)"
    for term, prov in terms.provenance.items():
        if prov.startswith("default"):
            warnings.append(f"No approved contract clause for '{term}'; using default modelling value "
                            f"{getattr(terms, term)} (assumption, not a contract fact).")
    if sbl > 0 and sums["brokerage"] <= 0:
        warnings.append("An SBL balance exists but no brokerage collateral is recorded.")

    snapshot = {
        "reporting_currency": reporting, "fx_rates": rates,
        "assets": [{"id": str(x.id), "kind": x.kind, "name": x.name, "amount": str(x.amount), "currency": x.currency,
                    "pledged_to_sbl": x.pledged_to_sbl, "fund_id": str(x.fund_id) if x.fund_id else None}
                   for x in assets],
        "liabilities": [{"id": str(x.id), "kind": x.kind, "name": x.name, "balance": str(x.balance),
                         "currency": x.currency, "monthly_payment": str(x.monthly_payment or 0)} for x in liabilities],
        "cash_flows": [{"id": str(x.id), "kind": x.kind, "name": x.name, "monthly_amount": str(x.monthly_amount),
                        "currency": x.currency} for x in flows],
        "events": [{"id": str(x.id), "kind": x.kind, "month": x.month, "amount": str(x.amount), "currency": x.currency,
                    "tax_due_month": x.tax_due_month, "label": x.label} for x in events],
    }
    snapshot["as_of_date"] = as_of.isoformat()
    versions = [{"id": str(c.id), "revision": c.revision, "type": c.constraint_type, "asset_key": c.asset_key,
                 "value": None if c.value is None else str(c.value), "document": name, "pdf_page": c.pdf_page,
                 "owner": "fund" if c.fund_id else "household", "fund_id": str(c.fund_id) if c.fund_id else None,
                 "effective_from": c.effective_from.isoformat() if c.effective_from else None,
                 "effective_to": c.effective_to.isoformat() if c.effective_to else None}
                for c, name in approved]
    return EngineInputs(scenario=scenario, terms=terms, assumptions=a, household_snapshot=snapshot,
                        constraint_versions=versions, warnings=warnings)


def terms_snapshot(terms: ContractTerms) -> dict[str, Any]:
    d = asdict(terms)
    d["relax"] = sorted(terms.relax)
    d["interval_offer_calendar_months"] = list(terms.interval_offer_calendar_months)
    return d


def term_rows(terms_snap: dict[str, Any]) -> list[dict[str, Any]]:
    prov = terms_snap.get("provenance", {})
    derived = set(terms_snap.get("derived") or [])

    def basis(k: str, v: str) -> str:
        if v.startswith("default"):
            return "default_assumption"
        if v.startswith("household"):
            return "household_record"
        if k in derived or v.startswith("derived"):
            return "derived_from_clause"
        return "contract_clause" if re.search(r"\.pdf p\.\d+", v) else "other"
    # Source-backed only when the value itself is stated by an approved clause (not derived or assumed).
    return [{"term": k, "value": terms_snap.get(k), "provenance": v, "basis": basis(k, v),
             "source_backed": basis(k, v) == "contract_clause"} for k, v in prov.items()]
