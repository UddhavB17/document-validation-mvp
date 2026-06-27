"""Audit logging boundary."""


def record_audit_event(action: str, metadata: dict | None = None) -> dict:
    return {"action": action, "metadata": metadata or {}}
