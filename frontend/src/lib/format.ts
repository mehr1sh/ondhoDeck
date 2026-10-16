/** Display formatting helpers. All money comes from the API as decimal strings or numbers. */

export const MINUS = "−";
export const EMPTY = "—";

/** Parses an API decimal ("250000.00", "-12.5", 42) to a number. Returns null for empty/invalid. */
export function parseDecimal(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const s = value.trim().replace(/,/g, "").replace(MINUS, "-");
  if (!s || !/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function withRealMinus(n: number, formatAbs: (abs: number) => string): string {
  // Treat -0 and values that round to zero as zero (no sign).
  const abs = Math.abs(n);
  const formatted = formatAbs(abs);
  const isZero = !/[1-9]/.test(formatted);
  return n < 0 && !isZero ? `${MINUS}${formatted}` : formatted;
}

const moneyFormatters = new Map<string, Intl.NumberFormat>();

function moneyFormatter(currency: string, digits: number): Intl.NumberFormat {
  const key = `${currency}|${digits}`;
  let f = moneyFormatters.get(key);
  if (!f) {
    try {
      f = new Intl.NumberFormat("en-US", {
        style: "currency",
        currency,
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
    } catch {
      // Unknown currency code: fall back to a plain number with the code appended.
      const plain = new Intl.NumberFormat("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
      f = { format: (n: number) => `${plain.format(n)} ${currency}` } as Intl.NumberFormat;
    }
    moneyFormatters.set(key, f);
  }
  return f;
}

export interface MoneyOptions {
  /** Fraction digits (default 0 for |value| >= 1000, else 2). */
  digits?: number;
  /** Compact notation (e.g. $1.2M) for chart axes. */
  compact?: boolean;
}

/** Formats a money value with its currency, using a real minus sign for negatives. */
export function formatMoney(value: unknown, currency = "USD", opts: MoneyOptions = {}): string {
  const n = parseDecimal(value);
  if (n === null) return EMPTY;
  const code = (currency || "USD").toUpperCase();
  if (opts.compact) {
    let f: Intl.NumberFormat;
    try {
      f = new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: code,
        notation: "compact",
        maximumFractionDigits: 1,
      });
    } catch {
      f = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
    }
    return withRealMinus(n, (a) => f.format(a));
  }
  const digits = opts.digits ?? (Math.abs(n) >= 1000 ? 0 : 2);
  return withRealMinus(n, (a) => moneyFormatter(code, digits).format(a));
}

/** Formats a fraction (0.25) as a percentage ("25.0%"). */
export function formatPercent(value: unknown, digits = 1): string {
  const n = parseDecimal(value);
  if (n === null) return EMPTY;
  const f = new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return withRealMinus(n, (a) => f.format(a));
}

export function formatNumber(value: unknown, digits = 0): string {
  const n = parseDecimal(value);
  if (n === null) return EMPTY;
  const f = new Intl.NumberFormat("en-US", { minimumFractionDigits: 0, maximumFractionDigits: digits });
  return withRealMinus(n, (a) => f.format(a));
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return EMPTY;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return EMPTY;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(d);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return EMPTY;
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(d);
}

const ACRONYMS: Record<string, string> = {
  reit: "REIT", rsu: "RSU", sbl: "SBL", nav: "NAV", ltv: "LTV", pdf: "PDF", fx: "FX", csv: "CSV", json: "JSON",
  sec: "SEC", cik: "CIK", sai: "SAI", gp: "GP", lpa: "LPA", llm: "LLM", pct: "%",
};

/** "non_traded_reit" -> "Non-traded REIT"; "reit_monthly_cap_pct" -> "REIT monthly cap %" */
export function humanize(key: string): string {
  const words = key.replace(/_/g, " ").trim().split(/\s+/).filter(Boolean)
    .map((w) => ACRONYMS[w.toLowerCase()] ?? w);
  const s = words.join(" ").replace(/\bnon traded\b/i, (m) => `${m.split(" ")[0]}-traded`);
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function formatMonth(month: number | null | undefined, label?: string | null): string {
  if (month === null || month === undefined) return "None";
  return label ? `Month ${month} (${label})` : `Month ${month}`;
}

export const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/**
 * Formats an arbitrary value from a loosely-typed API dict (attribution rows, key events,
 * liquidity breakdowns): month-like keys as integers, booleans as Yes/No, other numbers as money.
 */
export function formatCell(key: string, value: unknown, currency: string): string {
  if (value === null || value === undefined || value === "") return EMPTY;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.map(String).join("; ") : EMPTY;
  if (typeof value === "object") return JSON.stringify(value);
  const n = typeof value === "number" ? value : null;
  if (n !== null) {
    if (/month/i.test(key)) return formatNumber(n);
    if (/(drawdown|rate|share|pct|fraction)/i.test(key)) return formatPercent(n);
    return formatMoney(n, currency);
  }
  return String(value);
}

/** Converts a user-entered amount ("1,250.5") to a normalized decimal string ("1250.5"). */
export function normalizeDecimalInput(input: string): string {
  return input.trim().replace(/,/g, "").replace(MINUS, "-");
}
