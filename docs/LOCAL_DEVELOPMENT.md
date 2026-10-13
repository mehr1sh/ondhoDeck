# Local development

The local stack mirrors production: PostgreSQL, Redis, Supabase Auth (GoTrue) and a mail catcher run in
Docker; the API, worker, auth gateway and frontend run on the host.

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API (+ OpenAPI docs at `/docs`) | http://localhost:8000 |
| Supabase Auth via dev gateway | http://localhost:54321/auth/v1 |
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
alembic upgrade head

# three terminals:
uvicorn app.main:app --reload --port 8000
celery -A app.worker.celery_app worker --loglevel=INFO --concurrency=2 -Q slipslopes
python scripts/dev_auth_proxy.py      # serves the local auth server under :54321/auth/v1
```

Check readiness: `curl localhost:8000/api/v1/ready`.

## 3. Frontend

```bash
cd frontend
pnpm install
cp .env.example .env.local
# NEXT_PUBLIC_SUPABASE_URL=http://localhost:54321
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
