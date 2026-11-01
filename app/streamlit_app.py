"""Entry point and Overview page.

Run with: streamlit run app/streamlit_app.py
The top menu and filter bar are drawn here once, so filters carry across every page.
"""

from pathlib import Path
import sys

import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Translation Tool Adoption", page_icon="🌐", layout="wide",
                   initial_sidebar_state="collapsed")

sys.path.insert(0, str(Path(__file__).resolve().parent))   # so pages can `import ui`
import ui  # noqa: E402
from ui import metrics  # noqa: E402


ELIGIBILITY_HELP = (
    "Eligible calls: Spanish, Portuguese, Mandarin or Vietnamese calls handled by an agent who "
    "is not native in that language and whose translation tool was enabled on the call date. "
    "Adopted the tool: a translation session is linked to the call. "
    "Did not adopt: interpreter line or no support.")

CARD_CSS = """
<style>
.st-key-adoption_card { padding: 1.25rem 1.5rem; }
</style>
"""


def adoption_donut(split, share):
    """Two-slice donut with the adoption % in the center."""
    fig = go.Figure(go.Pie(
        labels=split["slice"], values=split["calls"], hole=0.62, sort=False, direction="clockwise",
        marker=dict(colors=[ui.PATH_COLORS["translation_tool"], ui.NOT_ADOPTED_COLOR],
                    line=dict(color="white", width=3)),
        textinfo="none", customdata=split["share"],
        hovertemplate="%{label}<br>%{value:,} calls (%{customdata:.1%})<extra></extra>"))
    fig.add_annotation(text=f"<b>{share:.0%}</b>", x=0.5, y=0.55, showarrow=False,
                       font=dict(size=44, color="#0b0b0b"))
    fig.add_annotation(text="adoption", x=0.5, y=0.40, showarrow=False,
                       font=dict(size=14, color="#52514e"))
    fig.update_layout(height=340, margin=dict(l=0, r=0, t=0, b=0), showlegend=True,
                      legend=dict(orientation="h", x=0, xanchor="left", y=-0.02, yanchor="top",
                                  font=dict(size=13)))
    return fig


def overview():
    """Adoption card: donut, summary line and CSV download for the active filters."""
    f = ui.page_header("Translation Tool Adoption")
    split = ui.q(metrics.adoption_split, f)
    total = int(split["calls"].sum())
    if total == 0:
        ui.no_data("tool-enabled eligible calls in this selection (the tool may not be "
                   "rolled out yet for these teams and dates)")
        st.stop()
    adopted = split.set_index("slice").loc["Adopted the tool"]

    st.html(CARD_CSS)
    left, _right = st.columns([0.43, 0.57])   # right column left empty for now
    with left, st.container(border=True, key="adoption_card"):
        st.subheader("Adoption Percentage", anchor=False)
        ui.show(adoption_donut(split, adopted["share"]), width=320)   # compact, left-aligned
        st.markdown(f"**{int(adopted['calls']):,}** of **{total:,}** eligible calls adopted the tool",
                    help=ELIGIBILITY_HELP)
        csv = split.assign(start_date=f.start, end_date=f.end,
                           teams="; ".join(f.teams or ["all"]),
                           supervisors="; ".join(f.supervisors or ["all"]),
                           languages="; ".join(f.languages))
        st.download_button("Download CSV", csv.to_csv(index=False), "adoption_split.csv",
                           "text/csv", icon=":material/download:")

    ui.footnote()


pages = [
    st.Page(overview, title="Overview", icon="📊", default=True),
    st.Page("views/1_Agents_and_Teams.py", title="Agents & Teams", icon="👥"),
    st.Page("views/2_Languages.py", title="Languages", icon="🗣️"),
    st.Page("views/3_Operational_Impact.py", title="Operational Impact", icon="⏱️"),
    st.Page("views/4_Cost.py", title="Cost", icon="💵"),
    st.Page("views/5_Data_Quality.py", title="Data Quality", icon="🧪"),
]
page = st.navigation(pages, position="top")
ui.render_filter_bar()
page.run()
