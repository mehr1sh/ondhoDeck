#!/usr/bin/env python3
"""Profile and normalise the client-finance CSVs, and build a provenance-tagged demo client profile.

Inputs (never modified): the client_finance rows of data/manifest.csv.
Outputs:
  data/interim/normalized_finance/<document_id>.normalized.csv   original columns + derived_* columns
  data/interim/normalized_finance/<document_id>.columns.json     provenance of every output column
  data/interim/normalized_finance/finance_profile.json           data-quality profile used by the report
  data/processed/client_profiles/demo_client_001.json            demo client (schema: data/schemas/client_profile.schema.json)
  data/processed/client_profiles/dataset_client_<user_id>.json   ONLY the fields present in the dataset record
  data/processed/client_profiles/synthetic_hnw_household.json    fully synthetic HNW household (the app's seeded demo)
  data/processed/scenarios/demo_stress_25pct.json                stress assumptions (all synthetic_assumption)

The personal-finance dataset is SYNTHETIC and individual-level (one record per user, no monthly history).
No time series is invented from it, and no credit model is trained.

    .venv/bin/python scripts/prepare_finance_data.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "interim" / "normalized_finance"


def manifest_rows() -> dict[str, dict]:
    with (DATA / "manifest.csv").open(newline="") as fh:
        return {r["document_id"]: r for r in csv.DictReader(fh) if r["data_category"] == "client_finance"}


def profile(df: pd.DataFrame, name: str) -> dict:
    numeric = df.select_dtypes("number")
    return {
        "file": name, "rows": int(df.shape[0]), "columns": int(df.shape[1]),
        "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        "missing": {c: int(v) for c, v in df.isna().sum().items() if v},
        "duplicate_rows": int(df.duplicated().sum()),
        "numeric_ranges": {c: {"min": float(numeric[c].min()), "median": float(numeric[c].median()),
                               "max": float(numeric[c].max())} for c in numeric.columns},
    }


def personal_finance(df: pd.DataFrame) -> tuple[pd.DataFrame, dict, list[str]]:
    checks: list[str] = []
    n = len(df)
    no_loan = df["has_loan"].eq("No")
    checks.append(f"loan_type missing in {int(df['loan_type'].isna().sum())} rows; has_loan == 'No' in {int(no_loan.sum())} rows; "
                  f"missing loan_type where has_loan == 'Yes': {int((df['loan_type'].isna() & ~no_loan).sum())}")
    checks.append(f"rows with has_loan == 'No' but loan_amount_usd > 0: {int((no_loan & df['loan_amount_usd'].gt(0)).sum())}")
    checks.append(f"rows with monthly_expenses_usd > monthly_income_usd: {int(df['monthly_expenses_usd'].gt(df['monthly_income_usd']).sum())} of {n}")
    checks.append(f"rows with monthly_emi_usd > monthly_income_usd: {int(df['monthly_emi_usd'].gt(df['monthly_income_usd']).sum())}")
    recomputed_dti = (df["monthly_emi_usd"] / df["monthly_income_usd"]).round(2)
    checks.append(f"debt_to_income_ratio differs from round(monthly_emi_usd / monthly_income_usd, 2) by > 0.01 in "
                  f"{int((recomputed_dti - df['debt_to_income_ratio']).abs().gt(0.011).sum())} rows "
                  f"(the dataset's definition of this ratio is undocumented)")
    recomputed_sti = (df["savings_usd"] / (12 * df["monthly_income_usd"])).round(2)
    checks.append(f"savings_to_income_ratio matches round(savings_usd / (12 * monthly_income_usd), 2) - i.e. savings over "
                  f"ANNUAL income - in {int((recomputed_sti - df['savings_to_income_ratio']).abs().le(0.011).sum())} of {n} rows")
    emi_ratio = df["monthly_emi_usd"] / df["monthly_income_usd"]
    checks.append(f"SUSPICIOUS: monthly_emi_usd exceeds monthly_income_usd in {int(emi_ratio.gt(1).sum())} rows "
                  f"(median EMI/income among them {emi_ratio[emi_ratio.gt(1)].median():.2f}); implausible for real borrowers")
    checks.append(f"credit_score range {int(df['credit_score'].min())}-{int(df['credit_score'].max())}; "
                  f"age range {int(df['age'].min())}-{int(df['age'].max())}")
    dates = pd.to_datetime(df["record_date"], errors="coerce")
    checks.append(f"record_date unparseable: {int(dates.isna().sum())}; range {dates.min().date()} to {dates.max().date()} "
                  f"(one record per user_id: {df['user_id'].is_unique})")
    out = df.copy()
    out["derived_has_loan"] = df["has_loan"].map({"Yes": True, "No": False})
    out["derived_loan_type"] = df["loan_type"].where(df["loan_type"].notna(), df["has_loan"].map({"No": "none"}))
    out["derived_record_date"] = dates.dt.date.astype("string")
    out["derived_monthly_surplus_usd"] = (df["monthly_income_usd"] - df["monthly_expenses_usd"] - df["monthly_emi_usd"]).round(2)
    cols = {c: "source_dataset" for c in df.columns}
    cols.update({"derived_has_loan": "derived: has_loan Yes/No -> boolean",
                 "derived_loan_type": "derived: loan_type, or 'none' where has_loan == 'No'",
                 "derived_record_date": "derived: record_date parsed as ISO date",
                 "derived_monthly_surplus_usd": "derived: monthly_income_usd - monthly_expenses_usd - monthly_emi_usd "
                                                "(assumes expenses exclude loan payments - undocumented)"})
    return out, cols, checks


def transactions(df: pd.DataFrame) -> tuple[pd.DataFrame, dict, list[str]]:
    out = df.copy()
    dates = pd.to_datetime(df["Date"], format="%m/%d/%Y", errors="coerce")
    sign = df["Transaction Type"].map({"debit": -1, "credit": 1})
    out["derived_date"] = dates.dt.date.astype("string")
    out["derived_month"] = dates.dt.to_period("M").astype("string")
    out["derived_signed_amount"] = (df["Amount"] * sign).round(2)
    checks = [f"date range {dates.min().date()} to {dates.max().date()}; unparseable dates: {int(dates.isna().sum())}",
              f"transaction types: {df['Transaction Type'].value_counts().to_dict()}",
              f"accounts: {sorted(df['Account Name'].unique().tolist())}",
              f"non-positive amounts: {int(df['Amount'].le(0).sum())}",
              "Credit-card payments appear as transactions; monthly sums mix spending with transfers between accounts."]
    cols = {c: "source_dataset" for c in df.columns}
    cols.update({"derived_date": "derived: Date (MM/DD/YYYY) as ISO", "derived_month": "derived: calendar month of Date",
                 "derived_signed_amount": "derived: Amount, negative for debits"})
    return out, cols, checks


def budget(df: pd.DataFrame) -> tuple[pd.DataFrame, dict, list[str]]:
    return df.copy(), {c: "source_dataset" for c in df.columns}, [
        f"total monthly budget {int(df['Budget'].sum())} across {len(df)} categories (currency not stated)"]


def demo_client(pf: pd.DataFrame) -> dict:
    """Base household flows from ONE synthetic dataset record; everything the dataset lacks is a labelled assumption."""
    # Deterministic selection: the highest monthly income among employed users with no loan.
    pool = pf[(pf["employment_status"] == "Employed") & (pf["has_loan"] == "No")]
    row = pool.sort_values(["monthly_income_usd", "user_id"], ascending=[False, True]).iloc[0]
    rid = row["user_id"]

    def v(value, source, basis):
        return {"value": value, "source": source, "basis": basis}

    def sa(value, basis):
        return v(value, "synthetic_assumption", basis)

    return {
        "profile_id": "demo_client_001",
        "description": "Demo high-net-worth client for liquidity stress testing. NOT a real client. "
                       "Monthly flows come from one record of a synthetic dataset; all holdings, obligations and "
                       "contract links are synthetic assumptions.",
        "currency": "USD",
        "source_record": {"document_id": "finance_personal_001", "user_id": rid,
                          "selection_rule": "highest monthly_income_usd among employment_status == 'Employed' and has_loan == 'No'"},
        "starting_cash": sa(250000, "Demo household value used by the SlipSlopes engine; the dataset has no cash balance "
                                    "(savings_usd is not split by asset type)."),
        "monthly_income": v(round(float(row["monthly_income_usd"]), 2), "source_dataset", f"monthly_income_usd of {rid}"),
        "monthly_expenses": v(round(float(row["monthly_expenses_usd"]), 2), "source_dataset", f"monthly_expenses_usd of {rid}"),
        "reported_savings": v(round(float(row["savings_usd"]), 2), "source_dataset",
                              f"savings_usd of {rid}; composition (cash vs investments) unknown"),
        "liquid_investments": sa(600000, "Taxable brokerage (pledged to the SBL); not present in the dataset."),
        "restricted_fund_holdings": [
            {"name": "Non-traded REIT", "amount": sa(500000, "Demo holding"), "linked_document_ids": ["contract_breit_001"]},
            {"name": "Interval fund", "amount": sa(300000, "Demo holding"),
             "linked_document_ids": ["contract_interval_001", "contract_interval_synthetic_001"]},
        ],
        "private_equity_commitments": [{
            "name": "Private fund commitment", "unfunded_commitment": sa(400000, "Demo commitment"),
            "expected_capital_calls": [{"month": 4, "amount": sa(250000, "Call timing/amount are at GP discretion "
                                                                          "(contract_lpa_001 Section 4.2(b)); schedule is assumed")}],
            "linked_document_ids": ["contract_lpa_001", "contract_lpa_synthetic_001"]}],
        "securities_backed_credit": {
            "balance": sa(300000, "Demo loan balance"), "collateral_value": sa(600000, "Pledged brokerage"),
            "linked_document_ids": ["contract_sbloc_001", "contract_sbloc_synthetic_001"],
            "notes": "The real UBS agreement states no numeric maintenance level; the synthetic agreement's 50%/60% are illustrative."},
        "rsu_grants": [{"vested_value": sa(150000, "Demo vested RSUs"),
                        "vests": [{"month": 2, "value": sa(300000, "Demo vest"), "tax_due_month": sa(4, "April true-up")}],
                        "linked_document_ids": ["contract_rsu_synthetic_001"],
                        "notes": "No real RSU agreement is available (contract_rsu_001 missing)."}],
        "one_off_obligations": [],
        "stress_scenario_ids": ["demo_stress_25pct"],
    }


DATASET_FIELDS = ["age", "gender", "education_level", "employment_status", "job_title", "monthly_income_usd",
                  "monthly_expenses_usd", "savings_usd", "has_loan", "loan_type", "loan_amount_usd", "loan_term_months",
                  "monthly_emi_usd", "loan_interest_rate_pct", "debt_to_income_ratio", "credit_score",
                  "savings_to_income_ratio", "region", "record_date"]


def dataset_client(pf: pd.DataFrame, user_id: str) -> dict:
    """Exactly one dataset record, field for field. Nothing is added, inferred or scaled."""
    row = pf[pf["user_id"] == user_id].iloc[0]

    def clean(x):
        if pd.isna(x):
            return None
        return x.item() if hasattr(x, "item") else x
    return {
        "profile_id": f"dataset_client_{user_id}",
        "description": "One record of a SYNTHETIC personal-finance dataset (source and license unknown). Not a real "
                       "client. Contains only the fields present in that record.",
        "source_record": {"document_id": "finance_personal_001", "user_id": user_id},
        "fields": {f: {"value": clean(row[f]), "source": "source_dataset", "column": f} for f in DATASET_FIELDS},
        "not_in_source": ["cash balance", "asset allocation of savings_usd", "brokerage holdings",
                          "non-traded REIT / interval fund holdings", "private fund commitments",
                          "securities-backed credit line", "RSU grants", "tax position", "monthly history"],
        "usage_note": "Insufficient on its own for a contract-aware liquidity simulation: it has no holdings in "
                      "illiquid or contract-constrained assets. Use it for base monthly flows only, and label any "
                      "added holdings as synthetic assumptions (see demo_client_001.json).",
    }


def synthetic_hnw_household() -> dict:
    """The seeded SlipSlopes demo household, from the engine's Scenario defaults. Every value is synthetic."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.engine.demo_data import SCENARIO_NOTES
    from app.engine.simulator import Scenario
    return {
        "profile_id": "synthetic_hnw_household",
        "description": "Fully SYNTHETIC high-net-worth household used by the SlipSlopes demo. No value comes from "
                       "the Kaggle/personal-finance dataset or from any real client.",
        "source": "synthetic_assumption",
        "generated_from": "backend/app/engine/simulator.py Scenario() defaults",
        "provenance_notes": SCENARIO_NOTES,
        "scenario_inputs": Scenario().model_dump(mode="json"),
    }


CLIENT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "slipslopes/client_profile.schema.json",
    "title": "SlipSlopes demo client profile",
    "description": "Every monetary or timing input is a {value, source, basis} object so its provenance is explicit.",
    "type": "object",
    "required": ["profile_id", "description", "currency", "starting_cash", "monthly_income", "monthly_expenses",
                 "liquid_investments", "restricted_fund_holdings", "private_equity_commitments",
                 "securities_backed_credit", "rsu_grants", "one_off_obligations", "stress_scenario_ids"],
    "$defs": {"sourced": {"type": "object", "required": ["value", "source", "basis"], "additionalProperties": False,
                          "properties": {"value": {"type": ["number", "string", "boolean"]},
                                         "source": {"enum": ["source_dataset", "derived", "synthetic_assumption"]},
                                         "basis": {"type": "string", "minLength": 1}}}},
    "properties": {
        "profile_id": {"type": "string"}, "description": {"type": "string"}, "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
        "source_record": {"type": "object"},
        "starting_cash": {"$ref": "#/$defs/sourced"}, "monthly_income": {"$ref": "#/$defs/sourced"},
        "monthly_expenses": {"$ref": "#/$defs/sourced"}, "reported_savings": {"$ref": "#/$defs/sourced"},
        "liquid_investments": {"$ref": "#/$defs/sourced"},
        "restricted_fund_holdings": {"type": "array", "items": {"type": "object", "required": ["name", "amount"],
                                     "properties": {"amount": {"$ref": "#/$defs/sourced"}}}},
        "private_equity_commitments": {"type": "array"}, "securities_backed_credit": {"type": "object"},
        "rsu_grants": {"type": "array"}, "one_off_obligations": {"type": "array"},
        "stress_scenario_ids": {"type": "array", "items": {"type": "string"}},
    },
}

SCENARIO = {
    "scenario_id": "demo_stress_25pct",
    "description": "2022-style equity drawdown. Every value is a modelling assumption, not a contract term or historical fact.",
    "source": "synthetic_assumption",
    "horizon_months": 24,
    "assumptions": {"equity_drawdown": 0.25, "months_to_trough": 3, "trough_hold_months": 9, "recovery_share": 0.5,
                    "reit_base_demand_pct": 1.5, "reit_demand_sensitivity": 50.0, "reit_board_fill_factor": 1.0,
                    "interval_base_demand_pct": 3.0, "interval_demand_sensitivity": 40.0,
                    "rsu_effective_tax_rate": 0.47},
    "notes": "Matches the defaults of backend/app/api_schemas.py ScenarioAssumptions. Redemption demand and board fill "
             "are assumptions: no supplied document discloses future fill rates.",
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    handlers = {"finance_personal_001": personal_finance, "finance_transactions_001": transactions, "finance_budget_001": budget}
    report: dict = {}
    pf_norm = None
    for doc_id, row in manifest_rows().items():
        path = ROOT / row["relative_path"]
        df = pd.read_csv(path)
        prof = profile(df, row["filename"])
        norm, cols, checks = handlers[doc_id](df)
        prof["checks"] = checks
        prof["license_source_status"] = "unknown - no README, license or dataset identifier was found with the file"
        norm.to_csv(OUT / f"{doc_id}.normalized.csv", index=False)
        (OUT / f"{doc_id}.columns.json").write_text(json.dumps(cols, indent=2))
        report[doc_id] = prof
        if doc_id == "finance_personal_001":
            pf_norm = df
        print(f"{doc_id:26s} {prof['rows']:6d} x {prof['columns']:2d}  missing={sum(prof['missing'].values())}  dup={prof['duplicate_rows']}")
    (OUT / "finance_profile.json").write_text(json.dumps(report, indent=2))

    schemas = DATA / "schemas"
    (schemas / "client_profile.schema.json").write_text(json.dumps(CLIENT_SCHEMA, indent=2))
    client = demo_client(pf_norm)
    jsonschema.validate(client, CLIENT_SCHEMA)
    (DATA / "processed" / "client_profiles" / "demo_client_001.json").write_text(json.dumps(client, indent=2))
    (DATA / "processed" / "scenarios" / "demo_stress_25pct.json").write_text(json.dumps(SCENARIO, indent=2))
    uid = client["source_record"]["user_id"]
    profiles = DATA / "processed" / "client_profiles"
    (profiles / f"dataset_client_{uid}.json").write_text(json.dumps(dataset_client(pf_norm, uid), indent=2))
    (profiles / "synthetic_hnw_household.json").write_text(json.dumps(synthetic_hnw_household(), indent=2))
    print(f"demo client built from synthetic record {client['source_record']['user_id']} (schema-valid)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
