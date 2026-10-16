# SlipSlopes data

Contract documents and client-finance data used to develop and evaluate contract extraction and the
liquidity simulation. `manifest.csv` is the index of every file; `evaluation/dataset_report.md` is the
generated quality report.

## Layout

```
data/
├── README.md, manifest.csv            tracked
├── schemas/                           tracked: contract_rule, client_profile JSON Schemas
├── raw/                               NOT tracked (git-ignored); originals, never modified
│   ├── contracts/real/                public filings (BREIT, two Lord Abbett interval funds, UBS credit line, Parkway LPA)
│   ├── contracts/synthetic/           SYNTHETIC sample contracts (copies of backend/app/engine/fixtures)
│   ├── client_finance/                synthetic personal-finance dataset; sample transactions and budget
│   └── reference/                     pitch deck, ideation form (personal details), LPL investor deck
├── interim/                           NOT tracked; regenerable
│   ├── extracted_text/<document_id>/  pages.jsonl (per PDF page), full_text.txt, summary.json
│   └── normalized_finance/            normalised CSVs (+ derived_* columns), column provenance, quality profile
├── processed/                         tracked (small)
│   ├── contract_clauses/              <id>.candidates.jsonl (for review) and <id>.auto_rules.jsonl (unverified)
│   ├── client_profiles/               demo_client_001.json (provenance on every value)
│   └── scenarios/                     demo_stress_25pct.json (assumptions)
├── labels/                            tracked: evaluation_cases.jsonl (real docs), extraction_examples.jsonl (synthetic docs)
├── evaluation/                        tracked: expected_rules.jsonl, quote_checks.json, dataset_report.md
└── BREIT-Prospectus-with-previous-supplements.pdf -> raw/contracts/real/...   compatibility symlink for the backend's default path
```

## Rules for this data

- **Real vs synthetic.** `source_type` in the manifest is `real_public`, `synthetic` (watermarked sample contracts),
  `synthetic_dataset` (the personal-finance CSV), `project_internal` or `unknown`. Synthetic material is never
  evidence about a real product or client.
- **Rules are not payouts.** A redemption limit is a fund-level maximum; fills depend on aggregate demand and
  board discretion. `value_kind` records whether a number is a maximum, minimum, exact value, range or qualitative.
- **Verification states.** `unverified` (automatic output) → `quote_matched` (clause found verbatim on the page) →
  `source_checked` (value and conditions read against the page) → `human_verified` (signed off by a named person).
  Nothing here is `human_verified` yet.
- **Provenance of client values.** Every client-profile input is `{value, source, basis}` with source
  `source_dataset`, `derived` or `synthetic_assumption`. The finance dataset has no assets, holdings, RSUs or
  monthly history; those are assumptions.
- **Licensing.** Download URLs, the Kaggle dataset identifier and licenses are recorded only where known (see the
  manifest). Confirm them before sharing raw files. Raw files are git-ignored.

## Regenerate

```bash
.venv/bin/python scripts/prepare_data.py          # runs the four steps below in order
.venv/bin/python scripts/prepare_contract_data.py # page text, OCR assessment, candidates, unverified auto rules
.venv/bin/python scripts/prepare_finance_data.py  # finance profiles, normalised CSVs, demo client, scenario
.venv/bin/python scripts/build_evaluation_set.py  # re-check curated quotes, emit evaluation/expected_rules.jsonl
.venv/bin/python scripts/build_dataset_report.py  # evaluation/dataset_report.md
```

Requires the backend virtual environment (PyMuPDF, pandas, jsonschema) because the contract step reuses
`backend/app/engine` (page labels, section detection, rule-based extractor). No LLM is called.

## Adding a document

1. Copy the original into `raw/contracts/real/` (or `synthetic/`) without renaming it.
2. Add a manifest row with a new stable `document_id`, the source URL if known, and `extraction_status=pending`.
3. Run `scripts/prepare_contract_data.py --only <document_id>` and review the candidates.
4. Add evaluation cases only after reading the clause in the source, then run `scripts/build_evaluation_set.py`.
