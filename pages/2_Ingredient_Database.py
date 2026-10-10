"""Browse the curated database; administrators can edit, review, import and export."""
import hmac
import json

import pandas as pd
import streamlit as st
from pydantic import ValidationError

import config
import ui
from database import db
from models.ingredient import Ingredient
from services import report_service as rs
from services.evidence_service import EVIDENCE_LABELS

ui.setup_page("Ingredient Database", "🧪")
st.title("🧪 Ingredient Safety Database")
ui.disclaimer_banner()

conn = ui.get_conn()
ings = db.get_all_ingredients(conn)
tab_browse, tab_admin = st.tabs(["Browse", "🔐 Administrator"])

with tab_browse:
    q = st.text_input("Search by name, synonym or E/INS number").strip().lower()
    def _hit(i: Ingredient) -> bool:
        hay = " ".join([i.canonical_name, i.identifier_label, *i.synonyms]).lower()
        return q in hay
    shown = [i for i in ings if _hit(i)]
    st.dataframe(pd.DataFrame([{
        "Ingredient": i.canonical_name, "Identifier": i.identifier_label, "Category": i.category,
        "Evidence": EVIDENCE_LABELS[i.evidence_level],
        "Record status": i.verification_status, "Reviewed on": i.reviewed_on or ""} for i in shown]),
        use_container_width=True, hide_index=True)
    for i in shown:
        ui.render_ingredient_card(rs.describe_ingredient(i))

with tab_admin:
    if not config.ADMIN_PASSWORD:
        st.info("The administrator page is disabled. Set ADMIN_PASSWORD in .env (or the host's secrets) to enable it.")
    else:
        st.session_state.setdefault("admin_ok", False)
        st.session_state.setdefault("admin_fails", 0)
        if not st.session_state["admin_ok"]:
            if st.session_state["admin_fails"] >= 5:
                st.error("Too many failed attempts in this session. Reload the page to try again.")
            else:
                pw = st.text_input("Administrator password", type="password")
                if st.button("Sign in"):
                    if hmac.compare_digest(pw.encode(), config.ADMIN_PASSWORD.encode()):
                        st.session_state["admin_ok"] = True
                        st.rerun()
                    st.session_state["admin_fails"] += 1
                    st.error("Incorrect password.")
        else:
            if st.button("Sign out"):
                st.session_state["admin_ok"] = False
                st.rerun()
            st.caption("Only reviewed, source-backed data should be marked 'reviewed'. AI output must never be pasted "
                       "in as verified data.")
            names = ["➕ New record"] + [i.canonical_name for i in ings]
            sel = st.selectbox("Record", names)
            current = next((i for i in ings if i.canonical_name == sel), None)
            template = current.model_dump(exclude={"id"}) if current else Ingredient(
                canonical_name="New ingredient").model_dump(exclude={"id"})
            text = st.text_area("Record JSON (synonyms, sources, effects, safety limits, status, review date)",
                                value=json.dumps(template, indent=2, ensure_ascii=False), height=420,
                                key=f"json_{sel}")
            if st.button("Save record", type="primary"):
                try:
                    rec = Ingredient.model_validate_json(text)
                    new_id = db.upsert_ingredient(conn, rec, current.id if current else None)
                    st.success(f"Saved (id {new_id}).")
                    st.rerun()
                except ValidationError as exc:
                    st.error("Validation failed:\n\n" + "\n".join(
                        f"- {'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()))
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not save: {exc}")
            if current:
                st.subheader("Quick review actions")
                c1, c2 = st.columns(2)
                status = c1.selectbox("Status", ["unverified", "reviewed", "outdated"],
                                      index=["unverified", "reviewed", "outdated"].index(current.verification_status))
                date = c2.text_input("Reviewed on (YYYY-MM-DD)", value=current.reviewed_on or "")
                mark_limits = st.checkbox("Also apply this status and date to all safety limits of this record")
                if st.button("Apply status"):
                    try:
                        data = current.model_dump()
                        data.update(verification_status=status, reviewed_on=date or None)
                        if mark_limits:
                            for l in data["safety_limits"]:
                                l.update(verification_status=status, reviewed_on=date or None)
                        db.upsert_ingredient(conn, Ingredient.model_validate(data), current.id)
                        st.success("Status updated.")
                        st.rerun()
                    except ValidationError as exc:
                        st.error("Cannot apply: " + "; ".join(e["msg"] for e in exc.errors()))
                if st.button("Delete this record"):
                    db.delete_ingredient(conn, current.id)
                    st.rerun()
            st.subheader("Import / export")
            st.download_button("⬇️ Export JSON (full)", db.export_json(conn), "ingredients.json", "application/json")
            st.download_button("⬇️ Export CSV (summary)", db.export_csv(conn), "ingredients.csv", "text/csv")
            keep = st.checkbox("Keep 'reviewed' status from the file (only for files you have reviewed yourself)")
            up = st.file_uploader("Import JSON or CSV", type=["json", "csv"])
            if up is not None and st.button("Import"):
                content = up.getvalue().decode("utf-8", errors="replace")
                n, errs = (db.import_json(conn, content, keep) if up.name.lower().endswith(".json")
                           else db.import_csv(conn, content))
                st.success(f"Imported {n} record(s). Imported records are 'unverified' unless you kept the status.")
                for e in errs:
                    st.error(e)
conn.close()
