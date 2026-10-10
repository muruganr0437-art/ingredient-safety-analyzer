"""Locally stored (redacted) report history with delete controls."""
import streamlit as st

import ui
from database import db
from services import report_service as rs

ui.setup_page("Report History", "🗂️")
st.title("🗂️ Report History")
ui.disclaimer_banner()
st.caption("Reports are stored only in this app's local database. Images and body weight are never stored.")

conn = ui.get_conn()
rows = db.list_sessions(conn)
if not rows:
    st.info("No saved reports yet. Use 'Save to local history' on the Product Analysis page.")
for r in rows:
    with st.expander(f"#{r['id']} - {r['product_name'] or 'Unnamed product'} - {r['created_at']}"):
        report = db.get_session_report(conn, r["id"])
        if report:
            for e in report["ingredients"]:
                st.markdown(f"- **{e['canonical_name']}** - {ui.risk_badge(e['risk_category'])}")
            if report["unmatched"]:
                st.markdown("Not assessed: " + ", ".join(report["unmatched"]))
            c1, c2, c3 = st.columns(3)
            c1.download_button("TXT", rs.report_to_text(report), f"report_{r['id']}.txt", key=f"t{r['id']}")
            c2.download_button("PDF", rs.report_to_pdf(report), f"report_{r['id']}.pdf", key=f"p{r['id']}")
            if c3.button("Delete", key=f"d{r['id']}"):
                db.delete_session(conn, r["id"])
                st.rerun()
if rows:
    st.divider()
    confirm = st.checkbox("I understand this deletes ALL saved reports")
    if st.button("Delete all history", disabled=not confirm):
        db.delete_all_sessions(conn)
        st.rerun()
conn.close()
