from unittest.mock import call, patch, MagicMock
import pytest
from views.results_view import render_application_results

def setup_mock_st(mock_st):
    # Mock return values for columns to allow unpacking
    all_columns = []

    def columns(n):
        column_mocks = [MagicMock() for _ in range(n)]
        for column in column_mocks:
            column.button.return_value = False
        all_columns.extend(column_mocks)
        return column_mocks

    mock_st.columns.side_effect = columns
    # A generic MagicMock is truthy, which would otherwise simulate clicking
    # every Streamlit button and send a real decision request to the API.
    mock_st.button.return_value = False
    return all_columns

@patch("views.results_view.st")
@patch("views.results_view._load_application_result")
def test_render_application_results_ocr_used(mock_load, mock_st):
    columns = setup_mock_st(mock_st)
    mock_load.return_value = {
        "application": {"loan_id": "L123", "product_type": "LAP", "status": "PENDING"},
        "ground_truth": {},
        "anomalies": [],
        "pages": [{"page_number": 1, "page_type": "scanned"}],
        "documents_found": [],
        "document_pages": {},
        "documents_missing": [],
        "uploaded_file": {"total_pages": 1, "digital_pages": 0, "scanned_pages": 1}
    }

    render_application_results(123)

    assert any(column.metric.call_args_list for column in columns)
    assert any(call("Scanned", 1) in column.metric.call_args_list for column in columns)

@patch("views.results_view.st")
@patch("views.results_view._load_application_result")
def test_render_application_results_ocr_not_used(mock_load, mock_st):
    columns = setup_mock_st(mock_st)
    mock_load.return_value = {
        "application": {"loan_id": "L123", "product_type": "LAP", "status": "PENDING"},
        "ground_truth": {},
        "anomalies": [],
        "pages": [{"page_number": 1, "page_type": "digital"}],
        "documents_found": [],
        "document_pages": {},
        "documents_missing": [],
        "uploaded_file": {"total_pages": 1, "digital_pages": 1, "scanned_pages": 0}
    }

    render_application_results(123)

    assert any(call("Digital", 1) in column.metric.call_args_list for column in columns)
    assert any(call("Scanned", "-") in column.metric.call_args_list for column in columns)
