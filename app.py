"""Home dashboard. Run with:  streamlit run app.py"""
import streamlit as st

import config
import ui

ui.setup_page("Home", "🥫")

st.title("🥫 " + config.APP_NAME)
st.markdown("Understand what is in a packaged food, what the evidence says about each ingredient, and "
            "what is **not** known - with sources you can check.")
ui.disclaimer_banner()
ui.render_emergency_panel()

c1, c2 = st.columns(2)
with c1:
    st.page_link("pages/1_Product_Analysis.py", label="📷 Upload Product / Analyze Ingredients", use_container_width=True)
    st.page_link("pages/3_Report_History.py", label="🗂️ Recent Reports", use_container_width=True)
    st.page_link("pages/5_About_and_Safety.py", label="ℹ️ About and Safety Disclaimer", use_container_width=True)
with c2:
    st.page_link("pages/2_Ingredient_Database.py", label="🧪 Ingredient Safety Database", use_container_width=True)
    st.page_link("pages/4_Educational_Resources.py", label="📚 Educational Resources", use_container_width=True)

st.subheader("How it works")
st.markdown(
    "1. **Upload** a photo of the ingredient label (or type the ingredients).\n"
    "2. **Review and correct** the OCR text.\n"
    "3. **Analyze**: ingredients are matched to a curated database; uncertain matches ask for your confirmation.\n"
    "4. **Optional exposure estimate** - only with a validated concentration, your serving and body weight.\n"
    "5. **Download** a TXT or PDF report with references and a list of what is missing.")
st.info("A hazard is not the same as a risk: whether an ingredient can cause harm depends on the dose, "
        "the person and the context. This app keeps those two ideas separate.")
