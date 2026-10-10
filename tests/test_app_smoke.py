"""Runs every Streamlit page headlessly and checks nothing raises."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["app.py", "pages/1_Product_Analysis.py", "pages/2_Ingredient_Database.py",
         "pages/3_Report_History.py", "pages/4_Educational_Resources.py", "pages/5_About_and_Safety.py"]


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    import config
    import streamlit as st
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "smoke.db")


@pytest.mark.parametrize("page", PAGES)
def test_page_runs(page):
    at = AppTest.from_file(str(ROOT / page), default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]


def test_manual_analysis_flow():
    at = AppTest.from_file(str(ROOT / "pages/1_Product_Analysis.py"), default_timeout=30).run()
    at.text_area(key="ingredients_text").set_value("Water, preservative (sodium benzoate), Aspartme").run()
    next(b for b in at.button if b.label == "Analyze ingredients").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Sodium benzoate" in e.label for e in at.expander)
    assert any("Aspartme" in c.label for c in at.checkbox)


def test_symptom_text_shows_urgent_banner():
    at = AppTest.from_file(str(ROOT / "pages/1_Product_Analysis.py"), default_timeout=30).run()
    at.text_area(key="symptom_text").set_value("my child swallowed some").run()
    assert any("Urgent medical evaluation" in e.value for e in at.error)
