# SlipSlopes — Contractual Liquidity Intelligence

Hackathon prototype (LPL WealthX). A household can be wealthy on paper and still run out of cash: fund
redemption gates, SBL collateral calls, private-fund capital calls and RSU tax bills tighten together in a
downturn. SlipSlopes reads the contract terms, simulates them month by month, finds the first month cash
runs out, and ranks costed ways to prevent it.

- **AI interprets text** (optional): an LLM extracts liquidity terms from retrieved excerpts as schema-validated JSON.
- **Deterministic Python computes everything else**: cash flows, gates, shortfalls, reverse stress, the prevention plan.
- **Every term carries evidence**: the exact quote, PDF page, printed page and prospectus section. Quotes are checked against the PDF text.
- **The advisor stays in control**: they review, edit or reject terms and assumptions, and decide whether to apply a plan.

> Synthetic household. Prototype only, not financial advice.

## Run it

```bash
uv venv --python 3.11 .venv            # or: python3.11 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt   # or: .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Open http://localhost:8501. Run the tests with `.venv/bin/python -m pytest -q`.

### Demo Mode (no API key)

Demo Mode is the default when `ANTHROPIC_API_KEY` is unset. It:

- runs a deterministic **rule-based extractor** over the real `data/BREIT-Prospectus-with-previous-supplements.pdf` (about 1 s for 607 pages);
- runs the same extractor over four **synthetic sample contracts** that it generates into `data/demo/`. These are an interval fund, an SBL agreement, a private-fund LPA and an RSU grant with an insider-trading policy. Every page is watermarked *SYNTHETIC*.

All quotes in Demo Mode are real text from those PDFs. If the BREIT PDF is missing, the app uses
`data/demo/constraints_snapshot.json`, a saved rule-based extraction of the same PDF, and says so in the UI.

**The BREIT prospectus is not included in this repository.** It is a third-party document. Demo Mode works
without it, using the snapshot. To enable live re-extraction and the full-page evidence viewer for BREIT,
download the prospectus (with supplements) and save it as
`data/BREIT-Prospectus-with-previous-supplements.pdf`, or upload any PDF in the Contract Explorer.
Page numbers in this README refer to the 607-page bundle dated through Supplement No. 6 (Sept 16, 2026).

### Live LLM extraction

```bash
cp .env.example .env   # set ANTHROPIC_API_KEY=...
```

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Enables "Extract with LLM" in the Contract Explorer |
| `SLIPSLOPES_LLM_MODEL` | `claude-opus-5-5` | Extraction model |
| `SLIPSLOPES_LLM_EFFORT` | `medium` | `low` / `medium` / `high` |
| `SLIPSLOPES_LLM_FALLBACKS` | `1` | Server-side refusal fallback (`0` to disable) |

How a PDF goes through the pipeline:

1. **Parse.** The PDF is read page by page with PyMuPDF, detecting printed page labels and prospectus sections.
2. **Retrieve.** A keyword search picks the top excerpts (8 by default), and repeated boilerplate is de-duplicated. The full document is never sent.
3. **Extract.** One Messages API call with `output_config.format` JSON-schema output.
4. **Validate.** The result is checked with Pydantic. Malformed or invalid output gets exactly one retry.
5. **Verify.** Each quote is checked verbatim against the cited page. Unverified quotes are flagged *low confidence / needs review*.
6. **Guard qualitative clauses.** Pro-rata, board-discretion, resubmission and trading-window clauses can never carry a numeric value.

If there's no key, or the API call fails, the UI shows the reason. The rule-based extractor and Demo Mode keep working.

## What the app shows

| Page | Contents |
|---|---|
| **Portfolio Overview** | Paper value, stress-usable liquidity, first shortfall month and amount, naive-vs-contract-aware cash chart, composition |
| **Contract Explorer** | Upload PDFs; table of extracted terms (editable value and review status); evidence inspector with the quote, page/section and full-page text; the simulator terms with provenance |
| **Stress Simulation** | All scenario inputs (each labelled synthetic or assumption); monthly ledger for either model, with the constraints that bound each month |
| **Reverse Stress Test** | Mildest failing equity drawdown; counterfactual attribution by contract rule; month-by-month events |
| **Prevention Planner** | Single actions ranked by cost; an LP-optimised combination verified by re-simulation; option to apply it to the scenario |
| **Export** | Constraints (CSV/JSON), monthly results (CSV), full results bundle (JSON) |

The sidebar has **Reset Demo Scenario**, which restores the seeded inputs and the extracted constraints.

## Seeded demo: what is sourced and what is assumed

**From the BREIT prospectus** (PDF p.53 = Supplement No. 5, Aug 17 2026, printed p.39; p.103 = printed p.89):

- 2% of aggregate NAV per month and 5% per calendar quarter, with both limits assessed each month;
- pro-rata fulfilment;
- board discretion to repurchase fewer shares or none;
- unfilled requests must be resubmitted;
- 98% repurchase price if held under one year;
- settlement within three business days.

**From the synthetic contracts:**

- interval fund: 5% quarterly offers in Mar/Jun/Sep/Dec, 2% fee;
- SBL: 50% advance rate, 60% maintenance LTV, 3-day cure, 7.25% interest;
- LPA: 10-business-day notice, calls at the GP's discretion;
- RSUs: 22% withholding (37% maximum election), trading windows only.

**Synthetic household:**

- holdings: $600K brokerage (pledged), $500K REIT, $300K interval fund, $150K vested RSUs, $250K cash, for $1.80M in total;
- $300K SBL balance;
- $35K/month net income against $45K/month spending;
- a $250K capital call in month 4;
- a $300K RSU vest in month 2, with the tax true-up due in month 4.

**Scenario assumptions** (editable, labelled in the UI; no document supports these):

- a 25% equity drawdown over 3 months;
- asset betas;
- aggregate REIT redemption demand of 1.5% of NAV/month, plus 50 points per 100% drawdown (14% at the trough);
- the board fills 100% of the cap;
- interval-fund tender demand;
- a 47% effective tax rate on RSU income;
- the household keeps 3 months of spending in cash while an RSU window is open.

**Simulator results with these inputs:**

| Measure | Result |
|---|---|
| Naive comparator | no shortfall |
| Contract-aware model | first shortfall in **Month 4 (April): −$71,872** |
| Stress-usable liquidity (first 3 months) | $527K (vs $1.25M under the naive haircuts) |
| Reverse stress | fails from a **16.7%** drawdown (the SBL maintenance call triggers there) |
| Prevention plan | about $2.7K of assumed cost: raise RSU withholding to the 37% maximum and file a REIT repurchase request before the stress; verified by re-simulation |

*Note on the presentation figure.* The deck quotes $410K of stress-usable liquidity. With these inputs the
simulator computes $527K. The difference is the $117.5K of vested RSUs that can be sold in the February
trading window; excluding them gives $409.6K. The app reports $527K and shows the breakdown. The shortfall
happens anyway because the RSU window is closed in April, when the cash is needed.

The ideation submission mentions BREIT's 2023 fill rates (15–35%). No source for that figure was supplied,
so the app does not display it. Fill rates in the simulator come only from the labelled demand assumption.

## Method notes

- **Naive baseline.** A deliberately simplified comparator, not a model of any commercial tool. Fixed liquid fractions (brokerage 90%, REIT/interval 70%, RSUs 85%) can be sold instantly. It ignores gates, lags, collateral calls, trading windows and the withholding gap.
- **REIT gate.** Fund-level capacity each month is the smaller of the monthly cap and the quarter's remaining cap. When aggregate demand exceeds capacity, every request is filled pro rata (capacity ÷ demand). Unfilled amounts are resubmitted, and proceeds settle the following month.
- **Reverse stress.** A 1% grid over drawdowns of 0–60%, then bisection to 0.05%. The app reports whether pass/fail was monotone on the grid; if it wasn't, the result is labelled as the first failing point, not an exact boundary.
- **Prevention planner.** Single actions use bisection on the simulator. The combined plan uses `scipy.optimize.linprog` (HiGHS) on per-month cash sensitivities measured by finite differences, iterated (sequential LP) and pruned. It is always re-simulated. If a single action is cheaper than the LP's local solution, the app reports that action and labels it. Costs are editable assumptions, not market quotes.

## Layout

```
app.py                     Streamlit UI
src/document_parser.py     PDF -> pages (pdf page, printed page, section)
src/retrieval.py           keyword excerpt retrieval + de-duplication
src/llm_service.py         Anthropic client, schema-constrained JSON
src/constraint_extractor.py rule-based + LLM extraction, quote verification
src/schemas.py             Pydantic constraint schema + enums
src/synthetic_docs.py      generates the SYNTHETIC sample contract PDFs
src/simulator.py           24-month naive and contract-aware models
src/reverse_stress.py      boundary search + counterfactual attribution
src/optimizer.py           ranked options + sequential LP
src/demo_data.py           seeded scenario, demo loading, snapshot
src/export.py              CSV / JSON export
tests/                     pytest suite (incl. headless Streamlit smoke tests)
```
