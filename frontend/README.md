# SlipSlopes web frontend

Web client for **SlipSlopes — Contractual Liquidity Intelligence**. It talks to the SlipSlopes API
(`/api/v1`, see `../docs/API.md`) and uses Supabase Auth for sign-in.

Stack: Next.js (App Router) · React · TypeScript (strict) · Tailwind CSS · `@supabase/ssr` · Recharts ·
Vitest + Testing Library.

## Setup

Requirements: Node.js 20+ and pnpm.

```bash
cd frontend
pnpm install
cp .env.example .env.local   # then fill in real values
pnpm dev                     # http://localhost:3000
```

The API must be running (default `http://localhost:8000`) and must allow the frontend origin via CORS
(`cors_origins` in the API configuration, `http://localhost:3000` by default).

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | yes | Supabase project URL (Project settings → API). |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | yes | Supabase public anon key. Never use the service-role key here. |
| `NEXT_PUBLIC_API_BASE_URL` | yes | Base URL of the SlipSlopes API **without** `/api/v1`, e.g. `http://localhost:8000`. |

All three are public (`NEXT_PUBLIC_*`) and are embedded into the client bundle at build time — rebuild after
changing them. They are read lazily: if any is missing the app still builds and shows a
"Configuration required" screen listing the missing variables instead of crashing.

### Supabase Auth settings

- **Site URL**: your deployed origin (e.g. `https://slipslopes.example.com`).
- **Redirect URLs**: add `<origin>/login` (email confirmation) and `<origin>/update-password` (password recovery),
  for every origin you use (local, preview, production).
- If email confirmation is enabled, registration shows a "Check your email" screen; the confirmation link returns
  the user to `/login`.

## Scripts

| Command | What it does |
|---|---|
| `pnpm dev` | Development server |
| `pnpm build` | Production build |
| `pnpm start` | Serve the production build |
| `pnpm lint` | ESLint (Next.js core-web-vitals + TypeScript rules) |
| `pnpm typecheck` | `tsc --noEmit` |
| `pnpm test` | Vitest unit/component tests (jsdom; `fetch` and Supabase are mocked) |

## How it fits together

- `src/middleware.ts` refreshes the Supabase session cookie and redirects unauthenticated requests for protected
  routes to `/login?next=…`. The same rules (`src/lib/authGuard.ts`) are applied client-side by `AppShell`.
- `src/lib/api.ts` is the single API client: it attaches `Authorization: Bearer <access token>`, parses the
  `{"error": {code, message, request_id, details}}` envelope into `ApiError` (with per-field messages for 422),
  and on 401 signs out and redirects to `/login?next=…&reason=expired`.
- `src/lib/endpoints.ts` wraps every endpoint; `src/lib/types.ts` mirrors `backend/app/api_schemas.py`.
  Decimal values arrive as strings and are parsed only for display (`src/lib/format.ts`).
- PDF uploads (`src/lib/upload.ts`): SHA-256 in the browser → initiate → `PUT` bytes → complete → poll every 2 s.
- All figures and charts are rendered from API responses; nothing financial is hard-coded in components.
  Demo households and sample contracts are synthetic and labelled as such throughout the UI.

## Deploying to Vercel

1. Import the repository and set **Root Directory** to `frontend`.
2. Framework preset: Next.js. Install command `pnpm install`, build command `pnpm build`
   (output is detected automatically).
3. Set environment variables for Production (and Preview if used):
   `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_BASE_URL`.
4. Add the deployed origin to the API's CORS origins and to Supabase Auth redirect URLs (see above).
5. Redeploy after changing any `NEXT_PUBLIC_*` variable (they are embedded at build time).
