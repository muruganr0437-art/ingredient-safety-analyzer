"""Upload -> OCR -> edit -> match -> evidence cards -> optional exposure -> report download."""
import pandas as pd
import plotly.express as px
import streamlit as st

import config
import ui
from database import db
from services import ai_service, ocr_service, ingredient_service as ing_svc
from services import report_service as rs
from services.exposure_service import calculate_exposure, food_amount_kg, percent_to_mg_per_kg
from services.safety_service import check_toxic_exposure

ui.setup_page("Product Analysis", "🔬")
st.title("🔬 Product Analysis")
ui.disclaimer_banner()

# ---- 0. Safety check -------------------------------------------------------
notes = st.text_area("Optional: describe any symptoms or a suspected ingestion (checked locally, never stored)",
                     key="symptom_text", height=70)
alert = check_toxic_exposure(notes)
ui.render_emergency_panel(triggered=bool(alert))

# ---- 1. Input --------------------------------------------------------------
tab_up, tab_manual = st.tabs(["📷 Upload label image", "⌨️ Enter manually"])
with tab_up:
    up = st.file_uploader("Ingredient label, nutrition facts or packaging photo",
                          type=sorted(config.ALLOWED_EXTENSIONS), help=f"Max {config.MAX_UPLOAD_MB} MB.")
    if up is not None:
        data = up.getvalue()
        try:
            ocr_service.validate_upload(up.name, data)
            image = ocr_service.load_image(data)
        except ocr_service.ImageValidationError as exc:
            st.error(str(exc))
            image = None
        if image is not None:
            st.image(image, caption="Preview (nothing is stored)", use_container_width=True)
            st.caption("Only text that is actually legible in the image will be extracted.")
            if st.button("Extract text (OCR)"):
                with st.spinner("Reading the label..."):
                    res = ocr_service.run_ocr(image)
                if res.success:
                    info = ocr_service.parse_label_text(res.text)
                    st.session_state["ocr_text"] = res.text
                    st.session_state["ingredients_text"] = info.ingredients_text
                    st.session_state["label_info"] = {
                        "serving_size": info.serving_size, "nutrition": info.nutrition,
                        "allergens": info.allergens, "manufacturer": info.manufacturer, "expiry": info.expiry}
                    if info.product_name:
                        st.session_state["product_name"] = info.product_name
                    st.success("Text extracted. Please check it below and fix any OCR mistakes.")
                else:
                    st.error(res.error)
                    st.info("You can still use the 'Enter manually' tab.")
with tab_manual:
    st.caption("Type or paste the ingredient list in the editable box below.")

st.text_area("Raw OCR text (editable)", key="ocr_text", height=140)
st.text_input("Product name (optional)", key="product_name")
st.text_area("Ingredient list to analyze (edit to correct OCR errors)", key="ingredients_text", height=110,
             placeholder="Water, sugar, preservative (sodium benzoate), colour (E102)...")
li = st.session_state.get("label_info") or {}
if any(li.values()):
    with st.expander("Other label details found by OCR (check before relying on them)"):
        st.json({k: v for k, v in li.items() if v})

# ---- 2. Analyze ------------------------------------------------------------
if st.button("Analyze ingredients", type="primary"):
    items = ing_svc.split_ingredient_list(st.session_state.get("ingredients_text", ""))
    if not items:
        st.error("Please provide an ingredient list first (upload an image or type it).")
    else:
        conn = ui.get_conn()
        try:
            all_ings = db.get_all_ingredients(conn)
        finally:
            conn.close()
        idx = ing_svc.build_index(all_ings)
        st.session_state["matches"] = ing_svc.match_items(items, idx)
        st.session_state["ings_by_id"] = {i.id: i for i in all_ings}
        st.session_state["exposures"] = {}
        st.session_state.pop("ai_text", None)

matches = st.session_state.get("matches")
if not matches:
    st.stop()
ings_by_id = st.session_state["ings_by_id"]

# ---- 3. Confirm uncertain matches -----------------------------------------
fuzzy = [m for m in matches if m.needs_confirmation]
confirmed: set[str] = set()
if fuzzy:
    st.subheader("Please confirm uncertain matches")
    st.caption("These look like typos or variants. They are excluded from the analysis until you confirm them.")
    for n, m in enumerate(fuzzy):
        target = ings_by_id[m.ingredient_id].canonical_name
        if st.checkbox(f"'{m.input_name}' is **{target}**", key=f"confirm_{n}"):
            confirmed.add(m.input_name)

exposures = list(st.session_state.get("exposures", {}).values())
report = rs.build_report(
    st.session_state.get("product_name", ""), matches, ings_by_id, exposures,
    st.session_state.get("label_info"), alert, confirmed)

# ---- 4. Results ------------------------------------------------------------
st.header("Results")
if report["safety_alert"]:
    st.error(f"{rs.RISK_URGENT}: see the emergency guidance above.", icon="🚨")
counts = report["risk_counts"]
if counts:
    df = pd.DataFrame({"Category": list(counts), "Ingredients": list(counts.values())})
    fig = px.bar(df, x="Ingredients", y="Category", orientation="h", text="Ingredients",
                 title="Ingredients by assessment category")
    fig.update_layout(height=260, margin=dict(l=0, r=0, t=40, b=0), yaxis_title=None)
    st.plotly_chart(fig, use_container_width=True)
for entry in report["ingredients"]:
    ui.render_ingredient_card(entry)
if report["unmatched"]:
    st.warning("**Not assessed (not found in the database):** " + ", ".join(report["unmatched"]) +
               "  \nNot being in the database does not mean an ingredient is safe or unsafe.")

# ---- 5. Exposure -----------------------------------------------------------
st.header("Exposure estimate (optional)")
st.caption("Requires a validated concentration from a reliable source (e.g., manufacturer declaration or lab "
           "report). Position in the ingredient list is NOT a concentration.")
active = [e for e in report["ingredients"]]
if active:
    names = {e["canonical_name"]: e for e in active}
    choice = st.selectbox("Ingredient", list(names))
    entry = names[choice]
    ing = ings_by_id[entry["ingredient_id"]]
    reviewed = [l for l in ing.safety_limits if l.verification_status == "reviewed"]
    if reviewed:
        st.info(f"Reviewed {reviewed[0].limit_type}: {reviewed[0].value_mg_per_kg_bw:g} mg/kg bw/day "
                f"({reviewed[0].authority}).")
    elif ing.safety_limits:
        st.warning("A safety limit is recorded but has not been reviewed, so no comparison will be made. "
                   "An administrator can review it on the Ingredient Database page.")
    else:
        st.warning("No safety limit is recorded; only intake can be estimated.")
    pct = entry.get("declared_percent")
    if pct:
        st.caption(f"The label text shows {pct:g}% ({percent_to_mg_per_kg(pct):,.0f} mg/kg). Use it only if you "
                   "have confirmed it refers to this exact substance in the form the limit uses.")
    c1, c2, c3 = st.columns(3)
    conc = c1.number_input("Concentration (mg/kg food)", min_value=0.0, value=None, format="%.4f")
    src = c1.text_input("Source of that concentration")
    serv_g = c2.number_input("Serving size (g)", min_value=0.0, value=None)
    servs = c2.number_input("Servings per day", min_value=0.0, value=None)
    bw = c3.number_input("Body weight (kg) - not stored", min_value=0.0, value=None)
    if st.button("Calculate exposure"):
        food = food_amount_kg(serv_g, servs) if serv_g and servs else None
        lim = reviewed[0] if reviewed else None
        st.session_state["exposures"][ing.id] = calculate_exposure(
            conc, food, bw, lim.value_mg_per_kg_bw if lim else None, bool(lim), src, ing.canonical_name,
            lim.expressed_as if lim else None, lim.authority if lim else None)
        st.rerun()

for x in report["exposures"]:
    st.subheader(x["ingredient_name"])
    if x["status"] != "ok":
        st.error(x["message"])
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Daily intake", f"{x['daily_intake_mg']:.4g} mg/day")
        m2.metric("Per kg body weight", f"{x['exposure_mg_per_kg_bw']:.4g} mg/kg/day")
        if x["percent_of_adi"] is not None:
            m3.metric("% of reviewed ADI", f"{x['percent_of_adi']:.1f}%")
            fig = px.bar(pd.DataFrame({"Item": ["Estimated exposure", "Reviewed ADI"],
                                       "mg/kg bw/day": [x["exposure_mg_per_kg_bw"], x["adi_mg_per_kg_bw"]]}),
                         x="Item", y="mg/kg bw/day")
            fig.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)
    for a in x["assumptions"] + x["personal_assumptions"]:
        st.caption("Assumption: " + a)
    for m in x["missing"]:
        st.caption("Missing: " + m)
    for l in x["limitations"]:
        st.caption("Limitation: " + l)

# ---- 6. Missing data -------------------------------------------------------
st.header("Missing data and uncertainty")
for m in report["missing_data"]:
    st.markdown(f"- {m}")

# ---- 7. Optional AI explanation -------------------------------------------
if ai_service.is_available():
    st.header("Optional plain-language explanation (AI)")
    st.caption("Generated only from the curated findings above and checked for added numbers/links. "
               "It never replaces the verified data.")
    if st.button("Explain in simple language"):
        with st.spinner("Generating..."):
            r = ai_service.explain(report)
        st.session_state["ai_text"] = r.text if r.ok else None
        if not r.ok:
            st.error(r.error)
    if st.session_state.get("ai_text"):
        st.info(st.session_state["ai_text"])

# ---- 8. Report -------------------------------------------------------------
st.header("Report")
txt = rs.report_to_text(report)
d1, d2, d3 = st.columns(3)
d1.download_button("⬇️ Download TXT", txt, file_name="ingredient_report.txt", mime="text/plain")
d2.download_button("⬇️ Download PDF", rs.report_to_pdf(report), file_name="ingredient_report.pdf",
                   mime="application/pdf")
if d3.button("💾 Save to local history"):
    conn = ui.get_conn()
    try:
        red = rs.redact_report(report)
        db.save_session(conn, report["product"]["name"], red, [
            {"ingredient_id": e["ingredient_id"], "input_name": e["input_name"], "match_type": e["match_type"],
             "confidence": e["confidence"], "risk_category": e["risk_category"]} for e in report["ingredients"]])
    finally:
        conn.close()
    st.success("Saved (images and body weight are never stored).")
with st.expander("Preview report text"):
    st.text(txt)
