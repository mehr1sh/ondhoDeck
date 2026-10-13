import pytest

from app.engine.demo_data import demo_scenario
from app.engine.simulator import (
    HORIZON_MONTHS,
    ContractTerms,
    Scenario,
    pro_rata_fill,
    reit_fund_capacity_pct,
    simulate_contract_aware,
    simulate_naive,
    stress_usable_liquidity,
)


def test_demo_assets_sum_to_1_8m():
    s = demo_scenario()
    assert s.total_paper_assets == pytest.approx(1_800_000)
    assert (s.brokerage, s.reit, s.interval_fund, s.rsu_vested, s.cash) == (600_000, 500_000, 300_000, 150_000, 250_000)


def test_monthly_capacity_respects_2pct_cap():
    assert reit_fund_capacity_pct(2.0, 5.0, 0.0) == 2.0
    # demand far above cap -> fund executes at most 2% of NAV
    fill = pro_rata_fill(10.0, reit_fund_capacity_pct(2.0, 5.0, 0.0))
    assert fill * 10.0 == pytest.approx(2.0)


def test_quarterly_capacity_respects_5pct_and_updates_after_prior_repurchases():
    used = 0.0
    executed = []
    for _ in range(3):  # three months of a quarter, demand always 10%
        cap = reit_fund_capacity_pct(2.0, 5.0, used)
        ex = min(10.0, cap)
        used += ex
        executed.append(ex)
    assert executed == pytest.approx([2.0, 2.0, 1.0])  # third month only has 1% left
    assert sum(executed) == pytest.approx(5.0)
    assert reit_fund_capacity_pct(2.0, 5.0, 5.0) == 0.0


def test_pro_rata_fill_when_oversubscribed_and_full_fill_when_not():
    assert pro_rata_fill(8.0, 2.0) == pytest.approx(0.25)
    assert pro_rata_fill(1.5, 2.0) == 1.0
    # every requester gets the same proportion: household request size does not change its fill
    assert pro_rata_fill(8.0, 2.0) * 100_000 == pytest.approx(25_000)


def test_simulator_quarter_cap_in_household_fills():
    s = demo_scenario().model_copy(update={"equity_drawdown": 0.30, "reit_redemption_target": 500_000})
    res = simulate_contract_aware(s, ContractTerms())
    fills = [r["reit_fill_rate"] for r in res.rows[:3]]
    # months 1-3 are one calendar quarter; month 3 capacity is the 1% quarterly remainder
    demand3 = s.reit_base_demand_pct + s.reit_demand_sensitivity * 0.30
    assert fills[2] == pytest.approx(1.0 / demand3)
    assert fills[2] < fills[1]


def test_simulator_runs_exactly_24_months():
    s = demo_scenario()
    for res in (simulate_contract_aware(s), simulate_naive(s)):
        assert len(res.rows) == HORIZON_MONTHS == 24
        assert [r["month"] for r in res.rows] == list(range(1, 25))


def test_cash_accounting_identity_and_first_shortfall():
    s = demo_scenario()
    res = simulate_contract_aware(s)
    for r in res.rows:
        expected = (r["beginning_cash"] + r["income"] - r["expenses"] - r["debt_service"] - r["taxes"]
                    - r["capital_call"] - r["collateral_call"] + r["reit_proceeds"] + r["interval_proceeds"]
                    + r["rsu_sale_proceeds"] + r["brokerage_sale_proceeds"] + r["sbl_draw"])
        assert r["ending_cash"] == pytest.approx(expected, abs=1e-6)
    negatives = [r["month"] for r in res.rows if r["ending_cash"] < -0.5]
    assert res.first_shortfall_month == (negatives[0] if negatives else None)
    if negatives:
        assert res.shortfall_amount == pytest.approx(-res.rows[negatives[0] - 1]["ending_cash"])


def test_no_shortfall_without_stress_or_obligations():
    s = Scenario(equity_drawdown=0.0, capital_calls=[], rsu_vests=[])
    res = simulate_contract_aware(s)
    assert res.first_shortfall_month is None
    assert res.shortfall_amount == 0.0


def test_demo_naive_vs_contract_aware():
    s = demo_scenario()
    naive, aware = simulate_naive(s), simulate_contract_aware(s)
    assert not naive.has_shortfall
    assert aware.has_shortfall
    assert aware.min_cash < naive.min_cash


def test_board_discretion_assumption_reduces_fills():
    s = demo_scenario()
    full = simulate_contract_aware(s)
    half = simulate_contract_aware(s.model_copy(update={"reit_board_fill_factor": 0.5}))
    assert sum(r["reit_proceeds"] for r in half.rows) < sum(r["reit_proceeds"] for r in full.rows)


def test_stress_usable_liquidity_components_add_up():
    liq = stress_usable_liquidity(demo_scenario(), ContractTerms(), 3)
    parts = (liq["cash"] + liq["reit_proceeds"] + liq["interval_proceeds"] + liq["rsu_sellable"]
             + liq["brokerage_free_equity"] + liq["collateral_calls"])
    assert liq["total"] == pytest.approx(parts)
    assert liq["total"] < liq["naive_total"]
