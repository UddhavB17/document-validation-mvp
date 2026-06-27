"""Report generation boundary."""


def build_report(application_id: int, exceptions: list[dict]) -> dict:
    return {"application_id": application_id, "exceptions": exceptions}
