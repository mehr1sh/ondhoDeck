"""Print local-only Supabase-style API keys signed with the local GoTrue JWT secret.

The hosted Supabase dashboard provides these keys; this script exists only for the local stack.
    python scripts/dev_keys.py <jwt-secret>
"""
import sys
import time

import jwt

secret = sys.argv[1] if len(sys.argv) > 1 else "local-dev-jwt-secret-at-least-32-characters-long"
exp = int(time.time()) + 10 * 365 * 24 * 3600
for role in ("anon", "service_role"):
    token = jwt.encode({"role": role, "iss": "supabase-local", "iat": int(time.time()), "exp": exp}, secret,
                       algorithm="HS256")
    print(f"{role.upper()}_KEY={token}")
