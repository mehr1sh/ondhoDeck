"""Bridge between persisted household data and the deterministic engine.

Household balances and scheduled obligations come from the database; modelling assumptions come
from the scenario; contract terms come only from *approved* extracted constraints. Anything the
engine falls back to (e.g. a default 2% cap with no approved clause) is reported as a warning so it
is never mistaken for a sourced contract fact.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
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
from ..engine.simulator import CapitalCall, ContractTerms, RsuVest, Scenario, ScheduledFlow, terms_from_constraints
from ..errors import ApiError
from ..models import (
    Asset,
    CashFlow,
    Document,
    ExtractedConstraint,
    Household,
    Liability,
    ScenarioDefinition,
    ScheduledEvent,
)

APPROVED = ("confirmed", "edited")
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


def approved_constraints(db: Session, household_id: uuid.UUID) -> list[tuple[ExtractedConstraint, str]]:
    rows = db.execute(
        select(ExtractedConstraint, Document.safe_filename)
        .join(Document, Document.id == ExtractedConstraint.document_id)
        .where(ExtractedConstraint.household_id == household_id, ExtractedConstraint.review_status.in_(APPROVED),
               Document.status != "deleted")
        .order_by(ExtractedConstraint.created_at)
    ).all()
    return [(r[0], r[1]) for r in rows]


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
        original_value=f(c.original_value))


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

    engine_fields = {k: v for k, v in a.model_dump().items() if k not in ("fx_rates", "assumption_sources")}
    scenario = Scenario(
        **engine_fields, **sums,
        monthly_income=flow("income"), monthly_core_expenses=flow("core_expense"),
        monthly_discretionary=flow("discretionary_expense"), other_debt_service_monthly=other_debt,
        sbl_loan_balance=sbl, capital_calls=capital_calls, rsu_vests=vests, scheduled_flows=scheduled,
        reit_redemption_target=sum(x for _, x in reit_requests),
        reit_request_start_month=min((m for m, _ in reit_requests), default=1),
        interval_redemption_target=interval_target, start_calendar_month=household.start_calendar_month,
    )

    approved = approved_constraints(db, hid)
    terms = terms_from_constraints([to_engine_constraint(c, name) for c, name in approved])
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
                    "pledged_to_sbl": x.pledged_to_sbl} for x in assets],
        "liabilities": [{"id": str(x.id), "kind": x.kind, "name": x.name, "balance": str(x.balance),
                         "currency": x.currency, "monthly_payment": str(x.monthly_payment or 0)} for x in liabilities],
        "cash_flows": [{"id": str(x.id), "kind": x.kind, "name": x.name, "monthly_amount": str(x.monthly_amount),
                        "currency": x.currency} for x in flows],
        "events": [{"id": str(x.id), "kind": x.kind, "month": x.month, "amount": str(x.amount), "currency": x.currency,
                    "tax_due_month": x.tax_due_month, "label": x.label} for x in events],
    }
    versions = [{"id": str(c.id), "revision": c.revision, "type": c.constraint_type, "asset_key": c.asset_key,
                 "value": None if c.value is None else str(c.value), "document": name, "pdf_page": c.pdf_page}
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
    # Source-backed only when the provenance cites a document page of an approved constraint.
    return [{"term": k, "value": terms_snap.get(k), "provenance": v,
             "source_backed": bool(re.search(r"\.pdf p\.\d+", v)) and not v.startswith(("default", "household"))}
            for k, v in prov.items()]
