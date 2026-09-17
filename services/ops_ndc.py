"""Non-Discrepancy Checklist state for the ops UI (tmp/user-portal-ux).

The paper form (``MSFC / NDC / MAY'26 / VER.1.4``, 44 rows) is the same
checklist the pipeline checks: row text comes from
``services/checklist_service.py`` keyed by ``s_no`` (rows 1-43), plus the
paper's row 44 ("Other", manual-only). The paper's E-Sign / Physical /
Upload column is display-only data below (``NDC_MODES``).

Completeness rule per row: system-checked (pipeline status FOUND) counts
on its own; otherwise the row needs a manual tick from both roles
(``cso`` = CSO/BOPS, ``cops`` = COPS).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database.db import get_connection

NDC_VERSION = "MSFC / NDC / MAY'26 / VER.1.4"

NDC_ROLES = ("cso", "cops")

_OTHER_S_NO = 44

# Paper column "E-Sign / Physical / Upload in System", condensed. Rows not
# listed here render "—" (row 3 has no mode on the paper form).
NDC_MODES: dict[int, str] = {
    1: "Physical",
    2: "Digital - if not verified in Graviton (Physical)",
    4: "Digital - if not verified in Graviton (Physical)",
    5: "Digital - if not verified in Graviton (Physical)",
    6: "Digital - if not verified in Graviton (Physical)",
    7: "Physical - Form 97",
    8: "Physical - Form 97",
    9: "Physical - If Applicable",
    10: "Upload in System",
    11: "Physical - If Applicable",
    12: "Crosscheck from System & Physical if available",
    13: "Crosscheck from System",
    14: "Crosscheck from System",
    15: "Upload in System",
    16: "Aggregator Banking / Upload in System",
    17: "Upload in System",
    18: "Upload in System",
    19: "Check in System",
    20: "e-Sign / Physical / Upload in System",
    21: "e-Sign / Physical / Upload in System",
    22: "Physical & Upload in System",
    23: "Upload in System",
    24: "Upload in System",
    25: "Physical",
    26: "Physical",
    27: "e-Sign / Physical - Upload in System",
    28: "Upload in System",
    29: "Upload in System",
    30: "Physical",
    31: "Digital - Upload in system",
    32: "Physical / Upload in System",
    33: "e-Sign / Physical / Upload in System",
    34: "Digital - Upload in system",
    35: "Physical & Upload in System",
    36: "Physical & Upload in system",
    37: "Update in System",
    38: "Update in System",
    39: "Update in System",
    40: "NACH",
    41: "Physical",
    42: "Digital - Upload in system",
    43: "Physical",
}

_OTHER_ROW: dict[str, Any] = {
    "s_no": _OTHER_S_NO,
    "category": "Other",
    "description": "Other remarks / additional documents on record",
    "ai_checkable": False,
    "manual_review_reason": "Free row for anything the printed form does not list; always checked by hand.",
}


def ndc_definitions(product_type: str = "LAP") -> list[dict[str, Any]]:
    """Return the 44 NDC rows in paper order (definitions only, no state)."""
    from services.checklist_service import load_checklist  # noqa: PLC0415

    raw = load_checklist(product_type)
    items = [dict(item) for item in raw.get("checklist_items", [])]
    items.sort(key=lambda item: int(item.get("s_no") or 0))
    items.append(dict(_OTHER_ROW))
    return items


def _display_names(user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    placeholders = ", ".join(["?"] * len(user_ids))
    with get_connection() as connection:
        rows = connection.execute(
            f"SELECT id, display_name, email FROM users WHERE id IN ({placeholders})",
            tuple(user_ids),
        ).fetchall()
    names: dict[int, str] = {}
    for row in rows:
        label = str(row["display_name"] or "").strip() or str(row["email"] or "").strip()
        names[int(row["id"])] = label or f"user {int(row['id'])}"
    return names


def build_ndc_state(application_id: int) -> dict[str, Any]:
    """Return the full NDC state for one application (raises KeyError when missing)."""
    from services.ops_presentation import build_ops_payload  # noqa: PLC0415

    payload = build_ops_payload(application_id)
    system_status = {
        int(row["s_no"]): str(row.get("status") or "")
        for row in payload.get("checklist", {}).get("rows", [])
        if isinstance(row, dict) and row.get("s_no") is not None
    }

    with get_connection() as connection:
        app_row = connection.execute(
            "SELECT id, loan_id, applicant_name, product_type FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        if app_row is None:
            raise KeyError(application_id)
        product_type = str(app_row["product_type"] or "LAP")
        try:
            check_rows = connection.execute(
                "SELECT s_no, role, checked_by, checked_at FROM ops_ndc_checks WHERE application_id = ?",
                (application_id,),
            ).fetchall()
        except Exception:
            check_rows = []
        latest_decision = None
        try:
            latest_decision = connection.execute(
                "SELECT decision, decided_at FROM reviewer_decisions "
                "WHERE application_id = ? ORDER BY id DESC LIMIT 1",
                (application_id,),
            ).fetchone()
        except Exception:
            latest_decision = None

    manual: dict[tuple[int, str], dict[str, Any]] = {}
    for row in check_rows:
        try:
            key = (int(row["s_no"]), str(row["role"]))
        except (TypeError, ValueError):
            continue
        manual[key] = {"by": row["checked_by"], "at": row["checked_at"]}
    names = _display_names(
        {int(v["by"]) for v in manual.values() if v["by"] is not None}
    )

    rows: list[dict[str, Any]] = []
    complete_count = 0
    for definition in ndc_definitions(product_type):
        s_no = int(definition["s_no"])
        status = system_status.get(s_no, "")
        system_checked = status == "FOUND"
        system_only = s_no == _OTHER_S_NO or not bool(definition.get("ai_checkable", True))
        cells: dict[str, Any] = {}
        for role in NDC_ROLES:
            tick = manual.get((s_no, role))
            cells[role] = (
                {
                    "checked": True,
                    "by": tick["by"],
                    "by_name": names.get(int(tick["by"]), "") if tick["by"] is not None else "",
                    "at": tick["at"],
                }
                if tick is not None
                else {"checked": False, "by": None, "by_name": "", "at": None}
            )
        row_complete = system_checked or all(cells[role]["checked"] for role in NDC_ROLES)
        if row_complete:
            complete_count += 1
        rows.append(
            {
                "s_no": s_no,
                "group": str(definition.get("category") or ""),
                "title": str(definition.get("description") or ""),
                "mode": NDC_MODES.get(s_no, "—"),
                "hint": "" if system_checked else str(definition.get("manual_review_reason") or ""),
                "system_checked": system_checked,
                "system_only_manual": system_only and not system_checked,
                "checks": cells,
                "complete": row_complete,
            }
        )

    decision = str((latest_decision or {}).get("decision") or "").upper() if latest_decision else ""
    return {
        "version": NDC_VERSION,
        "application_id": application_id,
        "loan_id": app_row["loan_id"],
        "applicant_name": app_row["applicant_name"],
        "checked_at": datetime.now(UTC).isoformat(),
        "total": len(rows),
        "complete_count": complete_count,
        "complete": complete_count == len(rows) and len(rows) > 0,
        "verified": decision == "ACCEPT",
        "latest_decision": decision or None,
        "rows": rows,
    }
