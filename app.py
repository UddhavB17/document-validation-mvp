"""Streamlit entry point for DMEF – Document Matching Early Finder.

Run with:
    streamlit run app.py
"""

import streamlit as st

from pages.upload_page import render_upload_page
from pages.results_page import render_results_page
from pages.worklist_page import render_worklist_page

# ── Page registry ─────────────────────────────
_PAGES: dict[str, callable] = {
    "📤 Upload": render_upload_page,
    "📋 Results": render_results_page,
    "🗂️ Worklist": render_worklist_page,
}


def main() -> None:
    st.set_page_config(
        page_title="DMEF – Document Matching Early Finder",
        page_icon="📄",
        layout="wide",
    )

    # Sidebar navigation
    with st.sidebar:
        st.title("DMEF")
        st.caption("Document Matching Early Finder")
        st.divider()
        selection = st.radio("Navigate", list(_PAGES.keys()), label_visibility="collapsed")

    # Render selected page
    _PAGES[selection]()


if __name__ == "__main__":
    main()
