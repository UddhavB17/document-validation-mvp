"""NDC checklist state endpoints (tmp/user-portal-ux)."""

from fastapi.testclient import TestClient

import database.db as db
from database.db import init_db
from main import app
from services.ops_ndc import NDC_VERSION


def _seed_application() -> int:
    init_db()
    with db.get_connection() as connection:
        created = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch, status)
            VALUES (?, ?, ?, ?, ?) RETURNING id
            """,
            ("LAP-NDC-1", "Meera Devi", "LAP", "Jaipur", "needs_review"),
        ).fetchone()
        return int(created["id"])


def test_ndc_get_returns_44_rows(tmp_path, monkeypatch, auth_headers) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id = _seed_application()
    client = TestClient(app)

    response = client.get(f"/ops/applications/{application_id}/ndc", headers=auth_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["version"] == NDC_VERSION
    assert payload["total"] == 44
    assert payload["complete"] is False
    assert payload["verified"] is False
    rows = payload["rows"]
    assert [row["s_no"] for row in rows] == list(range(1, 45))
    first = rows[0]
    assert first["group"] == "Application Form / KYC"
    assert first["title"]
    assert first["mode"]
    assert first["checks"]["cso"] == {"checked": False, "by": None, "by_name": "", "at": None}
    assert first["checks"]["cops"]["checked"] is False
    other = rows[-1]
    assert other["s_no"] == 44
    assert other["system_checked"] is False


def test_ndc_get_missing_application_returns_404(tmp_path, monkeypatch, auth_headers) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    _seed_application()
    client = TestClient(app)

    response = client.get("/ops/applications/99999/ndc", headers=auth_headers)

    assert response.status_code == 404


def test_ndc_put_rejects_bad_input(tmp_path, monkeypatch, auth_headers) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id = _seed_application()
    client = TestClient(app)

    bad_role = client.put(
        f"/ops/applications/{application_id}/ndc",
        headers=auth_headers,
        json={"s_no": 1, "role": "boss", "checked": True},
    )
    assert bad_role.status_code == 400

    bad_row = client.put(
        f"/ops/applications/{application_id}/ndc",
        headers=auth_headers,
        json={"s_no": 45, "role": "cso", "checked": True},
    )
    assert bad_row.status_code == 400

    missing_app = client.put(
        "/ops/applications/99999/ndc",
        headers=auth_headers,
        json={"s_no": 1, "role": "cso", "checked": True},
    )
    assert missing_app.status_code == 404


def test_ndc_tick_roundtrip(tmp_path, monkeypatch, auth_headers) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id = _seed_application()
    client = TestClient(app)

    ticked = client.put(
        f"/ops/applications/{application_id}/ndc",
        headers=auth_headers,
        json={"s_no": 44, "role": "cso", "checked": True},
    )
    assert ticked.status_code == 200, ticked.text
    row = next(r for r in ticked.json()["rows"] if r["s_no"] == 44)
    assert row["checks"]["cso"]["checked"] is True
    assert row["checks"]["cso"]["by_name"] != ""
    assert row["checks"]["cops"]["checked"] is False
    assert row["complete"] is False

    unticked = client.put(
        f"/ops/applications/{application_id}/ndc",
        headers=auth_headers,
        json={"s_no": 44, "role": "cso", "checked": False},
    )
    assert unticked.status_code == 200, unticked.text
    row = next(r for r in unticked.json()["rows"] if r["s_no"] == 44)
    assert row["checks"]["cso"]["checked"] is False


def test_ndc_requires_auth(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id = _seed_application()
    client = TestClient(app)

    assert client.get(f"/ops/applications/{application_id}/ndc").status_code in (401, 403)
