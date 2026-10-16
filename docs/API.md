# OndhoDeck API (v1)

Base path: `/api/v1`. Interactive OpenAPI docs are served by the API at `/docs` (Swagger UI) and
`/openapi.json`. Request/response models live in `backend/app/api_schemas.py`.

## Conventions

- **Auth:** every endpoint except health/readiness requires `Authorization: Bearer <Supabase access token>`.
  The token is verified server-side (JWKS or HS256). The user id is taken only from the verified token.
- **Authorization:** household data requires membership in that household. Non-members receive `404`.
  Roles: `viewer` (read), `editor` (change data, run analyses), `owner` (also delete the household).
- **Errors:** always `{"error": {"code": str, "message": str, "request_id": str, "details"?: any}}`.
  Codes include `not_authenticated` (401), `token_expired` (401), `invalid_token` (401), `forbidden` (403),
  `not_found` (404), `conflict` (409), `validation_error` (422), `unprocessable` (422), `payload_too_large` (413),
  `unsupported_media_type` (415), `rate_limited` (429, `Retry-After` header), `internal_error` (500).
- **Pagination:** list endpoints accept `limit` (1–100, default 50) and `offset`; they return
  `{items, total, limit, offset}`.
- **Money:** decimals are serialized as JSON strings (e.g. `"250000.00"`); currency is ISO 4217.
- **Idempotency:** `POST /documents/{id}/complete`, `POST /documents/{id}/retry` and `POST /scenarios/{id}/runs`
  accept an optional `Idempotency-Key` header; repeating a request with the same key returns the original result.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness (no auth) |
| GET | `/ready` | Readiness: database, queue, storage (no auth; 503 when not ready) |
| GET / PATCH | `/me` | Current profile; update display name / reporting currency |
| DELETE | `/me` | Delete account data (body `{"confirm": "DELETE MY ACCOUNT"}`) |
| GET | `/me/documents` | All documents across the user's households (settings page) |
| GET / POST | `/households` | List (paginated) / create household (creator becomes owner) |
| POST | `/households/demo` | Create a clearly-labelled demo household with synthetic data and synthetic sample contracts |
| GET / PATCH / DELETE | `/households/{hid}` | Read / update (editor) / delete (owner; purges stored files) |
| GET | `/households/{hid}/summary` | Totals by asset kind and currency, flows, counts, latest run |
| GET / POST | `/households/{hid}/assets` | List / create |
| PATCH / DELETE | `/assets/{id}` | Update / delete |
| GET / POST | `/households/{hid}/liabilities` | List / create |
| PATCH / DELETE | `/liabilities/{id}` | |
| GET / POST | `/households/{hid}/cash-flows` | Recurring monthly income/expenses |
| PATCH / DELETE | `/cash-flows/{id}` | |
| GET / POST | `/households/{hid}/events` | Scheduled events: capital calls, RSU vests, tax payments, redemption requests |
| PATCH / DELETE | `/events/{id}` | |
| GET | `/households/{hid}/documents` | Document library (paginated) |
| POST | `/households/{hid}/documents` | Initiate upload → `{document, upload: {method, url, max_bytes}, duplicate}` |
| PUT | `/documents/{id}/content` | Upload the PDF bytes (`Content-Type: application/pdf`); validated, stored privately |
| POST | `/documents/{id}/complete` | Enqueue processing → `JobOut` (idempotent) |
| GET | `/documents/{id}` | Document with latest job and constraint count |
| GET | `/documents/{id}/jobs` | Processing attempts |
| POST | `/documents/{id}/retry` | New job for a failed document (409 otherwise) |
| GET | `/documents/{id}/download` | Short-lived signed URL |
| GET | `/documents/{id}/pages/{pdf_page}` | Extracted text of one page (evidence viewer) |
| DELETE | `/documents/{id}` | Delete file, page text and constraints (see retention policy) |
| GET | `/jobs/{id}` | Job status / progress |
| GET | `/households/{hid}/constraints` | Filters: `document_id`, `review_status` |
| GET | `/constraints/{id}` | Constraint with revision history |
| PATCH | `/constraints/{id}` | Edit values / status (requires `expected_revision`) |
| POST | `/constraints/{id}/approve` · `/reject` | Review decisions (require `expected_revision`) |
| GET | `/scenario-defaults` | Default assumptions and field metadata |
| GET / POST | `/households/{hid}/scenarios` | List / create scenarios |
| GET / PATCH / DELETE | `/scenarios/{id}` | |
| POST | `/scenarios/{id}/runs` | Run both models; persists inputs, approved constraint versions, engine version, monthly rows |
| GET | `/households/{hid}/runs` | Simulation history (paginated) |
| GET | `/runs/{id}` | Run detail incl. monthly rows for both models and term provenance |
| POST | `/scenarios/{id}/stress` | Reverse stress search |
| GET | `/households/{hid}/stress-results` · `/stress-results/{id}` | History / detail |
| POST | `/scenarios/{id}/prevention` | Ranked options + optimised combination (verified by re-simulation) |
| GET | `/households/{hid}/prevention-plans` · `/prevention-plans/{id}` | |
| POST | `/recommendations/{id}/decision` | `{"decision": "approved"|"rejected"}` |
| POST | `/recommendations/{id}/apply` | Create a new scenario with an **approved** recommendation applied |
| GET / POST | `/households/{hid}/exports` | List / request export (`constraints_csv`, `constraints_json`, `simulation_csv`, `results_json`, `report_pdf`) |
| GET | `/exports/{id}` · `/exports/{id}/download` | Status / signed download URL |
| GET | `/households/{hid}/audit-events` | Audit trail (paginated) |
| GET / POST | `/chats` | List the caller's assistant conversations (`?household_id=`; omit for general ones) / start one (`{"household_id": null|uuid}`) |
| GET / PATCH / DELETE | `/chats/{id}` | Conversation with messages / rename / delete (author only) |
| POST | `/chats/{id}/messages` | `{"content"}`; streams the reply as server-sent events: `delta` `{text}`, then `done` `{user_message, assistant_message, title}` or `error` `{code, message}`. Uses the caller's active AI provider key (409 `ai_provider_required` without one) |

## Document lifecycle

`pending_upload → uploaded → queued → processing → extracted | failed`, and `deleted`.
Jobs: `queued → running → succeeded | failed`. A failed document can be retried; at most one active job per
document is allowed (database-enforced), and re-extraction cannot duplicate constraints
(unique `(document_id, extraction_key)`).
