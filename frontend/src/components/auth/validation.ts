export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const MIN_PASSWORD = 8;

export function validateEmail(email: string): string | null {
  if (!email.trim()) return "Enter your email address.";
  if (!EMAIL_RE.test(email.trim())) return "Enter a valid email address.";
  return null;
}

export function validateNewPassword(password: string, confirm: string): { password?: string; confirm?: string } {
  const errors: { password?: string; confirm?: string } = {};
  if (password.length < MIN_PASSWORD) errors.password = `Use at least ${MIN_PASSWORD} characters.`;
  if (confirm !== password) errors.confirm = "Passwords do not match.";
  return errors;
}

/** Turns Supabase auth error messages into user-facing text. */
export function authErrorMessage(err: { message?: string; status?: number; code?: string } | null | undefined): string {
  if (!err) return "Something went wrong. Please try again.";
  const msg = err.message ?? "";
  if (/invalid login credentials/i.test(msg)) return "Incorrect email or password.";
  if (/email not confirmed/i.test(msg)) return "Please confirm your email address first. Check your inbox for the link.";
  if (/rate limit|too many/i.test(msg) || err.status === 429) return "Too many attempts. Please wait a moment and try again.";
  if (/fetch|network/i.test(msg)) return "Could not reach the authentication service. Check your connection.";
  return msg || "Something went wrong. Please try again.";
}
