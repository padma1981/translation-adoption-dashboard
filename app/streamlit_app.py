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


def overview():
    """One donut: tool-enabled eligible calls that adopted the tool vs did not."""
    f = ui.page_header("Translation Tool Adoption",
                       "Contact center calls in Spanish, Portuguese, Mandarin and Vietnamese.")
    split = ui.q(metrics.adoption_split, f)
    total = int(split["calls"].sum())
    if total == 0:
        ui.no_data("tool-enabled eligible calls in this selection (the tool may not be "
                   "rolled out yet for these teams and dates)")
        st.stop()
    adopted = split.set_index("slice").loc["Adopted the tool"]

    fig = go.Figure(go.Pie(
        labels=split["slice"], values=split["calls"], hole=0.62, sort=False, direction="clockwise",
        marker=dict(colors=[ui.PATH_COLORS["translation_tool"], ui.NOT_ADOPTED_COLOR],
                    line=dict(color="white", width=3)),
        textinfo="none", customdata=split["share"],
        hovertemplate="%{label}<br>%{value:,} calls (%{customdata:.1%})<extra></extra>"))
    fig.add_annotation(text=f"<b>{adopted['share']:.0%}</b>", x=0.5, y=0.56, showarrow=False,
                       font=dict(size=56, color="#0b0b0b"))
    fig.add_annotation(text=f"adoption<br>{int(adopted['calls']):,} of {total:,} eligible calls",
                       x=0.5, y=0.38, showarrow=False, font=dict(size=14, color="#52514e"))
    fig.update_layout(height=460, margin=dict(l=10, r=10, t=10, b=10), showlegend=True,
                      legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.02, yanchor="top",
                                  font=dict(size=14)))

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        ui.show(fig)
        st.caption("**Eligible calls:** Spanish, Portuguese, Mandarin or Vietnamese calls handled "
                   "by an agent who is not native in that language and whose translation tool "
                   "was enabled on the call date. **Adopted the tool:** a translation session is "
                   "linked to the call. **Did not adopt:** interpreter line or no support.")

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
