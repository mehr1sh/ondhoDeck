"""JSON / CSV export of constraints and simulation results."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone

import pandas as pd

from .schemas import ContractConstraint
from .simulator import ContractTerms, Scenario, SimulationResult

CONSTRAINT_EXPORT_FIELDS = [
    "constraint_id", "constraint_type", "asset_key", "description", "value", "lower_bound",
    "upper_bound", "unit", "timing", "conditions", "document_name", "document_section", "pdf_page", "printed_page",
    "evidence_quote", "quote_verified", "interpretation", "confidence", "source_type",
    "review_status", "extraction_method", "original_value",
]

SIMULATION_EXPORT_FIELDS = [
    "month", "label", "beginning_cash", "income", "expenses", "taxes", "debt_service",
    "collateral_call", "capital_call", "reit_proceeds", "interval_proceeds", "ending_cash",
    "shortfall", "binding_constraints",
]


def constraints_frame(constraints: list[ContractConstraint]) -> pd.DataFrame:
    rows = [c.model_dump(mode="json") for c in constraints]
    return pd.DataFrame(rows, columns=CONSTRAINT_EXPORT_FIELDS)


def constraints_csv(constraints: list[ContractConstraint]) -> str:
    return constraints_frame(constraints).to_csv(index=False)


def simulation_frame(res: SimulationResult) -> pd.DataFrame:
    df = res.to_frame()
    df["binding_constraints"] = df["binding_constraints"].apply(lambda b: " | ".join(b))
    for col in SIMULATION_EXPORT_FIELDS:
        if col not in df:
            df[col] = 0.0
    df.insert(0, "model", res.model)
    return df


def simulation_csv(*results: SimulationResult) -> str:
    return pd.concat([simulation_frame(r) for r in results], ignore_index=True).to_csv(index=False)


def results_bundle(scenario: Scenario, terms: ContractTerms, constraints: list[ContractConstraint],
                   naive: SimulationResult, aware: SimulationResult,
                   reverse: dict | None = None, plan: dict | None = None) -> dict:
    def summary(r: SimulationResult) -> dict:
        return {"model": r.model, "first_shortfall_month": r.first_shortfall_month,
                "shortfall_amount": round(r.shortfall_amount, 2),
                "peak_shortfall": round(r.peak_shortfall, 2), "min_cash": round(r.min_cash, 2)}

    terms_d = asdict(terms)
    terms_d["relax"] = sorted(terms.relax)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": ("Prototype output on a synthetic household. Not financial advice. Values marked "
                       "scenario_assumption are modelling inputs, not contract terms."),
        "scenario": scenario.model_dump(mode="json"),
        "contract_terms": terms_d,
        "constraints": [c.model_dump(mode="json") for c in constraints],
        "results": {"naive": summary(naive), "contract_aware": summary(aware)},
        "monthly": {
            "naive": json.loads(simulation_frame(naive).to_json(orient="records")),
            "contract_aware": json.loads(simulation_frame(aware).to_json(orient="records")),
        },
        "reverse_stress": reverse,
        "prevention_plan": plan,
    }


def bundle_json(bundle: dict) -> str:
    return json.dumps(bundle, indent=2, default=str)
