/** Splits `text` into segments, marking the first whitespace/case-insensitive occurrence of `quote`. */
export interface Segment {
  text: string;
  match: boolean;
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function highlightQuote(text: string, quote: string | null | undefined): { segments: Segment[]; found: boolean } {
  const words = (quote ?? "")
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!words.length || !text) return { segments: [{ text, match: false }], found: false };
  const normalized = text.replace(/[“”]/g, '"').replace(/[‘’]/g, "'");
  const re = new RegExp(words.map(escapeRe).join("\\s+"), "i");
  const m = re.exec(normalized);
  if (!m) return { segments: [{ text, match: false }], found: false };
  const start = m.index;
  const end = start + m[0].length;
  const segments: Segment[] = [];
  if (start > 0) segments.push({ text: text.slice(0, start), match: false });
  segments.push({ text: text.slice(start, end), match: true });
  if (end < text.length) segments.push({ text: text.slice(end), match: false });
  return { segments, found: true };
}
