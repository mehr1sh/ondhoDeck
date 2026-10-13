"""Export generation (CSV / JSON / PDF report), executed by the worker and stored privately."""
from __future__ import annotations

import csv
import html
import io
import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pymupdf
from sqlalchemy import select

from ..db import session_scope
from ..models import (
    Document,
    ExportRecord,
    ExtractedConstraint,
    Household,
    PreventionPlan,
    ScenarioDefinition,
    SimulationMonth,
    SimulationRun,
    StressResult,
)
from ..storage import get_storage
from .engine_adapter import term_rows

log = logging.getLogger("slipslopes.exports")

CONSTRAINT_FIELDS = ["id", "document_name", "document_section", "pdf_page", "printed_page", "constraint_type",
                     "asset_key", "description", "value", "lower_bound", "upper_bound", "original_value", "unit",
                     "timing", "conditions", "evidence_quote", "quote_verified", "interpretation", "confidence",
                     "source_type", "review_status", "revision", "extraction_method", "provider", "model"]
MONTH_FIELDS = ["model", "month", "label", "beginning_cash", "income", "expenses", "taxes", "debt_service",
                "collateral_call", "capital_call", "redemption_requested", "redemption_proceeds", "other_proceeds",
                "ending_cash", "shortfall", "reit_fill_rate", "binding_constraints"]
DISCLAIMER = ("Prototype analysis for advisor review - not financial advice. Values labelled as assumptions are "
              "modelling inputs, not contract terms.")


def _plain(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def constraint_rows(db, household_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.execute(select(ExtractedConstraint, Document.safe_filename)
                      .join(Document, Document.id == ExtractedConstraint.document_id)
                      .where(ExtractedConstraint.household_id == household_id, Document.status != "deleted")
                      .order_by(Document.safe_filename, ExtractedConstraint.pdf_page)).all()
    out = []
    for c, name in rows:
        d = {f: _plain(getattr(c, f, None)) for f in CONSTRAINT_FIELDS if f != "document_name"}
        d["document_name"] = name
        out.append({f: d.get(f) for f in CONSTRAINT_FIELDS})
    return out


def month_rows(db, run_id: uuid.UUID) -> list[dict[str, Any]]:
    months = db.scalars(select(SimulationMonth).where(SimulationMonth.run_id == run_id)
                        .order_by(SimulationMonth.model.desc(), SimulationMonth.month)).all()
    return [{f: (" | ".join(m.binding_constraints) if f == "binding_constraints" else _plain(getattr(m, f)))
             for f in MONTH_FIELDS} for m in months]


def _csv(rows: list[dict[str, Any]], fields: list[str]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for r in rows:
        # Neutralise spreadsheet formula injection in free-text cells.
        w.writerow({k: ("'" + v if isinstance(v, str) and v[:1] in "=+-@" and not _is_number(v) else v)
                    for k, v in r.items()})
    return buf.getvalue().encode("utf-8")


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def results_bundle(db, run: SimulationRun) -> dict[str, Any]:
    scenario = db.get(ScenarioDefinition, run.scenario_id)
    stress = db.scalars(select(StressResult).where(StressResult.scenario_id == run.scenario_id)
                        .order_by(StressResult.created_at.desc())).first()
    plan = db.scalars(select(PreventionPlan).where(PreventionPlan.scenario_id == run.scenario_id)
                      .order_by(PreventionPlan.created_at.desc())).first()
    return {
        "generated_at": datetime.now(UTC).isoformat(), "disclaimer": DISCLAIMER,
        "run": {"id": str(run.id), "created_at": run.created_at.isoformat(), "engine_version": run.engine_version,
                "reporting_currency": run.reporting_currency, "horizon_months": run.horizon_months,
                "naive_summary": run.naive_summary, "contract_aware_summary": run.aware_summary,
                "stress_usable_liquidity": run.liquidity, "warnings": run.warnings},
        "scenario": {"id": str(scenario.id), "name": scenario.name, "assumptions": run.inputs_snapshot},
        "household_snapshot": run.household_snapshot,
        "contract_terms": term_rows(run.terms_snapshot),
        "approved_constraint_versions": run.constraint_versions,
        "monthly": month_rows(db, run.id),
        "latest_reverse_stress": None if stress is None else {
            "id": str(stress.id), "found": stress.found, "boundary_drawdown": _plain(stress.boundary_drawdown),
            "first_shortfall_month": stress.first_shortfall_month, "shortfall_amount": _plain(stress.shortfall_amount),
            "grid_monotone": stress.grid_monotone, "method": stress.method, "attribution": stress.attribution},
        "latest_prevention_plan": None if plan is None else {
            "id": str(plan.id), "combined_cost": _plain(plan.combined_cost), "verified": plan.combined_verified,
            "source": plan.combined_source, "cost_assumptions": plan.cost_assumptions,
            "recommendations": [{"rank": r.rank, "kind": r.kind, "name": r.name, "amount": _plain(r.amount),
                                 "unit": r.unit, "cost": _plain(r.cost), "status": r.status}
                                for r in plan.recommendations]},
    }


def _money(v: Any, ccy: str) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "-"
    return f"{'−' if x < 0 else ''}{ccy} {abs(x):,.0f}"


def report_pdf(bundle: dict[str, Any], household_name: str) -> bytes:
    ccy = bundle["run"]["reporting_currency"]
    run, aw, nv = bundle["run"], bundle["run"]["contract_aware_summary"], bundle["run"]["naive_summary"]
    e = html.escape
    first = lambda s: f"Month {s['first_shortfall_month']}" if s["first_shortfall_month"] else "None"  # noqa: E731
    months = [m for m in bundle["monthly"] if m["model"] == "contract_aware"]
    rows = "".join(
        f"<tr><td>{e(m['label'])}</td><td>{_money(m['beginning_cash'], ccy)}</td><td>{_money(m['capital_call'], ccy)}"
        f"</td><td>{_money(m['collateral_call'], ccy)}</td><td>{_money(m['taxes'], ccy)}</td>"
        f"<td>{_money(m['redemption_proceeds'], ccy)}</td><td>{_money(m['ending_cash'], ccy)}</td></tr>"
        for m in months)
    terms = "".join(f"<tr><td>{e(t['term'])}</td><td>{e(str(t['value']))}</td><td>{e(t['provenance'])}</td></tr>"
                    for t in bundle["contract_terms"])
    warns = "".join(f"<li>{e(w)}</li>" for w in run["warnings"]) or "<li>None</li>"
    doc_html = f"""
    <h1>SlipSlopes liquidity report</h1>
    <p><b>Household:</b> {e(household_name)} &nbsp; <b>Scenario:</b> {e(bundle['scenario']['name'])}<br/>
    <b>Run:</b> {e(run['id'])} &nbsp; <b>Engine:</b> {e(run['engine_version'])} &nbsp;
    <b>Generated:</b> {e(bundle['generated_at'][:19])} UTC</p>
    <h2>Summary</h2>
    <table><tr><th></th><th>Naive baseline</th><th>Contract-aware</th></tr>
    <tr><td>First shortfall</td><td>{first(nv)}</td><td>{first(aw)}</td></tr>
    <tr><td>Shortfall in that month</td><td>{_money(nv['shortfall_amount'], ccy)}</td>
        <td>{_money(aw['shortfall_amount'], ccy)}</td></tr>
    <tr><td>Minimum month-end cash</td><td>{_money(nv['min_cash'], ccy)}</td><td>{_money(aw['min_cash'], ccy)}</td></tr>
    </table>
    <p>Stress-usable liquidity (first {run['stress_usable_liquidity'].get('window_months')} months):
    {_money(run['stress_usable_liquidity'].get('total'), ccy)}</p>
    <h2>Warnings</h2><ul>{warns}</ul>
    <h2>Contract-aware monthly cash</h2>
    <table><tr><th>Month</th><th>Begin</th><th>Capital call</th><th>Collateral call</th><th>Taxes</th>
    <th>Fund proceeds</th><th>End</th></tr>{rows}</table>
    <h2>Contract terms used</h2>
    <table><tr><th>Term</th><th>Value</th><th>Provenance</th></tr>{terms}</table>
    <p><i>{e(DISCLAIMER)}</i></p>"""
    css = ("* {font-family: sans-serif; font-size: 9pt;} h1 {font-size: 16pt;} h2 {font-size: 12pt;} "
           "table {border-collapse: collapse;} td, th {border: 0.5px solid #999; padding: 2px 4px;}")
    out = io.BytesIO()
    writer = pymupdf.DocumentWriter(out)
    story = pymupdf.Story(html=doc_html, user_css=css)
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (36, 36, -36, -36)
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return out.getvalue()


def build_export(export_id: uuid.UUID) -> str:
    with session_scope() as db:
        rec = db.get(ExportRecord, export_id)
        if rec is None or rec.status not in ("queued", "failed"):
            return "skipped"
        rec.status = "running"
    try:
        with session_scope() as db:
            rec = db.get(ExportRecord, export_id)
            if rec is None:
                return "skipped"
            household = db.get(Household, rec.household_id)
            if household is None:
                raise ValueError("The household no longer exists.")
            run = db.get(SimulationRun, rec.run_id) if rec.run_id else None
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            if rec.kind == "constraints_csv":
                data = _csv(constraint_rows(db, rec.household_id), CONSTRAINT_FIELDS)
                name, ctype = "constraints.csv", "text/csv"
            elif rec.kind == "constraints_json":
                data = json.dumps(constraint_rows(db, rec.household_id), indent=2).encode()
                name, ctype = "constraints.json", "application/json"
            elif run is None:
                raise ValueError("This export requires a simulation run.")
            elif rec.kind == "simulation_csv":
                data, name, ctype = _csv(month_rows(db, run.id), MONTH_FIELDS), "simulation.csv", "text/csv"
            elif rec.kind == "results_json":
                data = json.dumps(results_bundle(db, run), indent=2, default=str).encode()
                name, ctype = "results.json", "application/json"
            else:
                data, name, ctype = report_pdf(results_bundle(db, run), household.name), "report.pdf", "application/pdf"
            path = f"{rec.household_id}/exports/{rec.id}/{stamp}-{name}"
            get_storage().put(path, data, ctype)
            rec.status, rec.storage_path, rec.filename = "ready", path, f"slipslopes-{stamp}-{name}"
            rec.size_bytes, rec.completed_at, rec.error_message = len(data), datetime.now(UTC), None
        return "ready"
    except Exception as exc:
        log.warning("export %s failed: %s", export_id, type(exc).__name__)
        with session_scope() as db:
            failed = db.get(ExportRecord, export_id)
            if failed is None:
                return "failed"
            failed.status = "failed"
            failed.error_message = str(exc)[:400] if isinstance(exc, ValueError) else "Export generation failed."
        return "failed"
