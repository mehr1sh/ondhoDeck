"""OndhoDeck - Contractual Liquidity Intelligence (hackathon prototype).

Run:  streamlit run app.py
"""
from __future__ import annotations

import html
import json
from dataclasses import asdict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.constraint_extractor import extract_rule_based, extract_with_llm
from src.demo_data import SCENARIO_NOTES, demo_scenario, load_demo_documents
from src.document_parser import normalize_text, parse_pdf_bytes
from src.export import bundle_json, constraints_csv, results_bundle, simulation_csv, simulation_frame
from src.llm_service import LLMError, get_config
from src.optimizer import CostAssumptions, plan_prevention
from src.reverse_stress import reverse_stress
from src.schemas import ContractConstraint, ReviewStatus, SourceType
from src.simulator import (
    ContractTerms, Scenario, simulate_contract_aware, simulate_naive, stress_usable_liquidity,
    terms_from_constraints,
)

st.set_page_config(page_title="OndhoDeck - Contractual Liquidity Intelligence", page_icon="◢",
                   layout="wide", initial_sidebar_state="expanded")

# --------------------------------------------------------------------------- #
# Styling
# --------------------------------------------------------------------------- #
C_AWARE, C_NAIVE, C_CRIT, C_OK = "#2a78d6", "#eb6834", "#d03b3b", "#2f7d32"
INK, INK2, GRID = "#0f172a", "#475569", "#e2e8f0"

st.markdown("""
<style>
:root { --lime:#a3e635; --lime-ink:#3f6212; --slate-900:#0f172a; --slate-700:#334155;
        --slate-500:#64748b; --slate-200:#e2e8f0; --surface:#ffffff; }
.block-container { padding-top: 3.2rem; padding-bottom: 3rem; max-width: 1400px; }
[data-testid="stSidebar"] { background: #1e293b; }
[data-testid="stSidebar"] * { color: #e2e8f0; }
[data-testid="stSidebar"] .stButton button { background:#a3e635; color:#0f172a; border:0; font-weight:700; }
[data-testid="stSidebar"] .stButton button:hover { background:#bef264; color:#0f172a; }
[data-testid="stSidebar"] .stButton button * { color:#0f172a !important; }
header[data-testid="stHeader"] { background: transparent; }
h1, h2, h3 { color: var(--slate-900); letter-spacing: -0.01em; }
.brand { font-size: 1.35rem; font-weight: 800; color: #f8fafc; line-height: 1.15; }
.brand span { color: var(--lime); }
.brand-sub { font-size: .78rem; color: #94a3b8; text-transform: uppercase; letter-spacing: .08em; }
.page-title { font-size: 1.6rem; font-weight: 800; margin: 0 0 .1rem 0; color: var(--slate-900); }
.page-sub { color: var(--slate-500); margin-bottom: 1rem; font-size: .92rem; }
.kpi { background: var(--surface); border: 1px solid var(--slate-200); border-left: 4px solid var(--lime);
       border-radius: 8px; padding: .8rem 1rem; height: 100%; }
.kpi.crit { border-left-color: #d03b3b; } .kpi.ok { border-left-color: #2f7d32; }
.kpi .lbl { font-size: .72rem; text-transform: uppercase; letter-spacing: .06em; color: var(--slate-500); font-weight: 700; }
.kpi .val { font-size: 1.65rem; font-weight: 800; color: var(--slate-900); margin-top: .15rem; font-variant-numeric: tabular-nums; }
.kpi .sub { font-size: .8rem; color: var(--slate-700); margin-top: .1rem; }
.pill { display:inline-block; padding: .12rem .55rem; border-radius: 999px; font-size: .75rem; font-weight: 700; }
.pill.ok { background:#dcfce7; color:#14532d; } .pill.crit { background:#fee2e2; color:#7f1d1d; }
.pill.warn { background:#fef3c7; color:#78350f; } .pill.info { background:#e0e7ff; color:#1e3a8a; }
.pill.lime { background:#ecfccb; color:#365314; }
.panel { background: var(--surface); border: 1px solid var(--slate-200); border-radius: 8px; padding: .9rem 1.1rem; margin-bottom: .8rem; }
.quote { border-left: 4px solid var(--lime); background:#f8fafc; padding:.7rem .9rem; font-family: Georgia, serif;
         font-size: .95rem; color: var(--slate-900); border-radius: 0 6px 6px 0; }
.meta { font-size: .8rem; color: var(--slate-500); }
mark { background: #d9f99d; padding: 0 .1rem; }
.banner { border-radius: 8px; padding: .7rem 1rem; margin: .3rem 0 1rem 0; font-size: .9rem; }
.banner.demo { background:#ecfccb; border:1px solid #bef264; color:#365314; }
.banner.crit { background:#fef2f2; border:1px solid #fecaca; color:#7f1d1d; }
.banner.ok { background:#f0fdf4; border:1px solid #bbf7d0; color:#14532d; }
div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] { border: 1px solid var(--slate-200); border-radius: 6px; }
@media (max-width: 640px) { .kpi .val { font-size: 1.3rem; } }
</style>
""", unsafe_allow_html=True)


def money(x: float | None, compact: bool = False) -> str:
    if x is None:
        return "-"
    if abs(x) < 0.5:
        x = 0.0
    sign = "−" if x < 0 else ""
    a = abs(x)
    if compact and a >= 1_000_000:
        return f"{sign}${a / 1e6:.2f}M"
    if compact and a >= 10_000:
        return f"{sign}${a / 1e3:.0f}K"
    return f"{sign}${a:,.0f}"


def esc(text: str) -> str:
    """Escape $ so Streamlit markdown doesn't treat '$...$' as LaTeX."""
    return text.replace("$", "\\$")


def kpi(col, label: str, value: str, sub: str = "", tone: str = "") -> None:
    col.markdown(f'<div class="kpi {tone}"><div class="lbl">{html.escape(label)}</div>'
                 f'<div class="val">{html.escape(value)}</div><div class="sub">{sub}</div></div>',
                 unsafe_allow_html=True)


def header(title: str, sub: str) -> None:
    st.markdown(f'<div class="page-title">{title}</div><div class="page-sub">{sub}</div>',
                unsafe_allow_html=True)


def style_fig(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=36, b=10), paper_bgcolor="white", plot_bgcolor="white",
        font=dict(color=INK, size=12), hoverlabel=dict(bgcolor="white", font_color=INK),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(color=INK2)))
    fig.update_xaxes(showgrid=False, linecolor=GRID, tickfont=dict(color=INK2))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont=dict(color=INK2))
    return fig


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #

@st.cache_resource(show_spinner="Parsing BREIT prospectus and sample contracts…")
def _demo_bundle():
    return load_demo_documents()


@st.cache_resource(show_spinner="Parsing PDF…")
def _parse_upload(data: bytes, name: str):
    return parse_pdf_bytes(data, name)


def reset_demo() -> None:
    docs, reports, msgs = _demo_bundle()
    st.session_state.scenario = demo_scenario().model_dump()
    st.session_state.constraints = [c.model_copy(deep=True) for r in reports for c in r.constraints]
    st.session_state.docs = dict(docs)
    st.session_state.reports = list(reports)
    st.session_state.load_messages = msgs
    st.session_state.costs = asdict(CostAssumptions())
    for k in list(st.session_state.keys()):
        if k.startswith("w_") or k.startswith("constraint_editor"):
            del st.session_state[k]


def clear_editor() -> None:
    """Drop pending data-editor deltas (they are keyed by row position)."""
    for k in [k for k in st.session_state.keys() if k.startswith("constraint_editor")]:
        del st.session_state[k]


if "scenario" not in st.session_state:
    reset_demo()

llm_cfg = get_config()


def current_scenario() -> Scenario:
    return Scenario.model_validate(st.session_state.scenario)


def current_terms() -> ContractTerms:
    return terms_from_constraints(st.session_state.constraints)


@st.cache_data(show_spinner=False)
def _cached_reverse(scenario_json: str, terms_json: str) -> dict:
    s = Scenario.model_validate_json(scenario_json)
    t = _terms_from_json(terms_json)
    r = reverse_stress(s, t)
    out = {k: v for k, v in r.__dict__.items() if k != "boundary_result"}
    out["boundary_rows"] = r.boundary_result.rows if r.boundary_result else None
    return out


@st.cache_data(show_spinner=False)
def _cached_plan(scenario_json: str, terms_json: str, costs_json: str) -> dict:
    s = Scenario.model_validate_json(scenario_json)
    t = _terms_from_json(terms_json)
    p = plan_prevention(s, t, CostAssumptions(**json.loads(costs_json)))
    return asdict(p)


def _terms_json(t: ContractTerms) -> str:
    d = asdict(t)
    d["relax"] = sorted(t.relax)
    d["interval_offer_calendar_months"] = list(t.interval_offer_calendar_months)
    return json.dumps(d, sort_keys=True)


def _terms_from_json(s: str) -> ContractTerms:
    d = json.loads(s)
    d["relax"] = frozenset(d["relax"])
    d["interval_offer_calendar_months"] = tuple(d["interval_offer_calendar_months"])
    return ContractTerms(**d)


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
PAGES = ["Portfolio Overview", "Contract Explorer", "Stress Simulation", "Reverse Stress Test",
         "Prevention Planner", "Export"]
with st.sidebar:
    st.markdown('<div class="brand">Ondho<span>Deck</span></div>'
                '<div class="brand-sub">Contractual Liquidity Intelligence</div>', unsafe_allow_html=True)
    st.write("")
    page = st.radio("Navigate", PAGES, label_visibility="collapsed", key="nav")
    st.divider()
    if llm_cfg.configured:
        st.markdown(f'<span class="pill lime">LLM extraction: ON</span><br><span style="font-size:.75rem">'
                    f'model {html.escape(llm_cfg.model)}</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="pill warn">DEMO MODE - no API key</span>', unsafe_allow_html=True)
        st.caption("Rule-based extraction over the real BREIT PDF + synthetic sample contracts. "
                   "Set ANTHROPIC_API_KEY to enable LLM extraction.")
    st.write("")
    if st.button("↺ Reset Demo Scenario", width="stretch"):
        reset_demo()
        st.rerun()
    st.caption("Synthetic household. Prototype for advisor review - not financial advice.")

scenario = current_scenario()
terms = current_terms()
naive = simulate_naive(scenario, terms)
aware = simulate_contract_aware(scenario, terms)


def cash_chart(naive_res, aware_res, show_reserve: bool = False) -> go.Figure:
    df_a, df_n = aware_res.to_frame(), naive_res.to_frame()
    fig = go.Figure()
    neg = df_a["ending_cash"].clip(upper=0)
    fig.add_trace(go.Scatter(x=df_a["label"], y=neg, fill="tozeroy", mode="none",
                             fillcolor="rgba(208,59,59,0.12)", name="Shortfall (contract-aware)",
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=df_n["label"], y=df_n["ending_cash"], name="Naive baseline (comparator)",
                             line=dict(color=C_NAIVE, width=2, dash="dash"), mode="lines",
                             hovertemplate="%{y:$,.0f}"))
    fig.add_trace(go.Scatter(x=df_a["label"], y=df_a["ending_cash"], name="Contract-aware model",
                             line=dict(color=C_AWARE, width=2.5), mode="lines+markers",
                             marker=dict(size=7, line=dict(color="white", width=2)),
                             hovertemplate="%{y:$,.0f}"))
    if show_reserve:
        fig.add_trace(go.Scatter(x=df_n["label"], y=df_n["naive_liquid_reserve"],
                                 name="Naive 'liquid reserve' (cash + haircut assets)",
                                 line=dict(color=C_NAIVE, width=1.5, dash="dot"), hovertemplate="%{y:$,.0f}"))
    fig.add_hline(y=0, line=dict(color=INK, width=1))
    if aware_res.first_shortfall_month:
        fm = aware_res.first_shortfall_month
        fig.add_annotation(x=df_a["label"][fm - 1], y=df_a["ending_cash"][fm - 1],
                           text=f"First shortfall: {money(-aware_res.shortfall_amount)}",
                           showarrow=True, arrowhead=0, ax=40, ay=40, font=dict(color=C_CRIT, size=12),
                           bgcolor="white", bordercolor=C_CRIT)
    fig.update_layout(hovermode="x unified", yaxis_title="Ending cash", yaxis_tickformat="$~s")
    return style_fig(fig)


PLOT_CONFIG = {"displayModeBar": False}


def naive_caption(res) -> str:
    sold = sum(r.get("asset_sales", 0.0) for r in res.rows)
    return (f"Naive comparator covers any deficit by instantly selling a fixed fraction of each asset "
            f"(sold {money(sold)} over 24 months), so its cash never drops below $0. It ignores fund gates, "
            f"settlement lags, SBL collateral calls, trading windows and the RSU withholding gap.")


def status_pill(res) -> str:
    if res.has_shortfall:
        return f'<span class="pill crit">✖ Shortfall from M{res.first_shortfall_month}</span>'
    return '<span class="pill ok">✔ Liquidity sufficient (24 mo)</span>'


# --------------------------------------------------------------------------- #
# A. Portfolio Overview
# --------------------------------------------------------------------------- #
if page == "Portfolio Overview":
    header("Portfolio Overview",
           "Synthetic household · 24-month stress horizon · every figure below is computed by the simulator "
           "from the current scenario and reviewed contract terms.")
    if not llm_cfg.configured:
        st.markdown('<div class="banner demo"><b>Demo Mode.</b> Contract terms were extracted deterministically '
                    'from the supplied BREIT prospectus and from clearly-labelled synthetic sample contracts. '
                    'Household figures are synthetic.</div>', unsafe_allow_html=True)

    c = st.columns([1, 1, 1, 1])
    with c[0]:
        dd = st.slider("Equity drawdown (scenario)", 0, 60, int(round(scenario.equity_drawdown * 100)), 1,
                       format="%d%%", key="w_overview_dd")
    if dd / 100 != scenario.equity_drawdown:
        st.session_state.scenario["equity_drawdown"] = dd / 100
        st.session_state.pop("w_equity_drawdown", None)
        st.rerun()
    with c[1]:
        window = st.selectbox("Liquidity window", [1, 2, 3, 6], index=2, format_func=lambda m: f"First {m} months")
    liq = stress_usable_liquidity(scenario, terms, window)

    k = st.columns(4)
    kpi(k[0], "Total paper asset value", money(scenario.total_paper_assets, True),
        "Cash, brokerage, REIT, interval fund, vested RSUs")
    kpi(k[1], f"Stress-usable liquidity ({window} mo)", money(liq["total"], True),
        f"vs naive {money(liq['naive_total'], True)} · {liq['total'] / scenario.total_paper_assets:.0%} of paper value")
    fm = aware.first_shortfall_month
    kpi(k[2], "First projected shortfall", f"Month {fm}" if fm else "None",
        f"Naive baseline: {('Month ' + str(naive.first_shortfall_month)) if naive.has_shortfall else 'none'}",
        "crit" if fm else "ok")
    kpi(k[3], "Shortfall amount", money(-aware.shortfall_amount, True) if fm else "$0",
        f"Peak deficit {money(aware.peak_shortfall, True)} over 24 months" if fm else "Cash stays ≥ $0",
        "crit" if fm else "ok")
    st.write("")

    left, right = st.columns([1.75, 1])
    with left:
        st.markdown(f"**Monthly ending cash** &nbsp; Naive {status_pill(naive)} &nbsp; "
                    f"Contract-aware {status_pill(aware)}", unsafe_allow_html=True)
        st.plotly_chart(cash_chart(naive, aware), width="stretch", config=PLOT_CONFIG)
        st.caption(esc(naive_caption(naive)))
        if fm:
            st.markdown(f'<div class="banner crit"><b>Month {fm}:</b> '
                        + " · ".join(html.escape(b) for b in aware.binding_in(fm)) + "</div>",
                        unsafe_allow_html=True)
    with right:
        st.markdown("**Portfolio composition** (pre-stress)")
        comp = pd.DataFrame({
            "Asset": ["Taxable brokerage", "Non-traded REIT", "Interval fund", "Cash", "Vested RSUs"],
            "Value": [scenario.brokerage, scenario.reit, scenario.interval_fund, scenario.cash, scenario.rsu_vested],
            "Liquidity rule": ["Pledged to SBL", "2%/mo · 5%/qtr gate", "Quarterly 5% offer", "Immediate",
                               "Trading windows"],
        }).sort_values("Value")
        fig = go.Figure(go.Bar(x=comp["Value"], y=comp["Asset"], orientation="h", marker_color=C_AWARE,
                               text=[money(v, True) for v in comp["Value"]], textposition="outside",
                               customdata=comp["Liquidity rule"],
                               hovertemplate="%{y}: %{x:$,.0f}<br>%{customdata}<extra></extra>"))
        fig.update_xaxes(range=[0, comp["Value"].max() * 1.25], tickformat="$~s")
        st.plotly_chart(style_fig(fig, 250), width="stretch", config=PLOT_CONFIG)
        st.markdown("**Stress-usable liquidity, first %d months**" % window)
        rows = [("Starting cash", liq["cash"]), ("REIT repurchases settled (gated)", liq["reit_proceeds"]),
                ("Interval fund repurchases settled", liq["interval_proceeds"]),
                ("Vested RSUs (if a window opens)", liq["rsu_sellable"]),
                ("Brokerage equity above SBL requirement", liq["brokerage_free_equity"]),
                ("SBL collateral calls due", liq["collateral_calls"]), ("Total", liq["total"])]
        st.dataframe(pd.DataFrame(rows, columns=["Component", "Amount"]).style.format({"Amount": money}),
                     hide_index=True, width="stretch")
        st.caption("Computed by running the contract-aware simulator with the household requesting its full "
                   "REIT and interval positions from month 1.")

# --------------------------------------------------------------------------- #
# B. Contract Explorer
# --------------------------------------------------------------------------- #
elif page == "Contract Explorer":
    header("Contract Explorer",
           "Liquidity terms extracted from documents, each tied to an exact quote and PDF page. "
           "Review, edit or reject before simulating.")
    for m in st.session_state.load_messages:
        st.info(m)

    with st.expander("Upload agreements (PDF) and extract constraints", expanded=False):
        files = st.file_uploader("PDF agreements", type=["pdf"], accept_multiple_files=True)
        if files:
            for f in files:
                doc = _parse_upload(f.getvalue(), f.name)
                cols = st.columns([3, 1.2, 1.2])
                status = (f"{len(doc.pages)} pages with text"
                          + (f" · {len(doc.failed_pages)} without text" if doc.failed_pages else ""))
                cols[0].markdown(f"**{html.escape(f.name)}**  \n<span class='meta'>{status}</span>",
                                 unsafe_allow_html=True)
                if doc.errors and not doc.pages:
                    cols[0].error(doc.errors[0])
                    continue
                run_llm = cols[1].button("Extract with LLM", key=f"llm_{doc.document_id}",
                                         disabled=not llm_cfg.configured,
                                         help=None if llm_cfg.configured else "Set ANTHROPIC_API_KEY to enable")
                run_rules = cols[2].button("Rule-based (no key)", key=f"rb_{doc.document_id}")
                report = None
                if run_llm:
                    with st.spinner("Retrieving relevant excerpts and extracting with the LLM…"):
                        try:
                            report = extract_with_llm(doc)
                        except LLMError as exc:
                            st.error(f"LLM extraction failed: {exc}  \nYou can continue with the rule-based "
                                     "extractor or Demo Mode.")
                if run_rules:
                    report = extract_rule_based(doc)
                if report is not None:
                    st.session_state.docs[doc.document_id] = doc
                    st.session_state.constraints = [c for c in st.session_state.constraints
                                                    if c.document_id != doc.document_id] + report.constraints
                    st.session_state.reports = [r for r in st.session_state.reports
                                                if r.document_id != doc.document_id] + [report]
                    clear_editor()
                    st.success(f"{len(report.constraints)} constraint(s) extracted from {f.name} "
                               f"({report.method.value}, {report.excerpts_used or 'all'} excerpts/pages).")
                    for msg in report.messages:
                        st.warning(msg)
        if not llm_cfg.configured:
            st.caption("LLM extraction is disabled because ANTHROPIC_API_KEY is not set. The rule-based "
                       "extractor recognises the clause families used in this demo only.")

    cons: list[ContractConstraint] = st.session_state.constraints
    if not cons:
        st.warning("No constraints loaded. Reset the demo or upload a document.")
        st.stop()

    docs_in = sorted({c.document_name for c in cons})
    fc = st.columns([2, 1, 1])
    doc_filter = fc[0].multiselect("Documents", docs_in, default=docs_in)
    n_review = sum(c.review_status == ReviewStatus.NEEDS_REVIEW for c in cons)
    fc[1].markdown(f"<br><span class='pill warn'>{n_review} need review</span>", unsafe_allow_html=True)
    if fc[2].button("Confirm all verified quotes"):
        for c in cons:
            if c.quote_verified and c.review_status == ReviewStatus.NEEDS_REVIEW:
                c.review_status = ReviewStatus.CONFIRMED
        clear_editor()
        st.rerun()

    shown = [c for c in cons if c.document_name in doc_filter]
    df = pd.DataFrame([{
        "id": c.constraint_id, "Document": c.document_name.replace(".pdf", ""),
        "Category": c.constraint_type.value.replace("_", " "), "Section": c.document_section or "",
        "Value": c.value,
        "Unit": c.unit or ("qualitative" if c.is_qualitative else ""), "Timing": c.timing or "",
        "PDF p.": c.pdf_page, "Printed p.": c.printed_page or "",
        "Source": c.source_type.value.replace("_", " "), "Quote verified": c.quote_verified,
        "Confidence": c.confidence.value, "Review": c.review_status.value,
    } for c in shown])
    edited = st.data_editor(
        df, key="constraint_editor_" + "|".join(doc_filter), hide_index=True, width="stretch", height=380,
        disabled=["id", "Document", "Category", "Section", "Unit", "Timing", "PDF p.", "Printed p.", "Source",
                  "Quote verified", "Confidence"],
        column_config={
            "id": None,
            "Value": st.column_config.NumberColumn("Value", help="Editable. Edits mark the term user-confirmed.",
                                                   format="%.4g"),
            "Review": st.column_config.SelectboxColumn("Review", options=[r.value for r in ReviewStatus]),
            "Quote verified": st.column_config.CheckboxColumn("Quote ✓"),
        })
    by_id = {c.constraint_id: c for c in cons}
    changed = False
    for _, row in edited.iterrows():
        c = by_id[row["id"]]
        new_val = None if pd.isna(row["Value"]) else float(row["Value"])
        if c.is_qualitative and new_val is not None and c.original_value is None:
            st.warning(f"'{c.description}' is a qualitative clause; a numeric value cannot be added to it. "
                       "Model discretionary effects as scenario assumptions instead.")
            continue
        if new_val != c.value:
            c.value = new_val
            c.review_status = ReviewStatus.EDITED
            c.source_type = SourceType.USER_CONFIRMED
            changed = True
        status = ReviewStatus(row["Review"])
        if status != c.review_status and not (changed and status == ReviewStatus.NEEDS_REVIEW):
            c.review_status = status
            if status == ReviewStatus.CONFIRMED and c.value != c.original_value:
                c.source_type = SourceType.USER_CONFIRMED
            changed = True
    if changed:
        st.rerun()

    st.markdown("#### Evidence inspector")
    pick = st.selectbox("Constraint", [c.constraint_id for c in shown],
                        format_func=lambda i: f"{by_id[i].document_name.replace('.pdf', '')} · "
                                              f"{by_id[i].description} (p.{by_id[i].pdf_page})")
    c = by_id[pick]
    left, right = st.columns([1.6, 1])
    with left:
        st.markdown(f'<div class="quote">“{html.escape(c.evidence_quote)}”</div>', unsafe_allow_html=True)
        printed = f" · printed page {html.escape(c.printed_page)}" if c.printed_page else ""
        corr = (f" · same clause also on PDF pages {', '.join(map(str, c.corroborating_pages[:8]))}"
                f"{'…' if len(c.corroborating_pages) > 8 else ''}" if c.corroborating_pages else "")
        section = f" · {html.escape(c.document_section)}" if c.document_section else ""
        st.markdown(f'<div class="meta">{html.escape(c.document_name)}{section} · PDF page {c.pdf_page}{printed}{corr}</div>',
                    unsafe_allow_html=True)
        doc = st.session_state.docs.get(c.document_id)
        if doc and doc.page(c.pdf_page):
            with st.expander(f"Show full text of PDF page {c.pdf_page}"):
                text = html.escape(normalize_text(doc.page(c.pdf_page).text))
                q = html.escape(normalize_text(c.evidence_quote))
                st.markdown(f"<div style='font-size:.85rem'>{text.replace(q, f'<mark>{q}</mark>')}</div>",
                            unsafe_allow_html=True)
    with right:
        val = ("qualitative - no numeric value" if c.is_qualitative
               else f"{c.value:g} {c.unit or ''}" + (f" (extracted: {c.original_value:g})"
                                                    if c.original_value is not None and c.value != c.original_value else ""))
        src_pill = {"source_backed": "info", "synthetic_document": "warn", "user_confirmed": "lime",
                    "scenario_assumption": "warn"}[c.source_type.value]
        st.markdown(f"""<div class="panel">
<b>{html.escape(c.description)}</b><br>
<span class="pill {src_pill}">{c.source_type.value.replace('_', ' ')}</span>
<span class="pill {'ok' if c.quote_verified else 'crit'}">{'quote verified in PDF' if c.quote_verified else 'quote NOT verified'}</span>
<span class="pill info">{c.extraction_method.value.replace('_', '-')}</span>
<span class="pill {'ok' if c.review_status.value in ('confirmed', 'edited') else 'warn' if c.review_status.value == 'needs_review' else 'crit'}">{c.review_status.value.replace('_', ' ')}</span>
<p style="margin:.6rem 0 .2rem"><b>Value:</b> {html.escape(val)}<br>
<b>Timing:</b> {html.escape(c.timing or '-')}<br>
<b>Conditions:</b> {html.escape(c.conditions or '-')}<br>
<b>Confidence:</b> {c.confidence.value}</p>
<p style="margin:.3rem 0 0"><b>Interpretation:</b> {html.escape(c.interpretation)}</p></div>""",
                    unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        if b1.button("✔ Confirm", width="stretch"):
            c.review_status = ReviewStatus.CONFIRMED
            clear_editor()
            st.rerun()
        if b2.button("✖ Reject", width="stretch"):
            c.review_status = ReviewStatus.REJECTED
            clear_editor()
            st.rerun()

    st.markdown("#### Terms the simulator will use")
    tdf = pd.DataFrame([{"Term": k, "Value": getattr(terms, k), "Provenance": v}
                        for k, v in terms.provenance.items()])
    tdf["Value"] = tdf["Value"].astype(str)
    st.dataframe(tdf, hide_index=True, width="stretch")
    st.caption("Rejected constraints are ignored; their terms fall back to labelled default assumptions. "
               "Qualitative clauses (pro rata, board discretion) never become numbers - their effect is set "
               "through the scenario assumptions on the Stress Simulation page.")

# --------------------------------------------------------------------------- #
# C. Stress Simulation
# --------------------------------------------------------------------------- #
elif page == "Stress Simulation":
    header("Stress Simulation", "24-month deterministic monthly accounting. Edit inputs; results update immediately.")
    sc = st.session_state.scenario

    def num(col, label, field, step=1000.0, fmt="%.0f", help=None, minv=0.0, maxv=None):
        v = col.number_input(label, value=float(sc[field]), step=step, format=fmt, help=help,
                             key=f"w_{field}", min_value=minv, max_value=maxv)
        sc[field] = v

    def pct(col, label, field, maxv=100, help=None):
        v = col.slider(label, 0, maxv, int(round(sc[field] * 100)), format="%d%%", key=f"w_{field}", help=help)
        sc[field] = v / 100

    def intin(col, label, field, lo=1, hi=24, help=None):
        sc[field] = int(col.number_input(label, lo, hi, int(sc[field]), key=f"w_{field}", help=help))

    with st.expander("Market stress  ·  scenario assumption", expanded=True):
        c = st.columns(4)
        pct(c[0], "Equity drawdown at trough", "equity_drawdown", 60)
        intin(c[1], "Months to trough", "months_to_trough", 1, 12)
        intin(c[2], "Months held at trough", "trough_hold_months", 0, 18)
        pct(c[3], "Drawdown recovered by M24", "recovery_share")
        st.caption(SCENARIO_NOTES["stress"] + " " + SCENARIO_NOTES["betas"]
                   + f" Betas: brokerage {sc['beta_brokerage']}, RSU {sc['beta_rsu']}, REIT NAV "
                     f"{sc['beta_reit_nav']}, interval NAV {sc['beta_interval_nav']}.")
    with st.expander("Household, holdings & obligations  ·  synthetic", expanded=False):
        c = st.columns(4)
        num(c[0], "Cash reserve", "cash")
        num(c[1], "Taxable brokerage (pledged)", "brokerage")
        num(c[2], "Non-traded REIT", "reit")
        num(c[3], "Interval fund", "interval_fund")
        c = st.columns(4)
        num(c[0], "Vested RSUs", "rsu_vested")
        num(c[1], "Monthly income (net)", "monthly_income", 500.0)
        num(c[2], "Core expenses / month", "monthly_core_expenses", 500.0)
        num(c[3], "Discretionary / month", "monthly_discretionary", 500.0)
        c = st.columns(4)
        num(c[0], "SBL loan balance", "sbl_loan_balance")
        call = sc["capital_calls"][0] if sc["capital_calls"] else {"month": 4, "amount": 0.0}
        amt = c[1].number_input("Capital call amount", value=float(call["amount"]), step=5000.0, format="%.0f",
                                key="w_cc_amount", min_value=0.0)
        mon = int(c[2].number_input("Capital call month", 1, 24, int(call["month"]), key="w_cc_month"))
        sc["capital_calls"] = [{"month": mon, "amount": amt}] + sc["capital_calls"][1:]
        num(c[3], "RSU vest value (pre-stress)", "rsu_vest_value_prestress")
        c = st.columns(4)
        intin(c[0], "RSU vest month", "rsu_vest_month")
        pct(c[1], "Effective tax rate on RSU income", "rsu_effective_tax_rate",
            help="Scenario assumption: combined marginal federal + state rate")
        intin(c[2], "RSU tax true-up month", "rsu_tax_due_month")
        num(c[3], "Cash floor in RSU windows (months)", "rsu_window_cash_floor_months", 1.0, "%.0f",
            help="Household policy assumption: while a trading window is open, sell vested RSUs to keep cash at "
                 "this many months of net spending.", maxv=24.0)
        c = st.columns(4)
        sc["reit_shares_held_over_one_year"] = c[0].checkbox("REIT shares held > 1 year",
                                                             sc["reit_shares_held_over_one_year"], key="w_reit_1y")
        st.caption(SCENARIO_NOTES["holdings"] + " " + SCENARIO_NOTES["capital_calls"] + " " + SCENARIO_NOTES["rsu"])
    with st.expander("Redemption requests & fund-demand stress assumptions", expanded=True):
        c = st.columns(4)
        num(c[0], "REIT repurchase target ($)", "reit_redemption_target", 5000.0)
        intin(c[1], "First REIT request month", "reit_request_start_month")
        num(c[2], "Interval fund tender target ($)", "interval_redemption_target", 5000.0)
        c = st.columns(4)
        num(c[0], "REIT demand, no stress (% NAV/mo)", "reit_base_demand_pct", 0.1, "%.1f",
            help=SCENARIO_NOTES["demand"])
        num(c[1], "REIT demand per 100% drawdown (% NAV)", "reit_demand_sensitivity", 1.0, "%.1f",
            help=SCENARIO_NOTES["demand"])
        pct(c[2], "Board fills share of cap", "reit_board_fill_factor", help=SCENARIO_NOTES["board"])
        num(c[3], "Interval tender demand per 100% DD (%)", "interval_demand_sensitivity", 1.0, "%.1f")
        dd_now = sc["equity_drawdown"]
        implied = sc["reit_base_demand_pct"] + sc["reit_demand_sensitivity"] * dd_now
        st.markdown(f'<span class="pill warn">SCENARIO ASSUMPTION</span> At the trough, aggregate REIT repurchase '
                    f'demand is <b>{implied:.1f}% of NAV/month</b> versus the 2% monthly cap → implied pro-rata fill '
                    f'≈ <b>{min(1, terms.reit_monthly_cap_pct * sc["reit_board_fill_factor"] / max(implied, 1e-9)):.0%}</b> '
                    f'in the first two months of a quarter. The prospectus does not disclose future fill rates.',
                    unsafe_allow_html=True)

    scenario = current_scenario()
    naive = simulate_naive(scenario, terms)
    aware = simulate_contract_aware(scenario, terms)

    k = st.columns(4)
    kpi(k[0], "Contract-aware: first shortfall", f"Month {aware.first_shortfall_month}" if aware.has_shortfall else "None",
        money(-aware.shortfall_amount) if aware.has_shortfall else "cash stays ≥ $0", "crit" if aware.has_shortfall else "ok")
    kpi(k[1], "Naive: first shortfall", f"Month {naive.first_shortfall_month}" if naive.has_shortfall else "None",
        money(-naive.shortfall_amount) if naive.has_shortfall else "cash stays ≥ $0", "crit" if naive.has_shortfall else "ok")
    kpi(k[2], "Contract-aware minimum cash", money(aware.min_cash, True), "lowest month-end balance")
    kpi(k[3], "Fund proceeds received (24 mo)",
        money(sum(r["reit_proceeds"] + r["interval_proceeds"] for r in aware.rows), True),
        "REIT + interval fund, after gates & fees")
    st.write("")
    st.plotly_chart(cash_chart(naive, aware, show_reserve=True), width="stretch", config=PLOT_CONFIG)
    st.caption(esc(naive_caption(naive)))

    view = st.radio("Monthly detail", ["Contract-aware model", "Naive baseline"], horizontal=True)
    res = aware if view.startswith("Contract") else naive
    if view.startswith("Naive"):
        st.caption("Naive baseline = simplified comparator: a fixed fraction of each asset is treated as "
                   "instantly saleable; it ignores fund gates, settlement lags, SBL collateral calls, trading "
                   "windows and the RSU withholding gap. It is not a model of any commercial planning tool.")
    df = simulation_frame(res)
    cols = ["label", "beginning_cash", "income", "expenses", "debt_service", "taxes", "capital_call",
            "collateral_call", "reit_fill_rate", "reit_proceeds", "interval_proceeds", "rsu_sale_proceeds",
            "brokerage_sale_proceeds", "sbl_draw", "asset_sales", "ending_cash", "shortfall", "binding_constraints"]
    df = df[[c for c in cols if c in df.columns]]
    money_cols = [c for c in df.columns if c not in ("label", "reit_fill_rate", "binding_constraints")]
    sty = df.style.format({**{c: money for c in money_cols}, "reit_fill_rate": lambda v: "-" if pd.isna(v) else f"{v:.0%}"})
    sty = sty.map(lambda v: "color:#b91c1c;font-weight:700" if isinstance(v, (int, float)) and v < -0.5 else "",
                  subset=["ending_cash"])
    nice = {"label": "Month", "beginning_cash": "Begin cash", "income": "Income", "expenses": "Expenses",
            "debt_service": "SBL interest", "taxes": "Taxes", "capital_call": "Capital call",
            "collateral_call": "Collateral call", "reit_fill_rate": "REIT fill", "reit_proceeds": "REIT proceeds",
            "interval_proceeds": "Interval proceeds", "rsu_sale_proceeds": "RSU sales",
            "brokerage_sale_proceeds": "Brokerage sales", "sbl_draw": "SBL draw", "asset_sales": "Asset sales",
            "ending_cash": "End cash", "shortfall": "Shortfall"}
    cfg = {k: v for k, v in nice.items() if k in df.columns}
    cfg["binding_constraints"] = st.column_config.TextColumn("Binding constraints / events", width="large")
    st.dataframe(sty, hide_index=True, width="stretch", height=460, column_config=cfg)

# --------------------------------------------------------------------------- #
# D. Reverse Stress Test
# --------------------------------------------------------------------------- #
elif page == "Reverse Stress Test":
    header("Reverse Stress Test", "The mildest equity drawdown at which the household's cash first goes negative, "
                                  "holding every other input fixed.")
    with st.spinner("Searching drawdown grid…"):
        rs = _cached_reverse(scenario.model_dump_json(), _terms_json(terms))
    st.caption(rs["method"])
    if not rs["found"]:
        st.markdown(f'<div class="banner ok"><b>No failure found</b> for any drawdown up to '
                    f'{rs["last_safe_drawdown"]:.0%} with the current inputs.</div>', unsafe_allow_html=True)
    else:
        k = st.columns(4)
        kpi(k[0], "Failure boundary (equity drawdown)", f"{rs['boundary_drawdown']:.1%}",
            f"passes at {rs['last_safe_drawdown']:.1%}" if rs["last_safe_drawdown"] is not None
            else "fails even with no market stress", "crit")
        kpi(k[1], "First shortfall month", f"Month {rs['first_shortfall_month']}", "at the boundary", "crit")
        kpi(k[2], "Shortfall at boundary", money(-rs["shortfall_amount"]), "first month deficit", "crit")
        kpi(k[3], "Current scenario", f"{scenario.equity_drawdown:.0%} drawdown",
            "fails" if aware.has_shortfall else "passes", "crit" if aware.has_shortfall else "ok")
        if not rs["grid_monotone"]:
            st.warning("Pass/fail was not monotone in drawdown on the grid - the boundary shown is the first "
                       "failing grid point, not an exact threshold.")
    st.write("")
    left, right = st.columns([1.3, 1])
    with left:
        g = pd.DataFrame(rs["grid"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=g["equity_drawdown"], y=g["min_cash"], mode="lines+markers",
                                 line=dict(color=C_AWARE, width=2), marker=dict(size=6),
                                 name="Minimum month-end cash", hovertemplate="DD %{x:.0%}: %{y:$,.0f}<extra></extra>"))
        fig.add_hline(y=0, line=dict(color=INK, width=1))
        if rs["found"]:
            fig.add_vline(x=rs["boundary_drawdown"], line=dict(color=C_CRIT, dash="dash"),
                          annotation_text=f"boundary {rs['boundary_drawdown']:.1%}",
                          annotation_font_color=C_CRIT)
        fig.update_layout(xaxis_title="Equity drawdown at trough", yaxis_title="Minimum cash (contract-aware)",
                          xaxis_tickformat=".0%", yaxis_tickformat="$~s", showlegend=False)
        st.plotly_chart(style_fig(fig, 340), width="stretch", config=PLOT_CONFIG)
    with right:
        if rs["found"]:
            st.markdown("**Constraints responsible** (counterfactual: rule removed, all else equal)")
            att = pd.DataFrame(rs["attribution"])[["constraint", "shortfall_reduction", "removes_shortfall"]]
            st.dataframe(att.style.format({"shortfall_reduction": money}), hide_index=True,
                         width="stretch",
                         column_config={"constraint": "Contractual rule", "shortfall_reduction":
                                        "Peak deficit avoided", "removes_shortfall": "Removes shortfall alone?"})
            st.markdown("**Binding in the failure month**")
            for b in rs["binding_constraints"]:
                st.markdown(f"- {esc(b)}")
    if rs["found"]:
        st.markdown("**Key monthly events leading to failure** (at the boundary drawdown)")
        ev = pd.DataFrame(rs["key_events"])
        st.dataframe(ev.style.format({c: money for c in ev.columns if c not in ("month", "binding")}),
                     hide_index=True, width="stretch", column_config={
                         "month": "Month", "beginning_cash": "Begin cash", "net_household_flow": "Household net",
                         "capital_call": "Capital call", "taxes": "Taxes", "collateral_call": "Collateral call",
                         "fund_proceeds": "Fund proceeds", "other_sales_and_draws": "RSU/brokerage/SBL",
                         "ending_cash": "End cash",
                         "binding": st.column_config.TextColumn("Binding constraints", width="large")})

# --------------------------------------------------------------------------- #
# E. Prevention Planner
# --------------------------------------------------------------------------- #
elif page == "Prevention Planner":
    header("Prevention Planner", "Ranked, costed actions the advisor can take now - before the stress - "
                                 "evaluated on the same deterministic simulator. The advisor decides.")
    with st.expander("Cost assumptions (editable - not market quotes)"):
        cs = st.session_state.costs
        c = st.columns(5)
        for col, (k, label) in zip(c, [("sale_tax_drag", "Tax+trading per $ sold"), ("cash_drag", "Cash drag per $"),
                                       ("reit_forgone_return", "REIT forgone return"),
                                       ("withholding_time_value", "Withholding time value"),
                                       ("discretionary_weight", "Spending-cut weight")]):
            cs[k] = col.number_input(label, 0.0, 1.0, float(cs[k]), 0.01, format="%.2f", key=f"w_cost_{k}")
    if not aware.has_shortfall:
        st.markdown('<div class="banner ok"><b>No shortfall in the current scenario.</b> Increase the drawdown or '
                    'use the Reverse Stress Test boundary to explore prevention options.</div>', unsafe_allow_html=True)
        if st.button("Set scenario to the reverse-stress boundary"):
            rs = _cached_reverse(scenario.model_dump_json(), _terms_json(terms))
            if rs["found"]:
                st.session_state.scenario["equity_drawdown"] = min(0.95, rs["boundary_drawdown"])
                st.session_state.pop("w_equity_drawdown", None)
                st.rerun()
    else:
        with st.spinner("Evaluating options and solving the linear programme…"):
            plan = _cached_plan(scenario.model_dump_json(), _terms_json(terms), json.dumps(st.session_state.costs))
        k = st.columns(4)
        kpi(k[0], "Baseline first shortfall", f"Month {plan['baseline_first_shortfall']}",
            f"peak deficit {money(plan['baseline_peak_shortfall'])}", "crit")
        kpi(k[1], "Cost of doing nothing", money(plan["forced_liquidation_cost"]),
            "forced sale at the trough (est.)", "crit")
        kpi(k[2], "Optimised plan cost", money(plan["combined_cost"]),
            "verified by re-simulation" if plan["combined_verified"] else "NOT verified - see notes",
            "ok" if plan["combined_verified"] else "crit")
        kpi(k[3], "Plan minimum cash", money(plan["combined_min_cash"]),
            "no shortfall" if plan["combined_first_shortfall"] is None else f"shortfall M{plan['combined_first_shortfall']}",
            "ok" if plan["combined_first_shortfall"] is None else "crit")
        st.caption(esc(plan["forced_liquidation_note"]))
        st.write("")
        st.markdown("**Ranked single actions** (smallest amount that removes the shortfall on its own)")
        opts = pd.DataFrame(plan["options"])
        opts["Fixes alone"] = opts["feasible_alone"].map({True: "✔ yes", False: "✖ no (shown at cap)"})
        opts["New first shortfall"] = opts["first_shortfall_after"].apply(lambda v: "none" if pd.isna(v) else f"M{int(v)}")
        opts["Amount"] = opts.apply(lambda r: f"{r['amount']:.0%}" if r["unit"] == "rate pts" else money(r["amount"]), axis=1)
        show = opts[["name", "Amount", "unit", "cost", "liquidity_benefit", "New first shortfall", "Fixes alone",
                     "cost_basis", "constraints"]]
        st.dataframe(show.style.format({"cost": money, "liquidity_benefit": lambda v: "+" + money(v)}), hide_index=True,
                     width="stretch", column_config={
                         "name": "Option", "unit": "Unit", "cost": "Assumed cost",
                         "liquidity_benefit": "Min-cash improvement", "cost_basis": "Cost basis",
                         "constraints": st.column_config.TextColumn("Relevant constraints", width="large")})
        st.markdown("**Recommended combination** - `scipy.optimize.linprog` (HiGHS) on simulator-measured "
                    "sensitivities, verified by re-simulation")
        st.markdown(f'<span class="pill info">Source: {html.escape(plan["combined_source"])}</span>',
                    unsafe_allow_html=True)
        if plan["combined"]:
            comb = pd.DataFrame(plan["combined"])
            comb["Amount"] = comb.apply(lambda r: f"{r['amount']:.1%}" if r["unit"] == "rate pts" else money(r["amount"]), axis=1)
            st.dataframe(comb[["lever", "Amount", "unit", "cost", "cost_basis", "constraints"]]
                         .style.format({"cost": money}), hide_index=True, width="stretch",
                         column_config={"lever": "Action", "cost": "Assumed cost", "unit": "Unit",
                                        "cost_basis": "Cost basis",
                                        "constraints": st.column_config.TextColumn("Relevant constraints",
                                                                                   width="large")})
        st.caption(f"LP status: {plan['lp_status']}. The simulator is non-linear (gates, collateral calls), so the "
                   "LP is solved on finite-difference sensitivities and re-run until the re-simulated plan holds "
                   "(max 5 rounds). Costs are the assumptions above.")
        c1, c2 = st.columns([1, 3])
        if c1.button("Apply optimised plan to scenario", type="primary", disabled=not plan["combined"]):
            for r in plan["combined"]:
                st.session_state.scenario[r["field"]] = r["amount"]
            st.rerun()
        c2.caption("Applies the plan's lever amounts to the scenario so every page reflects it. Reset Demo "
                   "Scenario (sidebar) clears them.")
    active = {k: v for k, v in st.session_state.scenario.items() if k.startswith("lever_") and v}
    if active:
        st.info(esc("Active prevention levers in the scenario: " + ", ".join(
            f"{k.replace('lever_', '').replace('_', ' ')} = {v:.0%}" if "withholding" in k else
            f"{k.replace('lever_', '').replace('_', ' ')} = {money(v)}" for k, v in active.items())))
        if st.button("Clear prevention levers"):
            for k in active:
                st.session_state.scenario[k] = 0.0
            st.rerun()

# --------------------------------------------------------------------------- #
# F. Export
# --------------------------------------------------------------------------- #
elif page == "Export":
    header("Export", "Download reviewed constraints and simulation results.")
    cons = st.session_state.constraints
    rs = _cached_reverse(scenario.model_dump_json(), _terms_json(terms))
    rs_export = {k: v for k, v in rs.items() if k != "boundary_rows"}
    plan = (_cached_plan(scenario.model_dump_json(), _terms_json(terms), json.dumps(st.session_state.costs))
            if aware.has_shortfall else None)
    bundle = results_bundle(scenario, terms, cons, naive, aware, rs_export, plan)
    c = st.columns(4)
    c[0].download_button("Constraints (CSV)", constraints_csv(cons), "ondhodeck_constraints.csv", "text/csv",
                         width="stretch")
    c[1].download_button("Constraints (JSON)", json.dumps([x.model_dump(mode="json") for x in cons], indent=2),
                         "ondhodeck_constraints.json", "application/json", width="stretch")
    c[2].download_button("Monthly simulation (CSV)", simulation_csv(naive, aware), "ondhodeck_simulation.csv",
                         "text/csv", width="stretch")
    c[3].download_button("Full results bundle (JSON)", bundle_json(bundle), "ondhodeck_results.json",
                         "application/json", width="stretch")
    st.write("")
    st.markdown("**Bundle summary**")
    st.json(bundle["results"])
    st.caption(bundle["disclaimer"])
