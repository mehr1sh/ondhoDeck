# OndhoDeck: baseline, BYOK, contract extraction and liquidity explanation report

Report from the baseline phase (2026-10-16). Counts and results below were measured at that point; later
work (fund library, blind-spot detection, page-specific evidence checks) is described in the README and
[FUND_LIBRARY.md](FUND_LIBRARY.md). Nothing was deployed.
OndhoDeck is positioned as a liquidity-risk layer that can sit alongside portfolio platforms such as
Cyan. No comparison with Cyan was made and none is claimed.

## What was implemented

| Phase | Result |
|---|---|
| 0–1 Audit, runnable | Local stack runs (Postgres, Redis, auth on gateway port 54331 to avoid a port clash, API, worker, frontend build). |
| 2 Provider abstraction | `backend/app/llm/`: common interface (`extract_json`, `test_connection`, `list_models`, usage, latency), Anthropic and OpenAI adapters with schema-constrained JSON output, normalised error codes (`invalid_key`, `quota_exceeded`, `rate_limited`, `model_not_found`, `truncated`, `refusal`, …). Provider error text is never echoed. |
| 3 BYOK | Per-user keys encrypted at rest (Fernet, rotation via `CREDENTIALS_ENCRYPTION_KEYS`, ciphertext bound to user and provider). Endpoints under `/me/ai-providers` (list, save + test, test, live model list, update, delete) plus `/me/ai-providers-events`. Keys are never returned, logged, audited or put in Celery payloads (the job id is the only task argument; the worker decrypts in memory). Without an encryption key, storage is refused (503) — keys are never stored unencrypted. Table has RLS enabled and no `anon`/`authenticated` grants. UI: Settings → AI providers. |
| 4 Extraction baseline | Retrieval of bounded excerpts → schema-constrained LLM output → Pydantic validation with one bounded retry → verbatim quote verification on the cited page → contract validation → `needs_review`. Only reviewer-approved constraints reach the simulator (unchanged rule). Document text is delimited, escaped and treated as untrusted; the system prompt forbids following instructions inside it. Resolution order per job: user's active key → server provider → rule-based; the job records `credential_source`. |
| 5 Contract families | Common schema gained `value_kind`, `exceptions`, `discretion`, `effective_period`, `ambiguous`, `validation_issues` and six new types (suspension, notice period, capital commitment, demand repayment, vesting, termination). Contract checks: number must appear in the quote; percent/duration ranges; caps must be `maximum` (a cap is never a payout rate); cross-rule checks; discretion/condition language flags ambiguity. |
| 6 Client profiles | `data/processed/client_profiles/dataset_client_U20388.json` contains only the 19 fields of one record of the synthetic personal-finance dataset and lists what it lacks. `synthetic_hnw_household.json` is the fully synthetic demo household. They are not mixed. |
| 7 Simulator explanation | Each run stores an explanation: first shortfall month and amount, constraints binding then, counterfactual contribution of each contract rule linked to approved clause evidence (document, page, quote) or labelled as a default assumption, and material assumptions by perturbation. Scenario presets (including REIT board fills half / suspended) are labelled as assumptions. |
| 8 Prevention | Existing ranked, verified prevention plan unchanged and re-verified end to end. Nothing is executed automatically. |
| 9 Advisor UI | New: AI provider settings with key activity, extraction method on documents and jobs, constraint value kind / exceptions / discretion / ambiguity / validation warnings (view and edit), "Why this result" panel, scenario preset picker. Household audit trail was already on household settings. |
| 10 Evaluation | `scripts/evaluate_extraction.py` → `data/evaluation/extraction_eval_report.{md,json}` (see below). |
| 11 Fine-tuning | Not run. See `data/evaluation/fine_tuning_feasibility.md`. |

## Measured results

**Tests (run 2026-10-16):**
- Backend: `ruff check app tests scripts` clean, `mypy app` clean (51 files), `pytest` 106 passed.
- Frontend: typecheck clean, lint clean, Vitest 71 passed (14 files), production build succeeded (13 pages).
- Live end-to-end (`backend/scripts/e2e_local.py` with the real BREIT prospectus): **53/53 checks passed**,
  including the BYOK status and validation checks, `credential_source`, run explanation and preset run.

**Extraction evaluation** against 19 source-checked reference rules (pending human sign-off; not model
output) on 5 real public documents:

| | All documents | Held-out (excl. BREIT) |
|---|---|---|
| Rule-based: detected with correct type | 6/19 | **0/13** |
| Rule-based: citation verbatim on cited page (of detected) | 6/6 | n/a |
| Rule-based: unsupported predictions | 0 | 0 |
| Retrieval recall at 8 excerpts (LLM ceiling) | 18/19 | 13/13 |

The rule-based extractor only works on the document its patterns were written for. Retrieval does put
every held-out reference clause in front of the model, but **no LLM extraction was evaluated**: no provider
key was available, so LLM accuracy, latency and cost are unknown. To run it:
`EVAL_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=… .venv/bin/python scripts/evaluate_extraction.py`
(or `openai` with `OPENAI_API_KEY` and `EVAL_LLM_MODEL`).

## Not verified / limitations

- No call to a real Anthropic or OpenAI API was made. Adapters are tested with fake SDK clients only
  (request shape, parsing, error mapping). Live key validation, model listing and LLM extraction are untested.
- New UI screens are verified by component tests (mocked API) and the build, not in a browser session.
- Evaluation set is small (19 rules), labels await human sign-off, and the retrieval vocabulary was extended
  while the set existed. No RSU agreement exists in the data.
- Explanations are counterfactuals of the deterministic model, not causal claims about markets or advice.
- `CREDENTIALS_ENCRYPTION_KEYS` must be identical on API and worker; losing it makes stored keys
  unreadable (users are told to replace them). Re-encryption after rotation happens when keys are re-saved.
- Pre-existing: `backend/alembic/env.py` fails ruff's import ordering when linted directly; CI does not lint it.

## Commands

```bash
# backend
cd backend && ../.venv/bin/alembic upgrade head
../.venv/bin/ruff check app tests scripts && ../.venv/bin/mypy app && ../.venv/bin/python -m pytest -q
../.venv/bin/python scripts/e2e_local.py /abs/path/to/BREIT-Prospectus-with-previous-supplements.pdf
# frontend
cd frontend && pnpm typecheck && pnpm lint && pnpm test && pnpm build
# data
.venv/bin/python scripts/prepare_finance_data.py
.venv/bin/python scripts/evaluate_extraction.py
```

## New environment variables

`CREDENTIALS_ENCRYPTION_KEYS` (server-only; enables BYOK), `RATE_LIMIT_PROVIDER_TESTS_PER_10MIN`,
`OPENAI_API_KEY`, `OPENAI_MODEL`, and `LLM_PROVIDER` now accepts `openai`. Documented in
`backend/.env.example`, `docs/DEPLOYMENT.md`, `docs/LOCAL_DEVELOPMENT.md` and `render.yaml` (`sync: false`).
Evaluation only: `EVAL_LLM_PROVIDER`, `EVAL_LLM_MODEL`.

## Migration

`backend/alembic/versions/20261016_c3d9e2b7a4f1_byok_credentials_constraint_evidence_.py`
(upgrade → downgrade → upgrade verified locally).
