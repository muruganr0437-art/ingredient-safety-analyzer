"""Shared Streamlit helpers: page setup, disclaimer, risk badges, ingredient card, DB access."""
from __future__ import annotations

import streamlit as st

import config
from database import db
from services import report_service as rs
from services.safety_service import URGENT_GUIDANCE, load_emergency_resources

# Text label + symbol + colour: meaning never relies on colour alone. No green "safe" badge exists.
RISK_STYLE = {
    rs.RISK_NONE: ("🔵", "No specific concern identified in the available data (this is NOT a safety guarantee)"),
    rs.RISK_POTENTIAL: ("🟠", "Potential concern under particular conditions"),
    rs.RISK_ASSESS: ("🟡", "Additional assessment needed"),
    rs.RISK_URGENT: ("🔴", "Urgent medical evaluation recommended"),
}

_CSS = """
<style>
.block-container {max-width: 1100px; padding-top: 1.5rem;}
@media (max-width: 640px) {.block-container {padding: 1rem 0.6rem;} h1 {font-size: 1.6rem !important;}}
.stDownloadButton button, .stButton button {min-height: 2.6rem;}
</style>
"""


@st.cache_resource
def _init_database() -> bool:
    conn = db.get_connection()
    try:
        db.init_db(conn)
    finally:
        conn.close()
    return True


def setup_page(title: str, icon: str) -> None:
    st.set_page_config(page_title=f"{title} - {config.APP_NAME}", page_icon=icon, layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)
    _init_database()
    with st.sidebar:
        st.caption("Educational screening tool - not medical advice. For suspected poisoning or severe "
                   "symptoms contact local emergency services immediately.")


def get_conn():
    """New short-lived connection per call (SQLite connections are thread-bound in Streamlit)."""
    return db.get_connection()


def disclaimer_banner() -> None:
    st.warning(
        "**Educational screening tool, not a medical diagnostic service.** It cannot predict an individual's "
        "health outcome, lifespan or time to harm. If you suspect poisoning or have severe symptoms, contact "
        "local emergency services or a poison-information service right away and do not wait for this app.",
        icon="⚠️")


def render_emergency_panel(expanded: bool = False, triggered: bool = False) -> None:
    if triggered:
        st.error("**Your text mentions possible poisoning or serious symptoms. " + rs.RISK_URGENT + ".**", icon="🚨")
    with st.expander("Suspected poisoning or serious symptoms? Read this first", expanded=expanded or triggered):
        for line in URGENT_GUIDANCE:
            st.markdown(f"- {line}")
        resources = load_emergency_resources()
        if resources:
            for country, res in resources.items():
                st.markdown(f"**{country}**")
                for key, r in res.items():
                    if r.get("phone"):
                        st.markdown(f"- {r.get('name', key)}: **{r['phone']}** "
                                    f"(verified {r.get('verified_on', 'date not recorded')}; "
                                    f"[source]({r.get('source_url', '')}))")
        else:
            st.info("No verified emergency contacts are configured for your country. Look up your local "
                    "emergency number and poison-information service from an official source. "
                    "(Administrators: see data/emergency_resources.example.json.)")


def risk_badge(category: str) -> str:
    emoji, _ = RISK_STYLE.get(category, ("⚪", category))
    return f"{emoji} {category}"


def render_ingredient_card(e: dict, expanded: bool = False) -> None:
    with st.expander(f"{risk_badge(e['risk_category'])} - {e['canonical_name']}", expanded=expanded):
        if e.get("input_name") and e["input_name"].lower() != e["canonical_name"].lower():
            st.caption(f"Label text: '{e['input_name']}' - {e.get('match_type', '')} match "
                       f"(confidence {e.get('confidence', 0):.2f}). {e.get('match_note', '')}")
        st.markdown(f"**Identifier:** {e['identifiers'] or 'n/a'}  \n**Category:** {e['category']}  \n"
                    f"**Why it is used:** {e['purpose']}")
        status = e["verification_status"]
        (st.success if status == "reviewed" else st.warning)(e["verification_note"], icon="🗂️")
        st.markdown(f"**Overall evidence:** {e['evidence_level']}")
        if e["hazard_summary"]:
            st.markdown(f"**Summary of known hazards:** {e['hazard_summary']}")
        if e["effects"]:
            st.markdown("**Documented effects**")
            for ef in e["effects"]:
                st.markdown(f"- *{ef['timeframe']}* - {ef['effect']}  \n"
                            f"  Evidence: {ef['evidence_type']} / {ef['evidence_level']}; route: {ef['route']}"
                            + (f"; body system: {ef['body_system']}" if ef["body_system"] else "")
                            + (f"  \n  Conditions: {ef['conditions']}" if ef["conditions"] else "")
                            + (f"  \n  [Source]({ef['source_url']})" if ef["source_url"] else ""))
        else:
            st.markdown("**Documented effects:** none recorded (this is not evidence of safety).")
        for text, label in [(e["allergen_notes"], "Allergen/sensitivity"), (e["permitted_use_notes"], "Permitted use"),
                            (e["evidence_limitations"], "Evidence limitations"), (e["precautions"], "Precautions")]:
            if text:
                st.markdown(f"**{label}:** {text}")
        if e["safety_limits"]:
            st.markdown("**Safety limits**")
            for l in e["safety_limits"]:
                st.markdown(f"- {l['text']}" + (f" [Source]({l['source_url']})" if l["source_url"] else ""))
        else:
            st.markdown("**Safety limits:** none recorded.")
        if e["sources"]:
            st.markdown("**References**")
            for s in e["sources"]:
                st.markdown(f"- [{s['title']}]({s['url']}) - {s['publisher']}"
                            f" ({s['publication_date'] or 'date n/a'}). Supports: {s['claim_supported']}")
        if e["source_problems"]:
            with st.container():
                st.caption("Provenance gaps: " + " | ".join(e["source_problems"]))
