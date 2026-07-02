"""Streamlit entry point for DMEF - Document Matching Early Finder."""

from services.python_runtime import require_python_311

require_python_311()

import streamlit as st

from pages.activity_page import render_activity_page
from pages.worklist_page import render_worklist_page
from views.upload_view import render_upload_page


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
    st.markdown(
        """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        [data-testid="stToolbar"] {display: none;}
        [data-testid="stDecoration"] {display: none;}
        [data-testid="stStatusWidget"] {display: none;}
        .stDeployButton {display: none;}
        </style>
        """,
        unsafe_allow_html=True,
    )

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

    if page == "Upload":
        render_upload_page()
    elif page == "Worklist":
        render_worklist_page()
    else:
        render_activity_page()


if __name__ == "__main__":
    main()
