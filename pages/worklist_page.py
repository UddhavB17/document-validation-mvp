"""Streamlit reviewer worklist page."""

import streamlit as st


def render_worklist_page(items: list[dict]) -> None:
    st.subheader("Reviewer Worklist")
    st.dataframe(items)
