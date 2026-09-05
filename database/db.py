"""Dialect-aware database wrapper (contracts §1, owned by ``ws-b-storage-db``).

``get_connection()`` keeps its historical name and shape: ``?`` positional
placeholders, a cursor-like object with ``.fetchone()`` / ``.fetchall()`` /
``.rowcount``, rows supporting ``row["col"]`` / ``dict(row)`` /
``row.keys()``, commit on success and rollback on exception.

The dialect is selected by ``DATABASE_URL``: empty means SQLite at
``DATABASE_PATH`` (default ``data/dmef.db``); otherwise the URL is a
PostgreSQL connection string served through SQLAlchemy. ``?`` placeholders
are translated to named bound parameters (``:p1``, ``:p2``, …) so the same
statement runs on both dialects. A literal ``?`` inside a quoted string
literal is left untouched. No ``%%`` escaping is needed: statements go
through ``sqlalchemy.text``, where ``%`` is always literal.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from services.paths import database_path

load_dotenv()

DATABASE_PATH = database_path()

_Engines: dict[str, Engine] = {}


def _database_url() -> str:
    """Return the configured Postgres URL, or ``""`` for SQLite."""
    raw = os.getenv("DATABASE_URL", "")
    return raw.strip() if isinstance(raw, str) else ""


def dialect() -> str:
    """Return the active dialect: ``"sqlite"`` or ``"postgresql"``."""
    return "postgresql" if _database_url() else "sqlite"


def _engine_key() -> str:
    url = _database_url()
    if url:
        return f"pg::{url}"
    return f"sqlite:///{DATABASE_PATH}"


def _sqlite_on_connect(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.execute("PRAGMA foreign_keys = ON")
    finally:
        cursor.close()


def _get_engine() -> Engine:
    """Return (and cache) the engine for the current configuration.

    The cache key is derived from the *current* ``DATABASE_URL`` /
    ``DATABASE_PATH`` values so tests can point the wrapper at temp files.
    """
    key = _engine_key()
    engine = _Engines.get(key)
    if engine is not None:
        return engine
    url = _database_url()
    if url:
        # requirements.txt ships psycopg v3; a bare ``postgresql://`` URL
        # would make SQLAlchemy look for psycopg2 instead.
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
        engine = create_engine(url, pool_pre_ping=True)
    else:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            f"sqlite:///{DATABASE_PATH}",
            connect_args={"check_same_thread": False, "timeout": 30.0},
        )
        event.listen(engine, "connect", _sqlite_on_connect)
    _Engines[key] = engine
    return engine


def _translate_placeholders(sql: str) -> tuple[str, int]:
    """Rewrite ``?`` placeholders to ``:p{n}`` named parameters.

    A ``?`` inside a single- or double-quoted string literal is left alone.
    Returns the rewritten SQL and the number of placeholders found.
    """
    out: list[str] = []
    count = 0
    quote: str | None = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote is not None:
            out.append(char)
            if char == quote:
                # A doubled quote inside a literal is an escaped quote.
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    out.append(sql[index + 1])
                    index += 1
                else:
                    quote = None
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            out.append(char)
        elif char == "?":
            count += 1
            out.append(f":p{count}")
        else:
            out.append(char)
        index += 1
    return "".join(out), count


class Row:
    """Dialect-neutral row: ``row["col"]``, ``row[0]``, ``dict(row)``."""

    __slots__ = ("_keys", "_values", "_mapping")

    def __init__(self, keys: Sequence[str], values: Sequence[Any]) -> None:
        self._keys = list(keys)
        self._values = list(values)
        self._mapping = dict(zip(self._keys, self._values, strict=False))

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def __contains__(self, key: object) -> bool:
        return key in self._mapping

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def get(self, key: str, default: Any = None) -> Any:
        return self._mapping.get(key, default)

    def keys(self) -> list[str]:
        return list(self._keys)

    def values(self) -> list[Any]:
        return list(self._values)

    def items(self) -> list[tuple[str, Any]]:
        return list(self._mapping.items())

    def __repr__(self) -> str:
        return f"Row({self._mapping!r})"


class Cursor:
    """Cursor-like result: ``.fetchone()`` / ``.fetchall()`` / ``.rowcount``."""

    def __init__(
        self,
        rows: list[Row] | None,
        rowcount: int,
        lastrowid: Any = None,
    ) -> None:
        self._rows = rows or []
        self._pos = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self) -> Row | None:
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchall(self) -> list[Row]:
        rest = self._rows[self._pos :]
        self._pos = len(self._rows)
        return rest


def _coerce_params(params: Any) -> tuple[Any, ...]:
    if params is None:
        return ()
    if isinstance(params, Mapping):
        raise TypeError("Named parameter mappings are not supported; use '?' placeholders")
    if isinstance(params, (list, tuple)):
        return tuple(params)
    return (params,)


class _Connection:
    """Thin wrapper around a SQLAlchemy connection with sqlite3-like errors.

    Transactions use SQLAlchemy autobegin: the first statement opens one and
    ``__exit__`` commits (or rolls back). Explicit ``commit()`` mid-block is
    tolerated (some callers commit early, e.g. settings updates).
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._connection: Any = None
        self._closed = False

    def _ensure_open(self) -> Any:
        if self._closed or self._connection is None:
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
        return self._connection

    def __enter__(self) -> _Connection:
        self._connection = self._engine.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, _tb: Any) -> None:
        try:
            if self._connection is not None:
                if exc_type is None:
                    self._connection.commit()
                else:
                    self._connection.rollback()
        finally:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            self._closed = True

    def execute(self, sql: str, params: Any = ()) -> Cursor:
        connection = self._ensure_open()
        # `executemany` support: a list of tuples/lists is fanned out as one
        # executemany call (used by bulk helpers and tests).
        if isinstance(params, list) and params and isinstance(params[0], (list, tuple)):
            return self.executemany(sql, params)
        coerced = _coerce_params(params)
        statement, count = _translate_placeholders(sql)
        bound = {f"p{number}": value for number, value in enumerate(coerced, start=1)}
        if count != len(coerced):
            raise ValueError(
                f"SQL has {count} placeholder(s) but {len(coerced)} parameter(s) were given"
            )
        result = connection.execute(text(statement), bound)
        # NB: never touch .lastrowid on rows-returning results — on some
        # drivers (psycopg) that closes the underlying cursor.
        lastrowid = None
        if not result.returns_rows:
            try:
                lastrowid = result.lastrowid
            except Exception:  # noqa: BLE001
                lastrowid = None
        if result.returns_rows:
            keys = list(result.keys())
            rows = [Row(keys, tuple(values)) for values in result.fetchall()]
            return Cursor(rows, result.rowcount, lastrowid)
        return Cursor(None, result.rowcount, lastrowid)

    def executemany(self, sql: str, seq_of_params: Sequence[Any]) -> Cursor:
        connection = self._ensure_open()
        statement, count = _translate_placeholders(sql)
        payload = []
        for params in seq_of_params:
            coerced = _coerce_params(params)
            if count != len(coerced):
                raise ValueError(
                    f"SQL has {count} placeholder(s) but {len(coerced)} parameter(s) were given"
                )
            payload.append({f"p{number}": value for number, value in enumerate(coerced, start=1)})
        result = connection.execute(text(statement), payload)
        try:
            lastrowid = result.lastrowid
        except Exception:  # noqa: BLE001
            lastrowid = None
        return Cursor(None, result.rowcount, lastrowid)

    def commit(self) -> None:
        connection = self._ensure_open()
        connection.commit()

    def rollback(self) -> None:
        connection = self._ensure_open()
        connection.rollback()

    def close(self) -> None:
        if not self._closed:
            try:
                if self._connection is not None:
                    self._connection.rollback()
            finally:
                if self._connection is not None:
                    self._connection.close()
                self._connection = None
                self._closed = True


@contextmanager
def get_connection() -> Iterator[_Connection]:
    """Yield a configured connection; commit on success, rollback on error."""
    wrapper = _Connection(_get_engine())
    with wrapper as connection:
        yield connection


def init_db() -> None:
    """Create tables for SQLite dev/test; verify connectivity on Postgres.

    On PostgreSQL the schema comes from alembic (baseline owned by ``ws-i``),
    so ``init_db()`` only verifies that a connection can be opened.
    """
    if dialect() == "postgresql":
        engine = _get_engine()
        with engine.connect():
            pass
        return
    from database import schema_registry
    from database.models import INDEX_STATEMENTS, SCHEMA_STATEMENTS

    with get_connection() as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        for statement in schema_registry.all_statements():
            connection.execute(statement)
        for statement in INDEX_STATEMENTS:
            connection.execute(statement)
        seed_defaults(connection)


def seed_defaults(connection: _Connection) -> None:
    """Seed ``system_settings`` defaults; dialect neutral (``ON CONFLICT``)."""
    defaults = [
        (
            "llm_enabled",
            "false",
            "bool",
            "llm",
            "Enable LLM Verification",
            "Enable LLM verification checks and checklist engine queries.",
        ),
        (
            "llm_provider",
            "ollama",
            "str",
            "llm",
            "LLM Provider",
            "Select the LLM backend provider (e.g. ollama, openai, gemini).",
        ),
        (
            "llm_model",
            "llama3.2",
            "str",
            "llm",
            "Model Name",
            "Name of the LLM model to run queries against.",
        ),
        (
            "min_confidence",
            "0.70",
            "float",
            "classification",
            "Min Classification Confidence",
            "Minimum confidence score required to auto-classify a page.",
        ),
        (
            "ocr.provider",
            "google_vision",
            "str",
            "ocr",
            "OCR Provider",
            "Use Google Vision API OCR for scanned pages.",
        ),
        (
            "google.vision.auth",
            "auto",
            "str",
            "ocr",
            "Google Vision Auth Mode",
            "Use API key, Application Default Credentials, or automatic Google Vision authentication.",
        ),
        (
            "google.vision.api_key",
            "",
            "secret",
            "ocr",
            "Google Vision API Key",
            "Optional Google Vision API key used only for OCR calls.",
        ),
        (
            "google.vision.feature",
            "DOCUMENT_TEXT_DETECTION",
            "str",
            "ocr",
            "Google Vision OCR Feature",
            "Google Vision feature used for OCR.",
        ),
        (
            "google.vision.timeout.seconds",
            "60",
            "int",
            "ocr",
            "Google Vision Timeout",
            "Timeout in seconds for each Google Vision OCR request.",
        ),
        (
            "google.vision.max_attempts",
            "3",
            "int",
            "ocr",
            "Google Vision Retry Attempts",
            "Retry transient Google Vision network and service failures before flagging a page.",
        ),
        (
            "google.vision.language_hints",
            "",
            "str",
            "ocr",
            "Google Vision Language Hints",
            "Optional comma-separated BCP-47 hints such as en,gu; leave blank for automatic multilingual detection.",
        ),
        (
            "google.vision.api_endpoint",
            "",
            "str",
            "ocr",
            "Google Vision API Endpoint",
            "Optional custom client endpoint for Google Vision.",
        ),
        (
            "google.vision.rest_url",
            "https://vision.googleapis.com/v1/images:annotate",
            "str",
            "ocr",
            "Google Vision REST URL",
            "REST endpoint used when authenticating Google Vision with an API key.",
        ),
        (
            "required_fields.pan",
            '["pan_number", "applicant_name", "date_of_birth"]',
            "json",
            "fields",
            "PAN Card Required Fields",
            "Fields required to validate a PAN Card.",
        ),
        (
            "required_fields.aadhaar",
            '["aadhaar_number", "applicant_name", "date_of_birth", "address", "pin_code"]',
            "json",
            "fields",
            "Aadhaar Required Fields",
            "Fields required to validate Aadhaar.",
        ),
        (
            "required_fields.voter_id",
            '["voter_id_number", "applicant_name", "date_of_birth", "address"]',
            "json",
            "fields",
            "Voter ID Required Fields",
            "Fields required to validate a Voter ID.",
        ),
        (
            "required_fields.driving_license",
            '["dl_number", "applicant_name", "date_of_birth", "validity_date", "is_expired"]',
            "json",
            "fields",
            "Driving License Required Fields",
            "Fields required to validate a Driving License.",
        ),
        (
            "required_fields.sanction_letter",
            '["applicant_name", "loan_amount"]',
            "json",
            "fields",
            "Sanction Letter Required Fields",
            "Fields required to validate a Sanction Letter.",
        ),
        (
            "required_fields.loan_agreement",
            '["applicant_name", "loan_amount"]',
            "json",
            "fields",
            "Loan Agreement Required Fields",
            "Fields required to validate a Loan Agreement.",
        ),
        (
            "required_fields.cibil_report",
            '["applicant_name"]',
            "json",
            "fields",
            "CIBIL Required Fields",
            "Fields required to validate a CIBIL report.",
        ),
        (
            "required_fields.crif_report",
            '["applicant_name"]',
            "json",
            "fields",
            "CRIF Required Fields",
            "Fields required to validate a CRIF report.",
        ),
        (
            "required_fields.bank_statement",
            '["applicant_name", "account_number", "ifsc"]',
            "json",
            "fields",
            "Bank Statement Required Fields",
            "Fields required to validate a Bank Statement.",
        ),
        (
            "required_fields.passbook",
            '["applicant_name", "account_number", "ifsc"]',
            "json",
            "fields",
            "Passbook Required Fields",
            "Fields required to validate a Passbook.",
        ),
        (
            "required_fields.cheque",
            '["applicant_name", "account_number", "ifsc"]',
            "json",
            "fields",
            "Cheque Required Fields",
            "Fields required to validate a Cheque.",
        ),
        (
            "required_fields.salary_slip",
            '["applicant_name", "salary_month", "net_salary"]',
            "json",
            "fields",
            "Salary Slip Required Fields",
            "Fields required to validate a Salary Slip.",
        ),
        (
            "required_fields.stamp_duty",
            '["stamp_duty_amount", "stamp_certificate_number", "stamp_jurisdiction_state", "stamp_first_party", "stamp_second_party"]',
            "json",
            "fields",
            "Stamp Duty Required Fields",
            "Fields required to validate a Stamp Duty document.",
        ),
        (
            "required_fields.insurance_consent",
            '["is_consent_given", "premium_amount"]',
            "json",
            "fields",
            "Insurance Consent Required Fields",
            "Fields required to validate Insurance Consent.",
        ),
        (
            "required_fields.clearance_report",
            '["search_result", "debtor_name", "pan_number"]',
            "json",
            "fields",
            "Clearance Report Required Fields",
            "Fields required to validate a Clearance/CERSAI Report.",
        ),
        (
            "required_fields.nach_form",
            '["account_number", "ifsc", "mandate_limit"]',
            "json",
            "fields",
            "NACH Form Required Fields",
            "Fields required to validate a NACH Mandate Form.",
        ),
        (
            "required_fields.utility_bill",
            "[]",
            "json",
            "fields",
            "Utility Bill Required Fields",
            "Utility bills are classified for presence only; their contents are not cross-checked.",
        ),
        (
            "required_fields.application_form",
            '["applicant_name", "aadhaar_number", "pan_number", "date_of_birth", "phone_number", "address", "pin_code", "loan_amount"]',
            "json",
            "fields",
            "Application Form Required Fields",
            "Fields required to validate an Application Form.",
        ),
    ]
    for key, val, val_type, cat, lbl, desc in defaults:
        connection.execute(
            """
            INSERT INTO system_settings
            (config_key, config_value, value_type, category, label, description)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(config_key) DO NOTHING
            """,
            (key, val, val_type, cat, lbl, desc),
        )

    # API OCR is now the supported production path. Upgrade the former seeded
    # default so existing installations do not remain on local OCR invisibly.
    connection.execute(
        """
        UPDATE system_settings
        SET config_value = 'google_vision',
            description = 'Use Google Vision API OCR for scanned pages.'
        WHERE config_key = 'ocr.provider' AND config_value IN ('local', 'auto', '')
        """
    )


# Backward-compatible alias for the pre-cutover seeding entry point.
seed_settings = seed_defaults
