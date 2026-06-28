"""Streamlit results page.

Displays validation exceptions and the LLM summary for a given application.
"""

import streamlit as st


def render_results_page(
    exceptions: list[dict] | None = None,
    llm_summary: str = "",
    loan_id: str = "",
) -> None:
    st.title("📋 Validation Results")

    if not loan_id and not exceptions:
        st.info("No application loaded. Use the **Upload** page to submit a loan file.")
        return

    if loan_id:
        st.caption(f"Loan ID: **{loan_id}**")

    st.divider()

    # ── LLM summary card ──────────────────────
    if llm_summary:
        st.subheader("Summary")
        st.info(llm_summary)

    # ── Exception table ───────────────────────
    st.subheader("Exceptions")
    if not exceptions:
        st.success("✅ No exceptions found — the loan file is complete.")
        return

    # Severity badge colour mapping
    severity_colours = {"high": "🔴", "medium": "🟡", "low": "🟢"}

    for exc in exceptions:
        severity = exc.get("severity", "medium")
        icon = severity_colours.get(severity, "⚪")
        with st.expander(
            f"{icon} [{severity.upper()}] {exc.get('document', 'Unknown')} — {exc.get('issue', '')}"
        ):
            st.write(exc.get("detail", "No detail provided."))

    st.divider()
    st.metric("Total exceptions", len(exceptions))
    high_count = sum(1 for e in exceptions if e.get("severity") == "high")
    if high_count:
        st.warning(f"⚠️ {high_count} high-severity exception(s) require immediate attention.")
