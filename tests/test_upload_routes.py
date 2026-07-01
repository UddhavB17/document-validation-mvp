from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import database.db as db
import routes.upload as upload_route
from main import app


def _create_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Applicant Name: Ramesh Kumar\nPAN: ABCDE1234F\nLoan Amount: 500000")
    doc.save(path)
    doc.close()


class _Spinner:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeStreamlit:
    def __init__(self) -> None:
        self.session_state = {}
        self.success_messages = []
        self.error_messages = []
        self.write_messages = []

    def spinner(self, _message: str) -> _Spinner:
        return _Spinner()

    def success(self, message: str) -> None:
        self.success_messages.append(message)

    def error(self, message: str) -> None:
        self.error_messages.append(message)

    def write(self, message: str) -> None:
        self.write_messages.append(message)


def test_partner_json_runs_validation_pipeline(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    client = TestClient(app)

    response = client.post(
        "/upload/json",
        json={
            "loan_id": "LAP-JSON-001",
            "applicant_name": "Ramesh Kumar",
            "product_type": "LAP",
            "branch": "Delhi",
            "digital_text": {
                "applicant_name": "Ramesh Kumar",
                "pan_number": "ABCDE1234F",
                "loan_amount": "500000",
            },
            "scanned_docs": {
                "pan_card": "INCOME TAX DEPARTMENT\nName: Ramesh Kumar\nABCDE1234F",
                "bank_statement": "Account Number: 123456789012\nStatement Date: 30/04/2026",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["application_id"]
    assert body["pipeline_status"] == "completed"
    assert body["status"] in {"CLEAN", "NEEDS_REVIEW", "CRITICAL"}
    assert "PAN" in body["documents_found"]

    with db.get_connection() as connection:
        page_count = connection.execute(
            "SELECT COUNT(*) AS total FROM pages WHERE application_id = ?",
            (body["application_id"],),
        ).fetchone()["total"]
        ground_truth = connection.execute(
            "SELECT pan_number FROM ground_truth WHERE application_id = ?",
            (body["application_id"],),
        ).fetchone()

    assert page_count == 2
    assert ground_truth["pan_number"] == "ABCDE1234F"


def test_pdf_upload_route_returns_processing_queued(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(upload_route, "run_pipeline", lambda *_args, **_kwargs: None)

    pdf_path = tmp_path / "upload.pdf"
    _create_pdf(pdf_path)
    client = TestClient(app)

    response = client.post(
        "/upload",
        data={
            "loan_id": "LAP-UPLOAD-001",
            "applicant_name": "Ramesh Kumar",
            "coapplicant_name": "",
            "product_type": "LAP",
            "branch": "Delhi",
        },
        files={"file": ("upload.pdf", pdf_path.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["pipeline_status"] == "queued"
    assert body["loan_id"] == "LAP-UPLOAD-001"


def test_upload_view_posts_real_form_metadata(monkeypatch) -> None:
    import views.upload_view as upload_view

    fake_st = _FakeStreamlit()
    posted = {}

    def fake_post(_url, *, data, files, timeout):
        posted["data"] = data
        posted["files"] = files
        posted["timeout"] = timeout
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "application_id": 42,
                "status": "processing",
                "total_pages": 3,
                "digital_pages": 1,
                "scanned_pages": 2,
            },
        )

    uploaded_file = SimpleNamespace(
        name="loan.pdf",
        size=1024,
        getvalue=lambda: b"%PDF-1.7\n",
    )

    monkeypatch.setattr(upload_view, "st", fake_st)
    monkeypatch.setattr(upload_view.requests, "post", fake_post)

    upload_view._submit_upload_form(
        "LAP-001",
        "Ramesh Kumar",
        "Sita Kumar",
        "MSME",
        "Delhi",
        uploaded_file,
    )

    assert posted["data"] == {
        "loan_id": "LAP-001",
        "applicant_name": "Ramesh Kumar",
        "coapplicant_name": "Sita Kumar",
        "product_type": "MSME",
        "branch": "Delhi",
    }
    assert fake_st.session_state["last_uploaded_application_id"] == 42
    assert not fake_st.error_messages


def test_partner_json_view_posts_to_api_and_renders_results(monkeypatch) -> None:
    import views.upload_view as upload_view

    fake_st = _FakeStreamlit()
    rendered = []
    payload = {
        "loan_id": "LAP-JSON-001",
        "applicant_name": "Ramesh Kumar",
        "product_type": "LAP",
        "branch": "Delhi",
        "digital_text": {"applicant_name": "Ramesh Kumar"},
        "scanned_docs": {"pan_card": "PAN ABCDE1234F"},
    }

    def fake_post(url, *, json, timeout):
        assert url.endswith("/upload/json")
        assert json == payload
        assert timeout == 180
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "application_id": 99,
                "status": "NEEDS_REVIEW",
                "anomaly_count": 1,
                "documents_found": ["PAN"],
            },
        )

    monkeypatch.setattr(upload_view, "st", fake_st)
    monkeypatch.setattr(upload_view.requests, "post", fake_post)
    monkeypatch.setattr(upload_view, "render_application_results", lambda application_id: rendered.append(application_id))

    upload_view._submit_partner_json(payload)

    assert fake_st.session_state["last_uploaded_application_id"] == 99
    assert rendered == [99]
    assert any("Issues found: 1" in message for message in fake_st.success_messages)
