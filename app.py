"""Streamlit entry point for DMEF."""

import streamlit as st

from pages.upload_page import render_upload_page


def main() -> None:
    st.set_page_config(page_title="DMEF", layout="wide")
    render_upload_page()


if __name__ == "__main__":
    main()
