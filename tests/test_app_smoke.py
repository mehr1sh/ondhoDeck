"""Headless smoke test: every page renders without exceptions in Demo Mode."""
import pytest
from streamlit.testing.v1 import AppTest

PAGES = ["Portfolio Overview", "Contract Explorer", "Stress Simulation", "Reverse Stress Test",
         "Prevention Planner", "Export"]


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    at = AppTest.from_file("../app.py", default_timeout=180)
    at.run()
    return at


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(app, page, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app.sidebar.radio(key="nav").set_value(page).run()
    assert not app.exception, [e.value for e in app.exception]
    text = " ".join(m.value for m in app.markdown)
    assert page in text


def test_overview_kpis_come_from_simulator(app):
    app.sidebar.radio(key="nav").set_value("Portfolio Overview").run()
    text = " ".join(m.value for m in app.markdown)
    assert "Month 4" in text and "$1.80M" in text


def test_reset_restores_demo(app):
    app.session_state["scenario"]["equity_drawdown"] = 0.05
    app.sidebar.button[0].click().run()
    assert app.session_state["scenario"]["equity_drawdown"] == 0.25
    assert not app.exception


def test_changing_inputs_changes_results(app):
    app.sidebar.radio(key="nav").set_value("Stress Simulation").run()
    before = " ".join(m.value for m in app.markdown)
    app.slider(key="w_equity_drawdown").set_value(10).run()
    after = " ".join(m.value for m in app.markdown)
    assert not app.exception
    assert "Month 4" in before and before != after
    assert app.session_state["scenario"]["equity_drawdown"] == 0.10
