from unittest.mock import patch, MagicMock
import pytest
from views.results_view import render_application_results

def setup_mock_st(mock_st):
    # Mock return values for columns to allow unpacking
    mock_st.columns.side_effect = lambda n: [MagicMock() for _ in range(n)]

@patch("views.results_view.st")
@patch("views.results_view._load_application_result")
def test_render_application_results_ocr_used(mock_load, mock_st):
    setup_mock_st(mock_st)
    mock_load.return_value = {
        "application": {"loan_id": "L123", "product_type": "LAP", "status": "PENDING"},
        "ground_truth": {},
        "anomalies": [],
        "pages": [{"page_number": 1, "page_type": "scanned"}],
        "documents_found": [],
        "document_pages": {},
        "documents_missing": [],
        "uploaded_file": {}
    }

    render_application_results(123)

    mock_st.subheader.assert_any_call("OCR")
    mock_st.write.assert_any_call("true")

@patch("views.results_view.st")
@patch("views.results_view._load_application_result")
def test_render_application_results_ocr_not_used(mock_load, mock_st):
    setup_mock_st(mock_st)
    mock_load.return_value = {
        "application": {"loan_id": "L123", "product_type": "LAP", "status": "PENDING"},
        "ground_truth": {},
        "anomalies": [],
        "pages": [{"page_number": 1, "page_type": "digital"}],
        "documents_found": [],
        "document_pages": {},
        "documents_missing": [],
        "uploaded_file": {}
    }

    render_application_results(123)

    mock_st.subheader.assert_any_call("OCR")
    mock_st.write.assert_any_call("false")
