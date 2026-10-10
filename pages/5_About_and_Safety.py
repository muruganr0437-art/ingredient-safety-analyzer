import streamlit as st

import config
import ui
from services import ai_service

ui.setup_page("About and Safety", "ℹ️")
st.title("ℹ️ About and Safety Disclaimer")
ui.disclaimer_banner()
ui.render_emergency_panel(expanded=True)

st.header("What this app does")
st.markdown("""
It reads ingredient lists (OCR or typed), matches them to a curated database and shows what that database says,
with sources, limitations and gaps. It can estimate intake for one ingredient when *you* supply a validated
concentration, and compare it with a *reviewed* ADI.
""")
st.header("What it does not do")
st.markdown("""
- It does not diagnose, treat, or give medical advice.
- It does not predict illness, death, lifespan or time to harm - ever.
- It does not call a product "safe" or "dangerous". Missing data is shown as missing.
- It does not query WHO/EFSA/FDA/FSSAI live. Its data is a local curated database, and records marked
  *unverified* have not been checked by a person.
- OCR can misread text; always check the extracted ingredients.
""")
st.header("Status of this installation")
st.markdown(f"- Optional AI explanations: **{'enabled' if ai_service.is_available() else 'off'}**\n"
            f"- Max upload size: **{config.MAX_UPLOAD_MB} MB**\n"
            f"- Admin page: **{'enabled' if config.ADMIN_PASSWORD else 'disabled'}**")
