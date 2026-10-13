"use client";

import { TableWrap, tableClass, tbodyClass, td, tdNum, th, thNum } from "@/components/ui";
import { formatCell, humanize } from "@/lib/format";

/** Renders a list of loosely-typed API rows (e.g. attribution, key events) as a table. */
export function DictTable({ rows, currency, label }: { rows: Record<string, unknown>[]; currency: string; label: string }) {
  const keys: string[] = [];
  for (const r of rows) for (const k of Object.keys(r)) if (!keys.includes(k)) keys.push(k);
  const numeric = (k: string) => rows.some((r) => typeof r[k] === "number");
  return (
    <TableWrap label={label}>
      <table className={tableClass}>
        <thead>
          <tr>
            {keys.map((k) => (
              <th key={k} className={numeric(k) ? thNum : th}>
                {humanize(k)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className={tbodyClass}>
          {rows.map((r, i) => (
            <tr key={i}>
              {keys.map((k) => (
                <td key={k} className={numeric(k) ? tdNum : td}>
                  {formatCell(k, r[k], currency)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}
