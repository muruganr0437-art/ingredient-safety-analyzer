import streamlit as st

import ui

ui.setup_page("Educational Resources", "📚")
st.title("📚 Educational Resources")
ui.disclaimer_banner()

st.header("Key ideas")
st.markdown("""
- **Hazard vs risk.** A *hazard* is something that *can* cause harm under some conditions. *Risk* depends on the
  dose, how often, who is exposed, and the context. Most ingredient headlines describe hazards.
- **Dose matters.** Even essential substances can harm at high enough doses, and many harmful-sounding names are
  harmless or even nutritious at normal intake.
- **ADI (acceptable daily intake).** The amount that can be consumed daily over a lifetime without appreciable
  health risk, built with large safety margins. It is a *chronic* reference, not an acute poisoning threshold.
  Exceeding it is a signal to look closer, not proof of harm.
- **E-numbers / INS numbers.** Identifiers for permitted additives. Having a number does not make an ingredient
  harmful, and lacking one does not make it safe.
- **Evidence levels.** Causal effects, statistical associations and theoretical concerns are different things.
  Laboratory or animal findings do not automatically apply to people.
- **Allergens and sensitivities** affect individuals differently from population-level safety limits.
""")
st.header("Official starting points")
st.markdown("""
- [JECFA food additives database (WHO/FAO)](https://apps.who.int/food-additives-contaminants-jecfa-database/)
- [EFSA - food additives](https://www.efsa.europa.eu/en/topics/topic/food-additives)
- [US FDA - food ingredients and packaging](https://www.fda.gov/food/food-ingredients-packaging)
- [FSSAI (India)](https://www.fssai.gov.in/)
- [IARC Monographs](https://monographs.iarc.who.int/)
""")
st.caption("These are general landing pages. The app does not query them live; always check the specific "
           "document cited in a report.")
