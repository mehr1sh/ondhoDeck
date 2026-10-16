# Local development

The local stack mirrors production: PostgreSQL, Redis, Supabase Auth (GoTrue) and a mail catcher run in
Docker; the API, worker, auth gateway and frontend run on the host.

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API (+ OpenAPI docs at `/docs`) | http://localhost:8000 |
| Supabase Auth via dev gateway | http://localhost:54331/auth/v1 |
| Mailpit (confirmation / recovery emails) | http://localhost:8025 |
| PostgreSQL | localhost:54329 |
| Redis | localhost:6379 |

## Prerequisites

Python 3.11, Node.js 20+ with pnpm, Docker, and Tesseract (`tesseract-ocr`) for OCR of scanned PDFs.

## 1. Services

```bash
docker compose up -d            # postgres, redis, mailpit, auth
```

`infra/local/init-db.sql` creates the `slipslopes` role and databases, the `anon`/`authenticated` roles used
by RLS policies, and the auth server's own database.

## 2. Backend

```bash
cd backend
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python scripts/dev_keys.py            # prints local ANON_KEY and SERVICE_ROLE_KEY
# In .env set:
#   SUPABASE_JWT_SECRET=local-dev-jwt-secret-at-least-32-characters-long
#   SUPABASE_SERVICE_ROLE_KEY=<SERVICE_ROLE_KEY printed above>
#   CREDENTIALS_ENCRYPTION_KEYS=<output of: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
#     (optional; enables Settings -> AI providers. Without it, key storage is disabled and
#      extraction falls back to the server provider or rule-based extraction.)
alembic upgrade head

# three terminals:
uvicorn app.main:app --reload --port 8000
celery -A app.worker.celery_app worker --loglevel=INFO --concurrency=2 -Q slipslopes
python scripts/dev_auth_proxy.py      # serves the local auth server under :54331/auth/v1
```

Check readiness: `curl localhost:8000/api/v1/ready`.

## 3. Frontend

```bash
cd frontend
pnpm install
cp .env.example .env.local
# NEXT_PUBLIC_SUPABASE_URL=http://localhost:54331
# NEXT_PUBLIC_SUPABASE_ANON_KEY=<ANON_KEY printed by dev_keys.py>
# NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
pnpm dev
```

Register at http://localhost:3000/register, open the confirmation email in Mailpit, then sign in.

## Tests

```bash
cd backend && pytest                       # engine + API tests (uses the slipslopes_test database)
cd frontend && pnpm test                   # component and flow tests (fetch and Supabase mocked)
```

The API tests use a real PostgreSQL database with migrations and RLS, but replace external services:
the queue runs eagerly in-process, storage is a temporary directory, tokens are signed locally, and the LLM
provider is absent or mocked. They do not prove live Supabase, Redis or LLM integration.

To exercise the real services end to end (auth emails, queue, worker, storage):

```bash
cd backend
python scripts/dev_keys.py | grep ANON_KEY | cut -d= -f2 > /tmp/anon_key
python scripts/e2e_local.py path/to/prospectus.pdf /tmp/anon_key
```

## Demo data

"Create demo household" (dashboard) creates a household named *Demo household (synthetic)* with fictional
balances and four synthetic sample contracts (watermarked SYNTHETIC) that are processed through the normal
pipeline. Demo data is labelled in the UI and in every record (`is_demo`, `is_demo_fixture`).

The BREIT prospectus is a third-party document and is not included in the repository; upload it through the
document library to extract its share-repurchase terms.

## Browser end-to-end tests

`frontend/e2e/` drives the real UI with Playwright against a running local stack (API, worker, auth gateway,
Mailpit and a frontend build). It registers a fresh account, confirms it through Mailpit, adds a library fund,
uploads a synthetic test prospectus, approves a term, links a holding and runs the blind-spot check.

```bash
cd frontend
pnpm build && pnpm start -p 3000          # or any port listed in the API's and gateway's CORS_ORIGINS
E2E_BASE_URL=http://localhost:3000 pnpm exec playwright test
```

To test a build without replacing one that `pnpm start` is already serving, build into another directory
(`NEXT_DIST_DIR=.next-verify pnpm build`, then `NEXT_DIST_DIR=.next-verify pnpm start -p 3100`) and add
`http://localhost:3100` to `CORS_ORIGINS` for both the API and `scripts/dev_auth_proxy.py`.
