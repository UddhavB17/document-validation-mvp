"""Streamlit results page."""

import streamlit as st


def render_results_page(exceptions: list[dict]) -> None:
    st.subheader("Validation Results")
    st.dataframe(exceptions)
