"use client";

import Link from "next/link";
import { Badge } from "@/components/ui";
import { FundPicker } from "@/components/funds/FundPicker";
import { itemsOf } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDate, formatMoney, formatPercent, humanize } from "@/lib/format";
import {
  ASSET_KINDS,
  ASSET_KIND_FUND_TYPE,
  type AssetKind,
  CASH_FLOW_KINDS,
  EVENT_KINDS,
  LIABILITY_KINDS,
  type AssetIn,
  type AssetOut,
  type CashFlowIn,
  type CashFlowOut,
  type EventIn,
  type EventOut,
  type LiabilityIn,
  type LiabilityOut,
} from "@/lib/types";
import { CrudSection } from "./CrudSection";
import type { FieldDef } from "./RecordForm";

/** API limit for projection months (MAX_HORIZON_MONTHS). */
export const MAX_PROJECTION_MONTH = 120;

export const ASSET_FIELDS: FieldDef[] = [
  { name: "kind", label: "Kind", type: "select", options: ASSET_KINDS, required: true },
  { name: "name", label: "Name", type: "text", required: true, maxLength: 160 },
  { name: "amount", label: "Amount", type: "money", required: true, hint: "Current value, up to 2 decimals." },
  { name: "currency", label: "Currency", type: "currency", required: true },
  { name: "as_of", label: "As of", type: "date" },
  {
    name: "unfunded_commitment",
    label: "Unfunded commitment",
    type: "money",
    hint: "Remaining commitment that can be called.",
    showIf: (v) => v.kind === "private_fund_commitment",
  },
  {
    name: "fund_id",
    label: "Library fund",
    type: "custom",
    resetOn: ["kind"],
    showIf: (v) => Boolean(ASSET_KIND_FUND_TYPE[v.kind as AssetKind]),
    render: ({ value, set, error, values, initial }) => (
      <FundPicker
        fundType={ASSET_KIND_FUND_TYPE[values.kind as AssetKind]!}
        value={value}
        initialName={initial && initial.fund_id === value ? (initial.fund_name as string | null | undefined) : null}
        onChange={set}
        error={error}
      />
    ),
  },
  { name: "pledged_to_sbl", label: "Pledged to securities-backed line", type: "checkbox" },
  { name: "liquidity_notes", label: "Liquidity notes", type: "textarea", maxLength: 2000 },
];

export const LIABILITY_FIELDS: FieldDef[] = [
  { name: "kind", label: "Kind", type: "select", options: LIABILITY_KINDS, required: true },
  { name: "name", label: "Name", type: "text", required: true, maxLength: 160 },
  { name: "balance", label: "Balance", type: "money", required: true },
  { name: "currency", label: "Currency", type: "currency", required: true },
  { name: "annual_rate", label: "Annual rate (%)", type: "percent", min: 0, max: 100, hint: "e.g. 7.25 for 7.25%" },
  { name: "monthly_payment", label: "Monthly payment", type: "money" },
  { name: "notes", label: "Notes", type: "textarea", maxLength: 2000 },
];

export const CASH_FLOW_FIELDS: FieldDef[] = [
  { name: "kind", label: "Kind", type: "select", options: CASH_FLOW_KINDS, required: true },
  { name: "name", label: "Name", type: "text", required: true, maxLength: 160 },
  { name: "monthly_amount", label: "Monthly amount", type: "money", required: true },
  { name: "currency", label: "Currency", type: "currency", required: true },
];

export const EVENT_FIELDS: FieldDef[] = [
  { name: "kind", label: "Kind", type: "select", options: EVENT_KINDS, required: true },
  { name: "label", label: "Label", type: "text", maxLength: 160 },
  {
    name: "month",
    label: "Projection month",
    type: "int",
    required: true,
    min: 1,
    max: MAX_PROJECTION_MONTH,
    hint: "1 = first projection month.",
  },
  { name: "amount", label: "Amount", type: "money", required: true },
  { name: "currency", label: "Currency", type: "currency", required: true },
  {
    name: "tax_due_month",
    label: "Tax due month",
    type: "int",
    min: 1,
    max: MAX_PROJECTION_MONTH,
    hint: "Projection month when tax on this vest is due.",
    showIf: (v) => v.kind === "rsu_vest",
  },
];

export function AssetsSection({ householdId, canEdit }: { householdId: string; canEdit: boolean }) {
  return (
    <CrudSection<AssetOut>
      title="Assets"
      singular="Asset"
      fields={ASSET_FIELDS}
      canEdit={canEdit}
      load={async () => itemsOf(await endpoints.listAssets(householdId, { limit: 100 }))}
      create={(b) => endpoints.createAsset(householdId, b as unknown as AssetIn)}
      update={(id, b) => endpoints.updateAsset(id, b)}
      remove={(id) => endpoints.deleteAsset(id)}
      rowLabel={(r) => r.name}
      columns={[
        { header: "Name", render: (r) => r.name },
        { header: "Kind", render: (r) => humanize(r.kind) },
        {
          header: "Library fund",
          render: (r) =>
            r.fund_id ? (
              <Link href={`/funds/${r.fund_id}`} className="underline-offset-2 hover:underline">
                {r.fund_name ?? "Linked fund"}
              </Link>
            ) : (
              EMPTY
            ),
        },
        { header: "Amount", numeric: true, render: (r) => formatMoney(r.amount, r.currency) },
        { header: "Currency", render: (r) => r.currency },
        {
          header: "Unfunded",
          numeric: true,
          render: (r) => (r.unfunded_commitment ? formatMoney(r.unfunded_commitment, r.currency) : EMPTY),
        },
        { header: "Pledged", render: (r) => (r.pledged_to_sbl ? <Badge tone="warning">Pledged to SBL</Badge> : "No") },
        { header: "As of", render: (r) => formatDate(r.as_of) },
      ]}
    />
  );
}

export function LiabilitiesSection({ householdId, canEdit }: { householdId: string; canEdit: boolean }) {
  return (
    <CrudSection<LiabilityOut>
      title="Liabilities"
      singular="Liability"
      fields={LIABILITY_FIELDS}
      canEdit={canEdit}
      load={async () => itemsOf(await endpoints.listLiabilities(householdId, { limit: 100 }))}
      create={(b) => endpoints.createLiability(householdId, b as unknown as LiabilityIn)}
      update={(id, b) => endpoints.updateLiability(id, b)}
      remove={(id) => endpoints.deleteLiability(id)}
      rowLabel={(r) => r.name}
      columns={[
        { header: "Name", render: (r) => r.name },
        { header: "Kind", render: (r) => humanize(r.kind) },
        { header: "Balance", numeric: true, render: (r) => formatMoney(r.balance, r.currency) },
        { header: "Currency", render: (r) => r.currency },
        { header: "Annual rate", numeric: true, render: (r) => formatPercent(r.annual_rate, 2) },
        { header: "Monthly payment", numeric: true, render: (r) => formatMoney(r.monthly_payment, r.currency) },
      ]}
    />
  );
}

export function CashFlowsSection({ householdId, canEdit }: { householdId: string; canEdit: boolean }) {
  return (
    <CrudSection<CashFlowOut>
      title="Recurring cash flows"
      singular="Cash flow"
      description="Recurring monthly income and expenses."
      fields={CASH_FLOW_FIELDS}
      canEdit={canEdit}
      load={async () => itemsOf(await endpoints.listCashFlows(householdId, { limit: 100 }))}
      create={(b) => endpoints.createCashFlow(householdId, b as unknown as CashFlowIn)}
      update={(id, b) => endpoints.updateCashFlow(id, b)}
      remove={(id) => endpoints.deleteCashFlow(id)}
      rowLabel={(r) => r.name}
      columns={[
        { header: "Name", render: (r) => r.name },
        {
          header: "Kind",
          render: (r) => <Badge tone={r.kind === "income" ? "success" : "neutral"}>{humanize(r.kind)}</Badge>,
        },
        { header: "Monthly amount", numeric: true, render: (r) => formatMoney(r.monthly_amount, r.currency) },
        { header: "Currency", render: (r) => r.currency },
      ]}
    />
  );
}

export function EventsSection({ householdId, canEdit }: { householdId: string; canEdit: boolean }) {
  return (
    <CrudSection<EventOut>
      title="Scheduled events"
      singular="Event"
      description="Capital calls, RSU vests (with the month tax is due), tax payments, other inflows/outflows and REIT or interval-fund redemption requests."
      fields={EVENT_FIELDS}
      canEdit={canEdit}
      load={async () => {
        const items = itemsOf(await endpoints.listEvents(householdId, { limit: 100 }));
        return [...items].sort((a, b) => a.month - b.month);
      }}
      create={(b) => endpoints.createEvent(householdId, b as unknown as EventIn)}
      update={(id, b) => endpoints.updateEvent(id, b)}
      remove={(id) => endpoints.deleteEvent(id)}
      rowLabel={(r) => r.label || humanize(r.kind)}
      columns={[
        { header: "Month", numeric: true, render: (r) => r.month },
        { header: "Kind", render: (r) => humanize(r.kind) },
        { header: "Label", render: (r) => r.label || EMPTY },
        { header: "Amount", numeric: true, render: (r) => formatMoney(r.amount, r.currency) },
        { header: "Currency", render: (r) => r.currency },
        { header: "Tax due month", numeric: true, render: (r) => r.tax_due_month ?? EMPTY },
      ]}
    />
  );
}
