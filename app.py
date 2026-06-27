"""Streamlit entry point for DMEF."""

import streamlit as st

from pages.results_page import render_application_results
from pages.upload_page import render_upload_page
from pages.worklist_page import render_worklist_page


def main() -> None:
    st.set_page_config(page_title="DMEF", layout="wide")
    page = st.sidebar.radio("View", ["Upload", "Worklist", "Results"])
    if page == "Upload":
        render_upload_page()
    elif page == "Worklist":
        render_worklist_page()
    else:
        application_id = st.session_state.get("application_id")
        if application_id is None:
            application_id = st.number_input("Application ID", min_value=1, step=1)
        render_application_results(int(application_id))


if __name__ == "__main__":
    main()
