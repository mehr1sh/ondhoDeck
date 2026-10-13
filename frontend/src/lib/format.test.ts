import { describe, expect, it } from "vitest";
import { formatCell, formatMoney, formatPercent, MINUS, normalizeDecimalInput, parseDecimal } from "./format";

describe("parseDecimal", () => {
  it("parses API decimal strings and numbers", () => {
    expect(parseDecimal("250000.00")).toBe(250000);
    expect(parseDecimal("-12.5")).toBe(-12.5);
    expect(parseDecimal(42)).toBe(42);
    expect(parseDecimal("1,234.50")).toBe(1234.5);
  });
  it("returns null for empty or invalid input", () => {
    expect(parseDecimal(null)).toBeNull();
    expect(parseDecimal("")).toBeNull();
    expect(parseDecimal("abc")).toBeNull();
    expect(parseDecimal(Number.NaN)).toBeNull();
  });
});

describe("formatMoney", () => {
  it("formats with the row's currency", () => {
    expect(formatMoney("250000.00", "USD")).toBe("$250,000");
    expect(formatMoney("1500.5", "EUR")).toBe("€1,501");
    expect(formatMoney("12.5", "GBP")).toBe("£12.50");
  });
  it("uses a real minus sign for negatives", () => {
    const s = formatMoney("-1234.56", "USD");
    expect(s).toBe(`${MINUS}$1,235`);
    expect(s).not.toContain("-");
  });
  it("does not show a sign for negative zero", () => {
    expect(formatMoney(-0.001, "USD")).toBe("$0.00");
  });
  it("supports compact notation and empty values", () => {
    expect(formatMoney(1_250_000, "USD", { compact: true })).toBe("$1.3M");
    expect(formatMoney(null, "USD")).toBe("—");
  });
  it("falls back gracefully for unknown currency codes", () => {
    expect(formatMoney(10, "ZZZ")).toMatch(/10/);
  });
});

describe("formatPercent / formatCell / normalizeDecimalInput", () => {
  it("formats fractions as percentages", () => {
    expect(formatPercent(0.25)).toBe("25.0%");
    expect(formatPercent("-0.031", 1)).toBe(`${MINUS}3.1%`);
  });
  it("formats loosely-typed cells by key", () => {
    expect(formatCell("first_shortfall_month", 7, "USD")).toBe("7");
    expect(formatCell("equity_drawdown", 0.3, "USD")).toBe("30.0%");
    expect(formatCell("peak_shortfall", -5000, "USD")).toBe(`${MINUS}$5,000`);
    expect(formatCell("removes_shortfall", true, "USD")).toBe("Yes");
  });
  it("normalizes user-entered amounts", () => {
    expect(normalizeDecimalInput(" 1,250.50 ")).toBe("1250.50");
  });
});
