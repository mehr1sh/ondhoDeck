# OndhoDeck — Contractual Liquidity Intelligence

Hackathon prototype (LPL WealthX). A household can be wealthy on paper and still run out of cash: fund
redemption gates, SBL collateral calls, private-fund capital calls and RSU tax bills tighten together in a
downturn. OndhoDeck reads the contract terms, simulates them month by month, finds the first month cash
runs out, and ranks costed ways to prevent it.

- **AI interprets text** (optional): an LLM extracts liquidity terms from retrieved excerpts as schema-validated JSON.
- **Deterministic Python computes everything else**: cash flows, gates, shortfalls, reverse stress, the prevention plan.
- **Every term carries evidence**: the exact quote, PDF page, printed page and prospectus section. Quotes are checked against the PDF text.
- **The advisor stays in control**: they review, edit or reject terms and assumptions, and decide whether to apply a plan.

> Real public contract documents; synthetic household. Prototype only, not financial advice.

## Full-stack application

The advisor application is a FastAPI backend with a Celery worker and a Next.js frontend; the original
Streamlit prototype (`app.py`, below) shares the same calculation engine in `backend/app/engine/`.

| Part | Where | What it does |
|---|---|---|
| API | `backend/app` (FastAPI, SQLAlchemy, Alembic) | Households, documents, terms review, simulations, fund library, reports |
| Worker | `backend/app/worker.py` (Celery + Redis) | PDF parsing/OCR, term extraction, PDF report generation |
| Engine | `backend/app/engine` | Deterministic simulator, reverse stress, prevention planner, extraction and evidence validation |
| Frontend | `frontend` (Next.js 15, TypeScript, Tailwind) | Advisor workspace: Overview, Households, Fund Library, Documents, Review Queue, Liquidity Scenarios, Reports, Settings |
| Auth/DB | Supabase Auth + PostgreSQL (local: `docker-compose.yml`) | Accounts, row-level security |

**Set up and run locally:** [docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md) (services, migrations, API,
worker, auth gateway, frontend, browser tests). Configuration templates contain placeholders only:
`backend/.env.example` and `frontend/.env.example`. Deployment: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

**Checks** (the same commands CI runs):

```bash
cd backend && ruff check app tests scripts && mypy app && pytest          # uses the separate slipslopes_test database
cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

**Anthropic / OpenAI keys (BYOK).** Each advisor can store their own key under Settings → AI providers. Keys
are encrypted at rest (`CREDENTIALS_ENCRYPTION_KEYS`), never returned by the API or logged, and used only by
the worker. Anthropic keys that are not scoped to a workspace also need the workspace ID (`wrkspc_...`).
Extraction uses the requester's active key, otherwise a server key, otherwise the rule-based extractor; every
job records which (`extraction_method`, `provider`, `model`, `credential_source`), including failed attempts.

**Extraction, review and simulation.**

1. Upload a PDF (household agreement, or a public offering document into the Fund Library).
2. Terms are extracted with a verbatim evidence quote. A quote counts as verified only on the page it cites;
   unsupported numbers, units or limit wording are flagged, and related clauses of the same type are
   cross-referenced rather than merged.
3. An advisor approves, edits or rejects each term. Approval re-checks the quote against the cited page; a term
   whose extracted value the quote does not support must be edited (it becomes a reviewer-confirmed value) or
   rejected.
4. Simulations use only approved, evidence-supported terms; this is enforced inside the engine. Disagreeing
   approved terms block the run instead of one silently winning. Qualitative restrictions (board discretion,
   suspension, resubmission) are listed as unmodelled risks, never given an invented numerical effect.
5. Each run records the term versions it used; its explanation cites only the clauses the engine applied and
   labels derived interpretations (e.g. settlement timing → a one-month cash lag) and default assumptions.

**Known limitations.** One non-traded REIT and one interval-fund allocation per household; library terms are
resolved at the projection start date; fill rates depend on a labelled demand assumption; the LLM extraction
benchmark has not been run against the reference set (see `data/evaluation/extraction_eval_report.md`).
More detail: [docs/FUND_LIBRARY.md](docs/FUND_LIBRARY.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Streamlit prototype (`app.py`)

```bash
uv venv --python 3.11 .venv            # or: python3.11 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt   # or: .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Open http://localhost:8501. Run the tests with `.venv/bin/python -m pytest -q`.

### Demo Mode (no API key)

Demo Mode is the default when `ANTHROPIC_API_KEY` is unset. It runs a deterministic **rule-based
extractor** over seven real, public documents. Every contract term in the demo is a verbatim quote from one
of them, with its PDF page:

| Asset | Document | Source file → save as |
|---|---|---|
| Non-traded REIT | Blackstone Real Estate Income Trust prospectus with supplements No. 1–6 (through Sept 16, 2026) | [breit.com/prospectus](https://www.breit.com/prospectus) → `data/BREIT-Prospectus-with-previous-supplements.pdf` |
| Interval fund | Franklin BSP Lending Fund prospectus, April 30, 2026 | [franklintempleton.com, doc 47536-P](https://www.franklintempleton.com/forms-literature/download-preview/47536-P) → `data/sources/47536-P.pdf` |
| Securities-backed line | Bank of America pledge agreement amendment (Kanders SAF, LLC), Sept 25, 2026: SEC Exhibit 99.2 to a Cadre Holdings 13D/A | [EDGAR](https://www.sec.gov/Archives/edgar/data/1860543/000110465926112476/tm2626642d1_ex99-2.htm) → `data/sources/tm2626642d1_ex99-2.htm` |
| Private fund | Andalusian Credit Company, LLC agreement, Dec 21, 2023: SEC Exhibit 3.3 to Form 10-12G/A | [EDGAR](https://www.sec.gov/Archives/edgar/data/1979306/000110465923128803/tm2333334d1_ex3-3.htm) → `data/sources/tm2333334d1_ex3-3.htm` |
| RSU withholding | IRS Publication 15 (Circular E), 2026 | [irs.gov](https://www.irs.gov/pub/irs-pdf/p15.pdf) → `data/sources/p15.pdf` |
| RSU withholding | Meta 2025 Equity Incentive Plan RSU award agreement: SEC Exhibit 10.1 to 10-Q, Q1 2026 | [EDGAR](https://www.sec.gov/Archives/edgar/data/1326801/000162828026028526/meta03312026-ex101.htm) → `data/sources/meta03312026-ex101.htm` |
| RSU trading windows | Meta Insider Trading Policy (amended Sept 5, 2024): SEC Exhibit 19.1 to FY2024 10-K | [EDGAR](https://www.sec.gov/Archives/edgar/data/1326801/000132680125000017/meta-12312024x10kexhibit191.htm) → `data/sources/meta-12312024x10kexhibit191.htm` |

**The documents are not included in this repository** (they are third-party documents). Download them in a
browser and save them under the names above; breit.com and sec.gov block scripted downloads without a
declared contact. HTML filings are rendered to PDF locally (`data/<name>.pdf`) so the same parse → extract → cite
pipeline applies to them.

**Reproducibility.** Each document is pinned by its URL and a fingerprint of its extracted text (the pinning
helper and its golden-number test are not included in this repository yet). A text fingerprint is used rather than a file checksum because EDGAR injects a different
script tag into every download; the text, and therefore the extracted terms, do not change. If a
document's text differs from the pinned version (for example a newer prospectus edition), the app re-extracts
from it and says so. If a document is missing, the app uses its saved extraction in `backend/app/engine/fixtures/snapshots/`
and says so, so the demo gives the same numbers on any machine. Page numbers in this README refer to the 607-page BREIT bundle dated through Supplement
No. 6 (Sept 16, 2026).

### Live LLM extraction

```bash
cp .env.example .env   # set ANTHROPIC_API_KEY=...
```

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Enables "Extract with LLM" in the Contract Explorer |
| `ONDHODECK_LLM_MODEL` | `claude-opus-5-5` | Extraction model |
| `ONDHODECK_LLM_EFFORT` | `medium` | `low` / `medium` / `high` |
| `ONDHODECK_LLM_FALLBACKS` | `1` | Server-side refusal fallback (`0` to disable) |

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

**From the Franklin BSP Lending Fund prospectus** (PDF p.22 = printed p.13; p.98 = printed p.89): the fund
intends to repurchase 5% of outstanding shares quarterly, in March, June, September and December;
oversubscribed offers are prorated; a 2.00% early repurchase fee applies within about a year of purchase;
payment no later than seven calendar days after the Repurchase Pricing Date.

**From the Bank of America pledge agreement** (PDF p.4–5): equities have a 70% Advance Percentage and a 75%
Margin Call Percentage; the pledgor has two business days after notice to cure; otherwise the bank may sell
collateral without further notice. The agreement does not state the interest rate, so 7.25% is a labelled
assumption.

**From the Andalusian Credit Company LLC agreement** (PDF p.23, 25): commitments are drawn as needed on not
less than ten Business Days' notice, in amounts at the Company's sole discretion; after a default uncured for
seven Business Days, 25% of the defaulting member's shares may be forfeited.

**From IRS Publication 15** (p.24): supplemental wages are withheld at a flat 22% ("no other percentage
allowed"); amounts over $1 million at 37%. **From Meta's RSU award agreement** (PDF p.3): the Company may
withhold shares up to the maximum statutory withholding amount, at the Committee's discretion. **From Meta's
insider trading policy** (PDF p.6): no trading from the close of each quarter's second month until the
second full trading day after earnings, which makes the open windows mostly Feb, May, Aug and Nov.

Treating RSU vest income as supplemental wages is an interpretation. Pub. 15's flat-rate method allows only
22% on the first $1 million, so the prevention planner's "raise RSU withholding" option depends on the
employer agreeing to withhold more (Meta's agreement allows it at the Committee's discretion). The app labels
it that way.

**Synthetic household:**

- holdings: $600K brokerage (pledged), $500K REIT, $300K interval fund, $150K vested RSUs, $250K cash, for $1.80M in total;
- $420K SBL balance (fully drawn to the 70% advance rate);
- $35K/month net income against $45K/month spending;
- a $250K capital call in month 4;
- a $300K RSU vest in month 2, with the tax true-up due in month 4;
- REIT and interval-fund shares held over one year (no early repurchase deduction or fee).

**Scenario assumptions** (editable, labelled in the UI; no document supports these):

- a 25% equity drawdown over 3 months;
- asset betas;
- aggregate REIT redemption demand of 1.5% of NAV/month, plus 50 points per 100% drawdown (14% at the trough);
- the board fills 100% of the cap;
- interval-fund tender demand;
- a 47% effective tax rate on RSU income;
- the household keeps 3 months of spending in cash while an RSU window is open.

**Simulator results with these inputs** (locked by `tests/test_demo_golden.py`):

| Measure | Result |
|---|---|
| Naive comparator | no shortfall |
| Contract-aware model | first shortfall in **Month 4 (April): −$102,802** |
| Stress-usable liquidity (first 3 months) | $497K (vs $1.25M under the naive haircuts): $250K cash + $234.6K REIT proceeds + $117.5K RSUs sellable in the February window − $105K of SBL collateral calls |
| Reverse stress | fails from a **14.5%** drawdown |
| Prevention plan | about $4.0K of assumed cost: raise RSU withholding by 15 points to 37% and file a REIT repurchase request before the stress; verified by re-simulation |

*Note on the presentation figures.* Earlier figures ($410K of stress-usable liquidity, a −$71,872 shortfall,
a 16.7% reverse-stress boundary) came from the synthetic SBL terms (50% advance, 60% margin call) that the
real Bank of America terms replaced. Excluding the RSUs, stress-usable liquidity is now $379.6K. The shortfall
still happens because the RSU window is closed in April, when the cash is needed.

The ideation submission mentions BREIT's 2023 fill rates (15–35%). No source for that figure was supplied,
so the app does not display it. Fill rates in the simulator come only from the labelled demand assumption.

## Method notes

- **Naive baseline.** A deliberately simplified comparator, not a model of any commercial tool. Fixed liquid fractions (brokerage 90%, REIT/interval 70%, RSUs 85%) can be sold instantly. It ignores gates, lags, collateral calls, trading windows and the withholding gap.
- **REIT gate.** Fund-level capacity each month is the smaller of the monthly cap and the quarter's remaining cap. When aggregate demand exceeds capacity, every request is filled pro rata (capacity ÷ demand). Unfilled amounts are resubmitted, and proceeds settle the following month.
- **Reverse stress.** A 1% grid over drawdowns of 0–60%, then bisection to 0.05%. The app reports whether pass/fail was monotone on the grid; if it wasn't, the result is labelled as the first failing point, not an exact boundary.
- **Prevention planner.** Single actions use bisection on the simulator. The combined plan uses `scipy.optimize.linprog` (HiGHS) on per-month cash sensitivities measured by finite differences, iterated (sequential LP) and pruned. It is always re-simulated. If a single action is cheaper than the LP's local solution, the app reports that action and labels it. Costs are editable assumptions, not market quotes.

## Layout

```
app.py                       Streamlit prototype UI (imports the engine from backend/app/engine)
backend/
  app/                       FastAPI app: routers/, services/, llm/ (provider adapters), models.py, worker.py
  app/engine/                document_parser, retrieval, constraint_extractor, contract_validation,
                             llm_service, schemas, simulator, reverse_stress, optimizer, demo_data,
                             synthetic_docs, export; fixtures/ (synthetic PDFs, extraction snapshots)
  alembic/                   database migrations
  scripts/                   local tooling (dev auth gateway, end-to-end check, fund-library backfill)
  tests/                     pytest: api/ (against the test database) and engine/
frontend/                    Next.js app; src/ (pages, components, lib), e2e/ (Playwright)
data/                        manifest, schemas, labels, evaluation set and reports (raw inputs stay local)
scripts/                     data preparation and extraction evaluation
docs/                        architecture, API, local development, deployment, fund library
tests/                       Streamlit prototype smoke tests
```
