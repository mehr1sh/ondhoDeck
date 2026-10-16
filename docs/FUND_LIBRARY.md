# Shared fund library, term versioning and blind-spot detection

Reference for advisors, reviewers and engineers working on OndhoDeck. It describes what the code does
today; anything not listed here is not implemented.

## Access model

| Concept | Rule |
|---|---|
| Firm | Access boundary of a fund library. Every account gets a personal firm ("My firm") on first sign-in; the migration created one per existing account. |
| Firm roles | **advisor**: read the library, add funds, upload documents, link holdings. **reviewer**: also approve, reject, edit and supersede library terms, set document effective dates, edit fund metadata, delete library documents with no approved terms. **admin**: also manage members and rename the firm. Ranks: advisor < reviewer < admin. |
| Household | Belongs to one firm (`households.firm_id`). Access to a household is still only through household membership; firm members do **not** see each other's households. |
| Private data | Household agreements (credit lines, RSU grants, LPAs), financial records, notes and household-uploaded documents stay household-scoped. Only public offering documents go into the library. |
| Database RLS | Library rows (funds, fund documents, pages, terms, revisions, fund audit events) are readable by members of the fund's firm; the browser roles cannot write. |

Non-members get 404 for library rows (ids cannot be probed). A firm cannot lose its last admin; if the last
admin deletes their account, the longest-standing remaining member becomes admin.

## Data model

- `funds`: canonical record per fund and share class in a firm (name unique per firm and share class,
  case-insensitive), type (`non_traded_reit`, `interval_fund`, `private_fund`, `other`), issuer, ticker,
  SEC CIK, aliases, `metadata_status` (`needs_review` / `verified`), `status` (`active` / `archived`). Funds are
  archived, never deleted, so past runs stay resolvable.
- `documents`, `document_pages`, `processing_jobs`, `extracted_constraints`, `constraint_revisions` have exactly
  one owner: `household_id` **or** `fund_id` (database CHECK). The same upload, OCR, extraction, quote
  verification and review pipeline serves both.
- Library documents: `effective_date`, `supersedes_document_id` (same fund, cycles rejected); one stored copy per
  fund per SHA-256 (identical uploads return the existing document).
- Terms: `effective_from` (inclusive), `effective_to` (exclusive), `superseded_by_id`.
- `assets.fund_id`: a holding of a library fund of the household's firm, of a matching kind
  (REIT -> `non_traded_reit`, interval fund -> `interval_fund`, private fund -> `private_fund_commitment`).

## Review, effective dates and supersession

1. Extracted library terms start as `needs_review`. Only reviewers/admins can approve, reject or edit them.
2. On approval, a term without `effective_from` takes its document's effective date (recorded in the revision).
3. A term applies on date D when it is approved (`confirmed`/`edited`) and `effective_from <= D < effective_to`.
4. Supersession is explicit: `POST /constraints/{new}/supersede` with the older approved term of the same type and
   owner. The older term gets `effective_to = new.effective_from` and `superseded_by_id`; its approval and history
   are kept and it still applies before that date. Nothing is inferred from upload order or document dates alone.
5. A library document with any approved term cannot be deleted; upload the replacement and supersede instead.
6. Every change writes a constraint revision and an audit event (`/funds/{id}/audit-events`).

## Simulation

- Inputs: the household's approved clauses **plus**, for each holding linked to a library fund, that fund's
  approved terms in force on the scenario's `as_of_date` (default: the run date) and matching the fund's type.
- Only approved terms affect results; the engine itself ignores anything else (fail closed).
- Approved terms that agree corroborate each other. Approved terms that disagree for the same simulator input
  block the run with `409 term_conflict`, listing each clause (document, page, value). No value is chosen
  automatically.
- The engine models one REIT allocation and one interval-fund allocation per household. Linking different funds
  of the same type works only if their approved terms agree; unlinked holdings of a linked type are modelled
  with the linked fund's terms (a warning says so).
- Each run stores the as-of date and every term version used (id, revision, owner, effective window), so later
  edits or supersessions never change what a past run used.

## Blind-spot detection

`POST /scenarios/{id}/blind-spots` runs a fixed, documented set of variants on the scenario (baseline, income
interruption for 6 months, unplanned expense of 3 months' spending, REIT repurchases suspended, interval fund
oversubscribed, proceeds delayed one month, severe market drawdown, and a combination). Each variant lists the
inputs it changes. Every variant is simulated with the contract-aware model and a paper-wealth model.

- **Risk**: month-end cash below zero in the contract-aware model.
- **Blind spot**: the paper-wealth view shows no shortfall, or a later one.
- **Ranking**, in order: severity class (critical: shortfall within 6 months and peak deficit >= 1 month of
  spending; high: within 12 months or peak >= 3 months of spending; otherwise moderate); blind spots first;
  earlier first shortfall; larger peak deficit; milder variant first.
- Each risk lists binding constraints in the first shortfall month and the contract rules whose removal would
  reduce the deficit, with approved clause evidence or a "default modelling assumption" label.
- Results are stored (`blind_spot_reports`) and exportable as a PDF (`blind_spot_pdf`).

This is deterministic what-if analysis under stated assumptions. It does not estimate probabilities, is not a
forecast and does not guarantee outcomes.

## Sharing from households

When a household document finishes processing, and the same file (same SHA-256) has now been uploaded to at
least two households of the firm (`MIN_HOUSEHOLDS` in `backend/app/services/library_sharing.py`), it is copied
into the firm's library once. Later uploads of that file are not copied again.

- Only public offering categories (prospectus, supplement, SAI, interval fund, other fund document) are
  eligible. Private agreements (credit lines, RSU grants, LPAs) are never shared, however often they repeat.
- Household documents, terms and approvals are not modified. The library copy's terms start as
  `needs_review` (household approvals are not library approvals); the fund gets a provisional name
  ("<file name> (confirm name)") with `metadata_status = needs_review`.
- Holdings are not linked automatically.
- Demo fixtures are included, so two demo households share the synthetic interval fund policy; the copy keeps
  `is_demo_fixture`.
- Sharing runs after the household document is saved; if it fails, the failure is logged and the household
  document stays processed.

## Backfill

`backend/scripts/backfill_fund_library.py` applies the same copy to documents uploaded earlier (dry run by
default; `--apply` to write; `--include-demo` for synthetic fixtures; `--min-households N` to copy only files
in at least N households, default 1). It never deletes or modifies household records, and holdings are listed
as link candidates but not linked.

## Migrations

- `e5f1a9c2d7b3` firms and shared fund library (creates one firm per existing account; assigns households).
- `f2b8c4d1e6a9` blind-spot reports.

Both downgrades refuse to run while library funds, added firm members or blind-spot PDF exports exist, because
they would destroy that data.
