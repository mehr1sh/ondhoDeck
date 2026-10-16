# Deploying OndhoDeck

Targets: **Supabase** (PostgreSQL, Auth, Storage), **Render** (FastAPI web service, Celery worker,
Key Value queue), **Vercel** (Next.js frontend). Keep separate Supabase projects (or at least separate
databases and buckets) for preview and production.

> Nothing in this repository has been deployed by its authors' tooling; follow these steps with your own
> accounts. Never commit the values you create here.

## 1. Supabase

1. Create a project. From **Project Settings → API** note:
   - Project URL (`https://<ref>.supabase.co`) → `SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`
   - Publishable/anon key → `NEXT_PUBLIC_SUPABASE_ANON_KEY` (safe for the browser)
   - Service-role/secret key → `SUPABASE_SERVICE_ROLE_KEY` (**backend only**)
   - If the project still uses the legacy JWT secret, also set `SUPABASE_JWT_SECRET`. Projects using JWT
     signing keys need only `SUPABASE_URL` (the API reads `/auth/v1/.well-known/jwks.json`).
2. **Database URL.** Project Settings → Database → connection string. Use the session-mode pooler or
   direct connection, prefixed with the driver: `postgresql+psycopg://postgres.<ref>:<password>@<host>:5432/postgres`.
3. **Migrations** (from a trusted machine or CI, never from the browser):
   ```bash
   cd backend
   DATABASE_URL='postgresql+psycopg://...' SUPABASE_URL='https://<ref>.supabase.co' alembic upgrade head
   ```
   The RLS migration reuses Supabase's existing `anon`/`authenticated` roles and `auth.uid()`.
   On Render, `preDeployCommand: alembic upgrade head` applies new migrations on each deploy.
4. **Storage.** Run `supabase/storage.sql` in the SQL editor to create the private `documents` bucket.
5. **Auth settings** (Authentication → URL Configuration):
   - Site URL: your Vercel production URL.
   - Redirect URLs: `https://<your-app>/update-password`, `https://<your-app>/**` and preview URLs as needed.
   - Keep email confirmation enabled. Configure custom SMTP for production email delivery.

## 2. Render (API, worker, queue)

1. New → **Blueprint** → select this repository. `render.yaml` defines `slipslopes-api` (web),
   `slipslopes-worker` (worker) and `slipslopes-queue` (Key Value, `noeviction`).
2. Fill the `sync: false` variables when prompted: `DATABASE_URL`, `SUPABASE_URL`,
   `SUPABASE_SERVICE_ROLE_KEY`, optional `SUPABASE_JWT_SECRET`, `CORS_ORIGINS` (exact Vercel origin(s),
   comma-separated), `CREDENTIALS_ENCRYPTION_KEYS` (enables user-supplied API keys; the API and the
   worker must share the same value), and `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`/`OPENAI_MODEL` if a
   server-level `LLM_PROVIDER` is used.
3. The API health check is `/api/v1/health`; `/api/v1/ready` reports database, queue and storage state.
4. Both services build `backend/Dockerfile`, which installs Tesseract for OCR.
5. `preDeployCommand` requires a paid Render plan; on free plans run `alembic upgrade head` manually
   (Render Shell or locally against the production `DATABASE_URL`) **before** deploying code that needs it.

## 3. Vercel (frontend)

1. Import the repository; set **Root Directory** to `frontend`. Framework preset: Next.js.
   Install command `pnpm install --frozen-lockfile`, build command `pnpm build`.
2. Environment variables (Production and Preview, with different values per environment):
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `NEXT_PUBLIC_API_BASE_URL` (e.g. `https://slipslopes-api.onrender.com`)
3. Add the Vercel URL(s) to the API's `CORS_ORIGINS` and to Supabase Auth redirect URLs.

## Environment variable reference

### Backend (`backend/.env.example`)

| Variable | Required | Description |
|---|---|---|
| `ENVIRONMENT` | yes | `development`, `test`, `preview`, `production` (preview/production enforce Supabase storage) |
| `DATABASE_URL` | yes | SQLAlchemy URL (`postgresql+psycopg://...`) |
| `SUPABASE_URL` | prod | Enables JWKS verification and issuer checks; storage base URL |
| `SUPABASE_JWT_SECRET` | optional | Legacy HS256 verification (and the local auth server) |
| `SUPABASE_JWT_AUDIENCE` | no | Default `authenticated` |
| `SUPABASE_SERVICE_ROLE_KEY` | prod | Server-only key for Storage and account deletion |
| `STORAGE_BACKEND` | yes | `supabase` (preview/prod) or `local` (development) |
| `STORAGE_BUCKET` | no | Default `documents` |
| `LOCAL_STORAGE_DIR` | dev | Directory for local storage |
| `SIGNED_URL_TTL_SECONDS` | no | Download link lifetime (default 120) |
| `REDIS_URL` | yes | Queue / rate-limit store |
| `MAX_UPLOAD_MB`, `MAX_PDF_PAGES` | no | Upload limits (50 MB, 1500 pages) |
| `OCR_ENABLED`, `OCR_MAX_PAGES` | no | OCR fallback and its page budget |
| `PROCESSING_TIME_LIMIT_S`, `MAX_JOB_ATTEMPTS` | no | Worker time limit and automatic retry bound |
| `LLM_PROVIDER` | no | Server-level provider: `none` (rule-based), `anthropic` or `openai` |
| `ANTHROPIC_API_KEY`, `LLM_MODEL`, `LLM_EFFORT`, `LLM_MAX_EXCERPTS`, `LLM_TIMEOUT_S` | if LLM | Provider settings |
| `ANTHROPIC_WORKSPACE_ID` | if needed | Workspace ID (`wrkspc_...`) sent as `anthropic-workspace-id`; required by Anthropic for keys not scoped to a workspace. Users set theirs per key in Settings → AI providers. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | if `openai` | OpenAI server provider (model has no default) |
| `CREDENTIALS_ENCRYPTION_KEYS` | for BYOK | Comma-separated Fernet keys encrypting user API keys at rest; first key encrypts, all decrypt. Empty disables key storage (503). Rotate by prepending a new key, then re-saving keys. |
| `RATE_LIMIT_PROVIDER_TESTS_PER_10MIN` | no | Per-user limit on key saves/tests/model listing (default 10) |
| `CORS_ORIGINS` | yes | Comma-separated exact origins |
| `RATE_LIMIT_EXTRACTION_PER_HOUR`, `RATE_LIMIT_COMPUTE_PER_MINUTE` | no | Per-user limits |

### Frontend (`frontend/.env.example`)

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL (local: `http://localhost:54331`) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Publishable/anon key (browser-safe) |
| `NEXT_PUBLIC_API_BASE_URL` | API origin (local: `http://localhost:8000`) |

## Migration policy

- Every schema change is an Alembic revision committed with the code that needs it.
- CI applies, rolls back and re-applies all migrations on a fresh database.
- Production: migrations run once per deploy (Render pre-deploy) against the production database before
  new code starts. Destructive changes should be split into expand → migrate data → contract releases.
- Tests run against a separate `slipslopes_test` database that is reset by the test-suite.

### Fund library rollout (migrations `e5f1a9c2d7b3`, `f2b8c4d1e6a9`)

1. Take a database backup. The migration adds firms (one per existing account) and assigns every household to
   its creator's firm; it deletes nothing. Its downgrade refuses to run once library data exists.
2. After the deploy, preview the backfill of household-uploaded public offering documents into each firm's
   library, then apply it (Render Shell, from `backend/`):
   `python scripts/backfill_fund_library.py` (dry run) and `python scripts/backfill_fund_library.py --apply`.
   Household records are not modified; copied terms need reviewer approval; holdings are not linked
   automatically. See [FUND_LIBRARY.md](FUND_LIBRARY.md).
