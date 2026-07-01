"""Streamlit My Activity page — end-of-day reviewer summary."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from database.db import get_connection


def render_activity_page() -> None:
    st.subheader("My Activity")
    st.caption("Decisions recorded today")

    summary = _load_today_summary()
    if not summary["rows"]:
        st.info("No reviewer decisions recorded today.")
        return

    columns = st.columns(4)
    columns[0].metric("Files reviewed today", summary["total"])
    columns[1].metric("Accepted", summary["accepted"])
    columns[2].metric("Overridden", summary["overridden"])
    columns[3].metric("Sent back", summary["sent_back"])

    chart_data = pd.DataFrame(
        [
            {"Decision": "Accepted", "Count": summary["accepted"]},
            {"Decision": "Overridden", "Count": summary["overridden"]},
            {"Decision": "Sent back", "Count": summary["sent_back"]},
        ]
    )
    if summary["total"] > 0:
        st.bar_chart(chart_data.set_index("Decision"))

    st.dataframe(pd.DataFrame(summary["rows"]), hide_index=True, use_container_width=True)


def _load_today_summary() -> dict:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                reviewer_decisions.id,
                reviewer_decisions.application_id,
                applications.loan_id,
                reviewer_decisions.decision,
                reviewer_decisions.decided_at
            FROM reviewer_decisions
            JOIN applications ON applications.id = reviewer_decisions.application_id
            WHERE date(reviewer_decisions.decided_at) = date('now', 'localtime')
            ORDER BY reviewer_decisions.decided_at DESC
            """
        ).fetchall()

    decision_rows = [dict(row) for row in rows]
    accepted = sum(1 for row in decision_rows if row["decision"] == "ACCEPT")
    overridden = sum(1 for row in decision_rows if row["decision"] == "OVERRIDE")
    sent_back = sum(1 for row in decision_rows if row["decision"] == "REQUEST_DOCS")

    return {
        "total": len(decision_rows),
        "accepted": accepted,
        "overridden": overridden,
        "sent_back": sent_back,
        "rows": decision_rows,
    }
