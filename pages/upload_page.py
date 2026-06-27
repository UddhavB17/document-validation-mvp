"""Streamlit upload page."""

import streamlit as st


def render_upload_page() -> None:
    st.title("DMEF")
    st.file_uploader("Upload loan-file PDF", type=["pdf"])
