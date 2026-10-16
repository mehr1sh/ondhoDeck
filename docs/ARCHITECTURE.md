# OndhoDeck architecture

```
 Browser (Next.js on Vercel)
   │  Supabase Auth (sign-up, login, recovery) ── session JWT
   │  REST calls with  Authorization: Bearer <access token>
   ▼
 FastAPI web service (Render) ──────────────── PostgreSQL (Supabase)
   │  verifies JWT (JWKS / HS256)                 tables + RLS policies, Alembic migrations
   │  household membership checks
   │  validated uploads ─────────────────────── Supabase Storage (private bucket, service role)
   │  enqueue job ──▶ Render Key Value (Redis) ──▶ Celery worker (Render)
   │                                              parse → OCR → retrieve → extract → verify → persist
   │                                              exports: CSV / JSON / PDF
   ▼
 Deterministic engine (backend/app/engine): simulator, reverse stress, prevention optimizer
```

## Responsibilities

| Layer | Does | Never does |
|---|---|---|
| LLM provider (optional) | Proposes structured terms from bounded, page-tagged excerpts | Calculate balances, decide shortfalls, choose actions |
| Rule-based extractor | Deterministic extraction of known clause families (used when no LLM is configured) | Invent values for clauses it does not match |
| Evidence verification | Checks each quote against the cited page text; unverified → low confidence, needs review | Accept unverified quotes silently |
| Reviewer (user) | Edits, approves or rejects each constraint; every change is a revision | — |
| Engine | Monthly cash accounting, fund-level gates, SBL calls, RSU windows/tax, reverse stress, LP prevention | Use unapproved constraints |
| API | Authentication, authorization, validation, persistence, audit | Trust browser-supplied user ids |

## Key modelling rules

- **Fund-level REIT gate.** The 2% monthly and 5% quarterly caps limit *total* repurchases across all investors.
  Capacity each month = min(monthly cap, quarter cap − already used this quarter). A household's fill is
  pro rata: capacity ÷ aggregate demand. Aggregate demand and the board's discretionary fill are **scenario
  assumptions**, shown and editable as such. The cap is never applied as a guaranteed per-household allocation.
- **Approved terms only.** Simulations use constraints with review status `confirmed` or `edited`. Any
  term without an approved clause falls back to a labelled default, and the run lists a warning per term.
- **Reproducibility.** Every run stores the scenario assumptions, a household snapshot, the contract terms
  with provenance, the approved constraint ids and revisions, and the engine version. Monthly rows for both
  models are stored.
- **Currencies.** Records keep their original currency. Runs convert to the household's reporting currency
  using scenario FX rates; a missing rate stops the run with a clear error.
- **Prevention.** Single actions are sized by bisection on the simulator. The combined plan is a linear
  programme (`scipy.optimize.linprog`, HiGHS) over simulator-measured sensitivities, iterated and pruned, then
  re-simulated. If the cheapest verified single action beats the LP's local solution, that is reported and
  labelled. Recommendations must be approved before they can be applied to a new scenario.

## Database schema (PostgreSQL)

All ids are UUIDs. Timestamps are `timestamptz`. Money is `numeric(18,2)` with an ISO currency column.

| Table | Purpose | Key constraints |
|---|---|---|
| `profiles` | One row per auth identity (`id` = JWT `sub`) | PK = auth user id |
| `households` | A client household; reporting currency, start month | currency format, month 1–12 |
| `household_members` | Ownership/membership: `owner` / `editor` / `viewer` | unique (household, user) |
| `assets` | Cash, brokerage (pledged flag), non-traded REIT, interval fund, private fund commitment, vested RSU | amount ≥ 0, kind enum |
| `liabilities` | SBL, mortgage, other loans; rate, monthly payment | balance ≥ 0 |
| `cash_flows` | Recurring monthly income / core / discretionary expenses | amount ≥ 0 |
| `scheduled_events` | Capital calls, RSU vests (+ tax due month), tax payments, other flows, redemption requests | month 1–120 |
| `documents` | Upload metadata, storage path, status, OCR stats, demo-fixture flag | unique live (household, sha256) |
| `document_pages` | Extracted text per PDF page, printed page, prospectus section, OCR flag | unique (document, page) |
| `processing_jobs` | Queue jobs: status, attempt/max, stage, progress, provider/model, errors, stats | unique idempotency key; one active job per document |
| `extracted_constraints` | Typed term, value/bounds/unit/timing/conditions, evidence quote, PDF/printed page, verification, review status, provider/model, revision | unique (document, extraction key) |
| `constraint_revisions` | Every review change: diff, full snapshot, note, author | unique (constraint, revision) |
| `scenarios` | Named assumption sets (validated JSON) | — |
| `simulation_runs` | Inputs, household snapshot, terms + provenance, constraint versions, engine version, summaries, warnings | unique (household, idempotency key) |
| `simulation_months` | Monthly rows for `naive` and `contract_aware` | unique (run, model, month) |
| `stress_results` | Search parameters and grid, boundary, first failure, attribution, key events | — |
| `prevention_plans` / `prevention_recommendations` | Costs, verification, ranked single and combined actions, approval status | unique (plan, kind, rank) |
| `exports` | Requested exports, status, storage path | kind/status enums |
| `chat_conversations`, `chat_messages` | Assistant conversations (author, optional household) and their messages with provider, model and token usage | role enum; RLS on, no browser grants |
| `audit_events` | Append-only record of changes (ids, field names, statuses only) | indexed by household, time |

Migrations: `backend/alembic/versions/` (initial schema, row-level security).

## Row-level security

The API connects as the table owner and enforces authorization in code. RLS is defense in depth for data
reachable through Supabase's auto-generated APIs: `authenticated` users can only **read** rows of households
they belong to (via `public.is_household_member`, a `SECURITY DEFINER` helper); `anon` has no access; there
are no insert/update/delete policies, so direct writes are denied. These policies are exercised in
`backend/tests/api/test_records_exports_security.py`.

## Security notes

- Secrets only in environment variables; the service-role key is used only by the backend.
- CORS allows only configured origins (`*` is rejected at startup).
- Uploads: size limit, PDF signature, parse check, no encrypted PDFs, page limit, sanitised file names,
  stored only in a private bucket; downloads use short-lived signed URLs.
- Expensive endpoints are rate-limited per user. Errors never include tracebacks; responses carry a
  request id. Logs record method, path, status and latency only, with token/key redaction.
- Retention: deleting a document removes the stored file, page text and its constraints immediately; a
  minimal audit record remains. Deleting a household or account removes its stored files.

These controls are reasonable engineering safeguards for a prototype; they are not a certification of
regulatory compliance.
