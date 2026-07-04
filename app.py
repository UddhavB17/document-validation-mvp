"""Streamlit entry point for DMEF - Document Matching Early Finder."""

from services.python_runtime import require_python_311

require_python_311()

import streamlit as st

from views.status_helpers import load_application_status
from pages.activity_page import render_activity_page
from pages.worklist_page import render_worklist_page
from views.upload_view import render_upload_page


APP_CSS = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
[data-testid="stToolbar"] {display: none;}
[data-testid="stDecoration"] {display: none;}
[data-testid="stStatusWidget"] {display: none;}
.stDeployButton {display: none;}

:root {
    --dmef-ink: #e6edf7;
    --dmef-muted: #9aa8ba;
    --dmef-line: #263447;
    --dmef-surface: #111827;
    --dmef-surface-2: #162033;
    --dmef-body: #0b111d;
    --dmef-blue: #60a5fa;
    --dmef-green: #34d399;
    --dmef-red: #fb7185;
    --dmef-amber: #fbbf24;
}

.stApp {
    background: var(--dmef-body);
    color: var(--dmef-ink);
}

.block-container {
    padding-top: 1.25rem;
    padding-bottom: 2rem;
    max-width: 1480px;
}

[data-testid="stSidebar"] {
    background: var(--dmef-body);
    border-right: 1px solid var(--dmef-line);
}

[data-testid="stSidebar"] > div {
    background: var(--dmef-body);
}

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: var(--dmef-ink);
}

h1, h2, h3, h4, h5, h6,
p, label, span, div {
    color: inherit;
}

.dmef-page-title {
    border-bottom: 1px solid var(--dmef-line);
    margin-bottom: 1rem;
    padding-bottom: 0.8rem;
}

.dmef-page-title h1 {
    color: var(--dmef-ink);
    font-size: 1.65rem;
    line-height: 1.2;
    margin: 0;
}

.dmef-caption {
    color: var(--dmef-muted);
    font-size: 0.9rem;
}

.dmef-side-block {
    border-top: 1px solid var(--dmef-line);
    margin-top: 1rem;
    padding-top: 1rem;
}

.dmef-pill {
    background: #132b42;
    border: 1px solid #23506f;
    border-radius: 999px;
    color: #b7dcff;
    display: inline-block;
    font-size: 0.8rem;
    font-weight: 600;
    margin: 0.2rem 0.25rem 0.2rem 0;
    padding: 0.2rem 0.55rem;
}

.dmef-status-clean { color: var(--dmef-green); font-weight: 700; }
.dmef-status-review { color: var(--dmef-amber); font-weight: 700; }
.dmef-status-critical { color: var(--dmef-red); font-weight: 700; }
.dmef-status-neutral { color: var(--dmef-blue); font-weight: 700; }

div[data-testid="stMetric"] {
    background: var(--dmef-surface);
    border: 1px solid var(--dmef-line);
    border-radius: 6px;
    padding: 0.7rem 0.8rem;
}

div[data-testid="stMetricLabel"] {
    color: var(--dmef-muted);
}

div[data-testid="stMetricValue"] {
    color: var(--dmef-ink);
}

div[data-baseweb="input"],
div[data-baseweb="select"] > div,
textarea,
input {
    background: var(--dmef-surface) !important;
    border-color: var(--dmef-line) !important;
    color: var(--dmef-ink) !important;
}

div[data-baseweb="tab-list"] {
    border-bottom-color: var(--dmef-line);
}

button[role="tab"] {
    color: var(--dmef-muted);
}

button[aria-selected="true"] {
    color: var(--dmef-blue);
}

div[data-testid="stFileUploader"] section {
    background: var(--dmef-surface);
    border-color: var(--dmef-line);
}

div[data-testid="stFileUploader"] small {
    color: var(--dmef-muted);
}

div[data-testid="stAlert"] {
    background: var(--dmef-surface-2);
    border: 1px solid var(--dmef-line);
    color: var(--dmef-ink);
}

div[data-testid="stExpander"] {
    background: var(--dmef-surface);
    border: 1px solid var(--dmef-line);
    border-radius: 6px;
}

code,
pre {
    background: #07101e !important;
    color: #d8e7ff !important;
    border-color: var(--dmef-line) !important;
}

button[kind="primary"] {
    border-radius: 6px;
}

button[kind="secondary"],
button[data-testid="baseButton-secondary"] {
    background: var(--dmef-surface) !important;
    border: 1px solid var(--dmef-line) !important;
    color: var(--dmef-ink) !important;
    border-radius: 6px;
}

button[kind="secondary"]:hover,
button[data-testid="baseButton-secondary"]:hover {
    border-color: var(--dmef-blue) !important;
    color: var(--dmef-blue) !important;
}

[role="radiogroup"] label {
    background: transparent !important;
    color: var(--dmef-ink) !important;
}

.stDataFrame {
    border: 1px solid var(--dmef-line);
    border-radius: 6px;
}

.stDataFrame,
[data-testid="stDataFrame"] {
    background: var(--dmef-surface);
}

[data-testid="stMarkdownContainer"] a {
    color: var(--dmef-blue);
}
</style>
"""


def main() -> None:
    st.set_page_config(
        page_title="DMEF - Document Matching Early Finder",
        layout="wide",
        menu_items={
            "Get Help": None,
            "Report a bug": None,
            "About": None,
        },
    )
    st.markdown(APP_CSS, unsafe_allow_html=True)

    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "Upload"

    with st.sidebar:
        st.title("DMEF")
        st.caption("Document Matching Early Finder")
        page = st.radio(
            "View",
            ["Upload", "Worklist", "My Activity"],
            key="current_page",
        )
        st.markdown('<div class="dmef-side-block"></div>', unsafe_allow_html=True)
        current_application_id = st.session_state.get("application_id") or st.session_state.get("last_uploaded_application_id")
        if current_application_id:
            status = load_application_status(int(current_application_id)) or "unknown"
            st.caption("Current file")
            st.write(f"Application `{current_application_id}`")
            st.markdown(f'<span class="dmef-pill">{status}</span>', unsafe_allow_html=True)
        else:
            st.caption("No active file selected")
        st.markdown('<div class="dmef-side-block"></div>', unsafe_allow_html=True)
        st.caption("API")
        st.code("127.0.0.1:8000", language="text")

    if page == "Upload":
        render_upload_page()
    elif page == "Worklist":
        render_worklist_page()
    else:
        render_activity_page()


if __name__ == "__main__":
    main()
