# Extraction evaluation

Generated 2026-10-15T19:31:31+00:00 by `scripts/evaluate_extraction.py` (git f5aeea3 + uncommitted changes).

**Reference labels** are the source-checked rules in `data/evaluation/expected_rules.jsonl` (manually read against the cited page; pending human sign-off). They are not model output. 19 rules across 5 real public documents; the set is small and not exhaustive, so treat rates as indicative only.

Rule-based patterns were written against `contract_breit_001`; the *held-out* rows exclude it.

## rule_based

| Metric | All documents | Held-out only |
|---|---|---|
| Detected with correct type | 6/19 (32%) | 0/13 (0%) |
| Value correct (numeric rules) (of detected) | 4/4 (100%) | n/a |
| Unit correct (of detected) | 4/4 (100%) | n/a |
| Value kind (max/min/exact/...) (of detected) | 6/6 (100%) | n/a |
| Conditions present iff reference has them (of detected) | 4/6 (67%) | n/a |
| Exceptions present iff reference has them (of detected) | 6/6 (100%) | n/a |
| Discretion present iff reference has it (of detected) | 4/6 (67%) | n/a |
| Citation: quote verbatim on cited page (of detected) | 6/6 (100%) | n/a |
| Predictions | 7 | 0 |
| Unsupported (quote not on page) | 0 | 0 |
| Value not in quote | 0 | 0 |
| Unmatched predictions (no reference rule) | 1 | 0 |

Schema-valid output rate: 100%. Total latency: 0.15 s (includes no parsing). Cost: 0 (no model calls).

| Document | Held-out | Detected | Predictions | Latency (s) |
|---|---|---|---|---|
| contract_breit_001 | no | 6/6 | 7 | 0.09 |
| contract_interval_001 | yes | 0/5 | 0 | 0.02 |
| contract_interval_002 | yes | 0/2 | 0 | 0.03 |
| contract_sbloc_001 | yes | 0/3 | 0 | 0.0 |
| contract_lpa_001 | yes | 0/3 | 0 | 0.01 |

Missed reference rules:

- `contract_interval_001:redemption_limit:eval_interval1_01`
- `contract_interval_001:redemption_limit:eval_interval1_02`
- `contract_interval_001:redemption_settlement_timing:eval_interval1_03`
- `contract_interval_001:pro_rata_fulfillment:eval_interval1_04`
- `contract_interval_001:redemption_suspension:eval_interval1_05`
- `contract_interval_002:redemption_limit:eval_interval2_01`
- `contract_interval_002:redemption_settlement_timing:eval_interval2_02`
- `contract_sbloc_001:demand_repayment:eval_sbloc_01`
- `contract_sbloc_001:collateral_maintenance_threshold:eval_sbloc_02`
- `contract_sbloc_001:termination_condition:eval_sbloc_03`
- `contract_lpa_001:capital_call_deadline:eval_lpa_01`
- `contract_lpa_001:capital_commitment:eval_lpa_02`
- `contract_lpa_001:capital_call_default:eval_lpa_03`

## llm

Status: not run: EVAL_LLM_PROVIDER not set to anthropic|openai

## Retrieval recall (LLM path ceiling)

Share of reference clauses contained in the retrieved excerpts sent to the model (deployed default `LLM_MAX_EXCERPTS=8`; about 2,000 characters each). An LLM cannot extract a clause it is not shown. No model calls. Caveat: the retrieval vocabulary (`SEARCH_TERMS`) was extended for these contract families while this dataset existed, so retrieval is not strictly held-out either.

| top_k | All | Held-out | contract_breit_001 | contract_interval_001 | contract_interval_002 | contract_sbloc_001 | contract_lpa_001 |
|---|---|---|---|---|---|---|---|
| 8 | 18/19 | 13/13 | 5/6 | 5/5 | 2/2 | 3/3 | 3/3 |
| 16 | 18/19 | 13/13 | 5/6 | 5/5 | 2/2 | 3/3 | 3/3 |
| 32 | 19/19 | 13/13 | 6/6 | 5/5 | 2/2 | 3/3 | 3/3 |

## Metric definitions

- *Detected*: a prediction of an engine type mapped to the reference type (`TYPE_MAP`) that points at the reference clause (same page, the reference clause text is on the predicted page, or >=50% token overlap with the predicted quote).
- *Conditions/exceptions/discretion*: presence agreement only; wording is not compared.
- *Citation correct*: the predicted evidence quote appears verbatim (whitespace/hyphenation normalised) on the predicted PDF page.
- *Unsupported*: predictions whose quote is not on the cited page, over all predictions.
- *Unmatched*: predictions with no reference rule; the reference set is not exhaustive, so these are not necessarily wrong.
