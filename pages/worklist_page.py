"""Streamlit reviewer worklist page.

Shows all applications currently in a reviewable state, letting the
reviewer navigate to each application's results page.
"""

import streamlit as st


# Status display config
_STATUS_ICONS = {
    "uploaded": "📥",
    "processing": "⚙️",
    "exceptions_found": "⚠️",
    "clean": "✅",
    "reviewed": "🔍",
    "approved": "✔️",
    "rejected": "❌",
}


def render_worklist_page(items: list[dict] | None = None) -> None:
    st.title("🗂️ Reviewer Worklist")
    st.caption("Applications awaiting review are listed below.")

    if items is None:
        # Placeholder data until DB queries are wired up
        items = [
            {
                "loan_id": "LN-DEMO-001",
                "applicant_name": "Ravi Kumar",
                "product_type": "Home Loan",
                "branch": "Pune Main",
                "status": "exceptions_found",
                "total_exceptions": 3,
                "high_severity_count": 1,
            }
        ]
        st.info("Showing placeholder data — wire up DB query to load real applications.")

    if not items:
        st.success("🎉 No applications pending review.")
        return

    st.divider()

    for item in items:
        status = item.get("status", "uploaded")
        icon = _STATUS_ICONS.get(status, "📄")
        exc_count = item.get("total_exceptions", 0)
        high_count = item.get("high_severity_count", 0)

        col_info, col_action = st.columns([4, 1])
        with col_info:
            st.markdown(
                f"**{icon} {item.get('loan_id', 'Unknown')}** — "
                f"{item.get('applicant_name', 'N/A')}  \n"
                f"Product: {item.get('product_type', '—')} | "
                f"Branch: {item.get('branch', '—')} | "
                f"Status: `{status}` | "
                f"Exceptions: **{exc_count}** ({high_count} high)"
            )
        with col_action:
            if st.button("View", key=f"view_{item.get('loan_id')}"):
                # TODO: set session state to load this application in results_page
                st.session_state["selected_loan_id"] = item.get("loan_id")
                st.info("TODO: navigate to Results page with this loan loaded.")

        st.divider()
