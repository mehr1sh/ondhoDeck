"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Button,
  Card,
  CheckboxField,
  Dialog,
  ErrorState,
  LinkButton,
  LoadingBlock,
  Notice,
  SelectField,
  TextAreaField,
  TextField,
} from "@/components/ui";
import { AssumptionBadge } from "@/components/badges";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { humanize } from "@/lib/format";
import { describeError, useApiQuery } from "@/lib/hooks";
import type { AssumptionField, ScenarioAssumptions, ScenarioDefaults, ScenarioOut, ScenarioPreset } from "@/lib/types";
import { groupFields, inputToScalar, isFractionPercent, scalarToInput, SPECIAL_KEYS, unitSuffix } from "./assumptions";
import { RunErrorState, isTermConflict } from "@/components/runs/TermConflict";

interface FxRow {
  currency: string;
  rate: string;
}

interface EditorState {
  name: string;
  description: string;
  /** Input strings for scalar fields (key) and object sub-fields (key.sub). */
  inputs: Record<string, string>;
  booleans: Record<string, boolean>;
  fx: FxRow[];
  sources: Record<string, string>;
  /** YYYY-MM-DD or "" (= the run date). */
  asOfDate: string;
}

function merged(defaults: ScenarioDefaults, scenario?: ScenarioOut | null): Record<string, unknown> {
  const base = defaults.assumptions as unknown as Record<string, unknown>;
  const out: Record<string, unknown> = { ...base };
  if (scenario) {
    for (const [k, v] of Object.entries(scenario.assumptions)) if (k in base) out[k] = v;
  }
  return out;
}

function buildState(defaults: ScenarioDefaults, scenario?: ScenarioOut | null): EditorState {
  const values = merged(defaults, scenario);
  const inputs: Record<string, string> = {};
  const booleans: Record<string, boolean> = {};
  for (const f of defaults.fields) {
    if (SPECIAL_KEYS.has(f.key)) continue;
    const v = values[f.key];
    if (f.kind === "boolean" || typeof v === "boolean") booleans[f.key] = Boolean(v);
    else if (v && typeof v === "object" && !Array.isArray(v)) {
      for (const [sub, sv] of Object.entries(v as Record<string, unknown>)) inputs[`${f.key}.${sub}`] = scalarToInput(f, sv);
    } else inputs[f.key] = scalarToInput(f, v);
  }
  const fx = Object.entries((values.fx_rates as Record<string, number>) ?? {}).map(([currency, rate]) => ({
    currency,
    rate: String(rate),
  }));
  return {
    name: scenario?.name ?? "",
    description: scenario?.description ?? "",
    inputs,
    booleans,
    fx,
    sources: { ...((values.assumption_sources as Record<string, string>) ?? {}) },
    asOfDate: typeof values.as_of_date === "string" ? values.as_of_date : "",
  };
}

/**
 * Applies a preset's assumption values to the form. Keeps the name, description, FX rates and source notes the
 * user already entered (FX rates are household-specific, not part of a stress preset).
 */
export function applyPreset(defaults: ScenarioDefaults, state: EditorState, preset: ScenarioPreset): EditorState {
  const pseudo = { assumptions: preset.assumptions } as unknown as ScenarioOut;
  const next = buildState(defaults, pseudo);
  return {
    ...next,
    name: state.name || preset.name,
    description: state.description || preset.description,
    fx: state.fx,
    sources: state.sources,
    asOfDate: state.asOfDate,
  };
}

function PresetPicker({
  presets,
  disabled,
  onApply,
}: {
  presets: ScenarioPreset[];
  disabled: boolean;
  onApply: (p: ScenarioPreset) => void;
}) {
  const [selected, setSelected] = useState("");
  const preset = presets.find((p) => p.id === selected);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-64 flex-1">
          <SelectField
            label="Start from a preset"
            value={selected}
            disabled={disabled}
            onChange={(e) => setSelected(e.target.value)}
            options={[{ value: "", label: "Choose a preset…" }, ...presets.map((p) => ({ value: p.id, label: p.name }))]}
          />
        </div>
        <Button variant="secondary" disabled={disabled || !preset} onClick={() => preset && onApply(preset)}>
          Apply preset
        </Button>
      </div>
      {preset && (
        <div className="text-sm text-slate-700">
          <p>{preset.description}</p>
          <p className="mt-1 text-xs font-medium text-slate-600">{preset.label}</p>
        </div>
      )}
      <p className="text-xs text-slate-600">
        Applying a preset replaces the assumption values below (FX rates and source notes are kept). Review them before
        saving.
      </p>
    </div>
  );
}

/** Builds the assumptions payload; returns field errors keyed like the API (assumptions.<key>[.<sub>]). */
export function buildAssumptions(
  defaults: ScenarioDefaults,
  scenario: ScenarioOut | null | undefined,
  state: EditorState,
): { assumptions: Partial<ScenarioAssumptions>; errors: Record<string, string> } {
  const values = merged(defaults, scenario);
  const errors: Record<string, string> = {};
  const out: Record<string, unknown> = { ...values };
  for (const f of defaults.fields) {
    if (SPECIAL_KEYS.has(f.key)) continue;
    const current = values[f.key];
    if (f.kind === "boolean" || typeof current === "boolean") {
      out[f.key] = Boolean(state.booleans[f.key]);
    } else if (current && typeof current === "object" && !Array.isArray(current)) {
      const obj: Record<string, unknown> = {};
      for (const sub of Object.keys(current as Record<string, unknown>)) {
        const r = inputToScalar(f, state.inputs[`${f.key}.${sub}`] ?? "");
        if (r.ok) obj[sub] = r.value;
        else errors[`assumptions.${f.key}.${sub}`] = r.error;
      }
      out[f.key] = obj;
    } else {
      const r = inputToScalar(f, state.inputs[f.key] ?? "");
      if (r.ok) out[f.key] = r.value;
      else errors[`assumptions.${f.key}`] = r.error;
    }
  }
  const fx: Record<string, number> = {};
  state.fx.forEach((row, i) => {
    const ccy = row.currency.trim().toUpperCase();
    if (!ccy && !row.rate.trim()) return;
    if (!/^[A-Z]{3}$/.test(ccy)) errors[`fx.${i}.currency`] = "Use a 3-letter ISO 4217 code.";
    const rate = Number(row.rate);
    if (!row.rate.trim() || !Number.isFinite(rate) || rate <= 0) errors[`fx.${i}.rate`] = "Rate must be a positive number.";
    if (ccy && fx[ccy] !== undefined) errors[`fx.${i}.currency`] = "Duplicate currency.";
    if (!errors[`fx.${i}.currency`] && !errors[`fx.${i}.rate`]) fx[ccy] = rate;
  });
  out.fx_rates = fx;
  const sources: Record<string, string> = {};
  for (const [k, v] of Object.entries(state.sources)) if (v.trim()) sources[k] = v.trim();
  out.assumption_sources = sources;
  const asOf = state.asOfDate.trim();
  if (asOf && !/^\d{4}-\d{2}-\d{2}$/.test(asOf)) errors["assumptions.as_of_date"] = "Use the format YYYY-MM-DD.";
  out.as_of_date = asOf || null;
  return { assumptions: out as Partial<ScenarioAssumptions>, errors };
}

function FieldInput({
  field,
  state,
  setState,
  errors,
  disabled,
  defaultValue,
}: {
  field: AssumptionField;
  state: EditorState;
  setState: (fn: (s: EditorState) => EditorState) => void;
  errors: Record<string, string>;
  disabled: boolean;
  defaultValue: unknown;
}) {
  const suffix = unitSuffix(field);
  const label = (
    <>
      {field.label}
      {suffix ? ` (${suffix})` : ""}
    </>
  );
  const sourceInput = (
    <details className="text-xs text-slate-600">
      <summary className="cursor-pointer select-none">Source / citation {state.sources[field.key] ? "(set)" : "(optional)"}</summary>
      <input
        aria-label={`Source for ${field.label}`}
        className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-xs"
        value={state.sources[field.key] ?? ""}
        disabled={disabled}
        onChange={(e) => setState((s) => ({ ...s, sources: { ...s.sources, [field.key]: e.target.value } }))}
      />
    </details>
  );
  const defaultHint =
    defaultValue === undefined
      ? ""
      : ` Default: ${
          typeof defaultValue === "boolean"
            ? defaultValue
              ? "yes"
              : "no"
            : typeof defaultValue === "object" && !Array.isArray(defaultValue)
              ? Object.entries(defaultValue as Record<string, unknown>)
                  .map(([k, v]) => `${humanize(k)} ${scalarToInput(field, v)}`)
                  .join(", ")
              : scalarToInput(field, defaultValue)
        }${suffix === "%" ? "%" : ""}.`;

  if (field.kind === "boolean" || field.key in state.booleans) {
    return (
      <div className="space-y-1 rounded-md border border-slate-200 p-3">
        <div className="flex items-center justify-between gap-2">
          <CheckboxField
            label={field.label}
            checked={Boolean(state.booleans[field.key])}
            disabled={disabled}
            onChange={(v) => setState((s) => ({ ...s, booleans: { ...s.booleans, [field.key]: v } }))}
          />
          <AssumptionBadge />
        </div>
        <p className="text-xs text-slate-600">
          {field.help}
          {defaultHint}
        </p>
        {sourceInput}
      </div>
    );
  }

  const subKeys = Object.keys(state.inputs)
    .filter((k) => k.startsWith(`${field.key}.`))
    .map((k) => k.slice(field.key.length + 1));
  if (subKeys.length > 0) {
    return (
      <fieldset className="space-y-2 rounded-md border border-slate-200 p-3 sm:col-span-2">
        <legend className="flex items-center gap-2 px-1 text-sm font-medium text-slate-800">
          {label} <AssumptionBadge />
        </legend>
        <p className="text-xs text-slate-600">
          {field.help}
          {defaultHint}
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {subKeys.map((sub) => (
            <TextField
              key={sub}
              label={humanize(sub)}
              inputMode="decimal"
              disabled={disabled}
              value={state.inputs[`${field.key}.${sub}`] ?? ""}
              error={errors[`assumptions.${field.key}.${sub}`]}
              onChange={(e) =>
                setState((s) => ({ ...s, inputs: { ...s.inputs, [`${field.key}.${sub}`]: e.target.value } }))
              }
            />
          ))}
        </div>
        {sourceInput}
      </fieldset>
    );
  }

  return (
    <div className="space-y-1 rounded-md border border-slate-200 p-3">
      <TextField
        label={label}
        badge={<AssumptionBadge />}
        inputMode={field.kind === "list" ? "text" : "decimal"}
        disabled={disabled}
        value={state.inputs[field.key] ?? ""}
        error={errors[`assumptions.${field.key}`]}
        hint={`${field.help}${defaultHint}${isFractionPercent(field) ? " Enter as a percentage." : ""}`}
        onChange={(e) => setState((s) => ({ ...s, inputs: { ...s.inputs, [field.key]: e.target.value } }))}
      />
      {sourceInput}
    </div>
  );
}

export function ScenarioEditor({
  householdId,
  scenarioId,
  canEdit,
  reportingCurrency,
}: {
  householdId: string;
  /** "new" to create a scenario. */
  scenarioId: string;
  canEdit: boolean;
  reportingCurrency: string;
}) {
  const router = useRouter();
  const toast = useToast();
  const isNew = scenarioId === "new";
  const defaults = useApiQuery(() => endpoints.scenarioDefaults(), []);
  const scenario = useApiQuery(() => endpoints.getScenario(scenarioId), [scenarioId], !isNew);
  const presets = useApiQuery(() => endpoints.scenarioPresets(), []);
  const [state, setState] = useState<EditorState | null>(null);
  const [dirty, setDirty] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (defaults.data && (isNew || scenario.data) && state === null) {
      setState(buildState(defaults.data, isNew ? null : scenario.data));
    }
  }, [defaults.data, scenario.data, isNew, state]);

  const update = (fn: (s: EditorState) => EditorState) => {
    setState((s) => (s ? fn(s) : s));
    setDirty(true);
  };

  const groups = useMemo(() => (defaults.data ? groupFields(defaults.data.fields) : []), [defaults.data]);

  const save = async (): Promise<ScenarioOut | null> => {
    if (!defaults.data || !state) return null;
    const v: Record<string, string> = {};
    if (!state.name.trim()) v.name = "Enter a scenario name.";
    const built = buildAssumptions(defaults.data, isNew ? null : scenario.data, state);
    Object.assign(v, built.errors);
    setErrors(v);
    setFormError(null);
    if (Object.keys(v).length) {
      setFormError(new Error("Please fix the highlighted fields."));
      return null;
    }
    setSaving(true);
    try {
      const body = {
        name: state.name.trim(),
        description: state.description.trim() ? state.description.trim() : null,
        assumptions: built.assumptions,
      };
      const saved = isNew
        ? await endpoints.createScenario(householdId, body)
        : await endpoints.updateScenario(scenarioId, body);
      setDirty(false);
      toast.success(isNew ? "Scenario created" : "Scenario saved");
      if (isNew) router.replace(`/households/${householdId}/scenarios/${saved.id}`);
      else scenario.setData(saved);
      return saved;
    } catch (e) {
      if (e instanceof ApiError && e.isValidation) setErrors(e.fieldErrors);
      setFormError(e);
      return null;
    } finally {
      setSaving(false);
    }
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    await save();
  };

  const run = async () => {
    let id = scenarioId;
    if (isNew || dirty) {
      const saved = await save();
      if (!saved) return;
      id = saved.id;
    }
    setRunning(true);
    try {
      const result = await endpoints.runScenario(id);
      toast.success("Simulation complete");
      router.push(`/households/${householdId}/runs/${result.id}`);
    } catch (e) {
      setFormError(e);
      if (!isTermConflict(e)) {
        const d = describeError(e);
        toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
      }
    } finally {
      setRunning(false);
    }
  };

  const remove = async () => {
    setDeleting(true);
    try {
      await endpoints.deleteScenario(scenarioId);
      toast.success("Scenario deleted");
      router.replace(`/households/${householdId}/scenarios`);
    } catch (e) {
      const d = describeError(e);
      toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
      setDeleting(false);
    }
  };

  if (defaults.error) return <ErrorState error={defaults.error} onRetry={() => void defaults.reload()} />;
  if (!isNew && scenario.error) return <ErrorState error={scenario.error} onRetry={() => void scenario.reload()} />;
  if (!defaults.data || !state) return <LoadingBlock rows={6} label="Loading scenario…" />;

  const defaultValues = defaults.data.assumptions as unknown as Record<string, unknown>;
  const base = `/households/${householdId}/scenarios/${scenarioId}`;
  const disabled = !canEdit;

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link href={`/households/${householdId}/scenarios`} className="text-xs text-slate-600 hover:underline">
            ← Scenarios
          </Link>
          <h2 className="font-display mt-1 text-[1.35rem] leading-snug text-ink">{isNew ? "New scenario" : state.name || "Scenario"}</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          {!isNew && (
            <>
              <LinkButton href={`${base}/stress`} size="sm">
                Reverse stress
              </LinkButton>
              <LinkButton href={`${base}/prevention`} size="sm">
                Prevention planner
              </LinkButton>
              <a
                href="#blind-spots"
                className="inline-flex items-center rounded-md border border-line-strong bg-surface px-2 py-1 text-xs font-medium text-ink hover:bg-surface-muted"
              >
                Blind-spot check
              </a>
            </>
          )}
        </div>
      </div>

      <Notice title="Every value on this page is an assumption">
        Scenario inputs are modelling assumptions you control, not facts from your contracts. Contract terms come from
        approved constraints, and balances and scheduled obligations come from the household profile at run time.
      </Notice>

      <RunErrorState error={formError} />

      {canEdit && (presets.data?.length ?? 0) > 0 && (
        <Card title={<span className="flex items-center gap-2">Presets <AssumptionBadge /></span>}>
          <PresetPicker
            presets={presets.data ?? []}
            disabled={disabled}
            onApply={(p) => {
              update((s) => applyPreset(defaults.data!, s, p));
              setErrors({});
              toast.success(`Applied preset: ${p.name}`, p.label);
            }}
          />
        </Card>
      )}

      <Card title={<span className="flex items-center gap-2">Projection start (as-of date) <AssumptionBadge /></span>}>
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            label="As-of date"
            type="date"
            value={state.asOfDate}
            disabled={disabled}
            error={errors["assumptions.as_of_date"]}
            hint="The date of projection month 1. Fund Library terms in force on this date are used. Leave empty to use the date the analysis is run."
            onChange={(e) => update((s) => ({ ...s, asOfDate: e.target.value }))}
          />
          <p className="self-center text-xs text-ink-3">
            A term superseded by a newer document still applies before its end date, so an earlier as-of date can select the
            older term.
          </p>
        </div>
      </Card>

      <Card title="Scenario">
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            label="Name"
            value={state.name}
            required
            maxLength={160}
            disabled={disabled}
            error={errors.name}
            onChange={(e) => update((s) => ({ ...s, name: e.target.value }))}
          />
          <TextAreaField
            label="Description"
            value={state.description}
            maxLength={4000}
            disabled={disabled}
            error={errors.description}
            onChange={(e) => update((s) => ({ ...s, description: e.target.value }))}
          />
        </div>
      </Card>

      {groups.map((g) => (
        <Card key={g.group} title={<span className="flex items-center gap-2">{humanize(g.group)} <AssumptionBadge /></span>}>
          <div className="grid gap-3 sm:grid-cols-2">
            {g.fields.map((f) => (
              <FieldInput
                key={f.key}
                field={f}
                state={state}
                setState={update}
                errors={errors}
                disabled={disabled}
                defaultValue={defaultValues[f.key]}
              />
            ))}
          </div>
        </Card>
      ))}

      <Card title={<span className="flex items-center gap-2">FX rates <AssumptionBadge /></span>}>
        <p className="mb-3 text-sm text-slate-600">
          Units of the reporting currency ({reportingCurrency}) per 1 unit of each other currency held by the household.
        </p>
        {errors["assumptions.fx_rates"] && <p className="mb-2 text-xs font-medium text-red-700">{errors["assumptions.fx_rates"]}</p>}
        <div className="space-y-2">
          {state.fx.length === 0 && <p className="text-sm text-slate-600">No FX rates set.</p>}
          {state.fx.map((row, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
              <TextField
                label="Currency"
                value={row.currency}
                maxLength={3}
                disabled={disabled}
                error={errors[`fx.${i}.currency`] ?? errors[`assumptions.fx_rates.${row.currency}`]}
                onChange={(e) =>
                  update((s) => ({
                    ...s,
                    fx: s.fx.map((r, j) => (j === i ? { ...r, currency: e.target.value.toUpperCase() } : r)),
                  }))
                }
              />
              <TextField
                label={`Rate (${reportingCurrency} per unit)`}
                inputMode="decimal"
                value={row.rate}
                disabled={disabled}
                error={errors[`fx.${i}.rate`]}
                onChange={(e) =>
                  update((s) => ({ ...s, fx: s.fx.map((r, j) => (j === i ? { ...r, rate: e.target.value } : r)) }))
                }
              />
              <Button
                variant="ghost"
                size="sm"
                disabled={disabled}
                aria-label={`Remove FX rate ${row.currency || i + 1}`}
                onClick={() => update((s) => ({ ...s, fx: s.fx.filter((_, j) => j !== i) }))}
              >
                Remove
              </Button>
            </div>
          ))}
          <Button
            variant="secondary"
            size="sm"
            disabled={disabled}
            onClick={() => update((s) => ({ ...s, fx: [...s.fx, { currency: "", rate: "" }] }))}
          >
            Add FX rate
          </Button>
        </div>
      </Card>

      {canEdit && (
        <div className="sticky bottom-0 z-10 -mx-4 flex flex-wrap items-center gap-2 border-t border-slate-200 bg-white/95 px-4 py-3 sm:mx-0 sm:rounded-lg sm:border">
          <Button type="submit" loading={saving} disabled={running}>
            {isNew ? "Create scenario" : "Save scenario"}
          </Button>
          <Button variant="accent" onClick={run} loading={running} disabled={saving}>
            {isNew || dirty ? "Save & run simulation" : "Run simulation"}
          </Button>
          {dirty && <span className="text-xs text-slate-600">Unsaved changes</span>}
          {!isNew && (
            <Button variant="ghost" className="ml-auto text-red-700" onClick={() => setConfirmDelete(true)}>
              Delete scenario
            </Button>
          )}
        </div>
      )}

      <Dialog
        open={confirmDelete}
        title="Delete scenario?"
        onClose={() => setConfirmDelete(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={remove} loading={deleting}>
              Delete
            </Button>
          </>
        }
      >
        <p>Delete this scenario? This cannot be undone.</p>
      </Dialog>
    </form>
  );
}
