"""End-to-end smoke runner: ten-file batch against a live API (ws-j-deploy-smoke).

Usage (operator only; never run by the agent against cloud without credentials):

    python scripts/smoke_batch.py --api URL --email E --password P \\
        --files tests/fixtures --timeout 1800
    python scripts/smoke_batch.py --api URL --email E --password P \\
        --files <dir-with-10-pdfs> --dry-run

Flow: login (``POST /auth/login``), ``POST /upload/batch`` with every
``*.pdf``/``*.zip`` in ``--files``, poll ``GET /upload/batch/{id}`` until
every item is terminal (``completed``/``failed``/``cancelled``), then for
each completed application ``GET /ops/applications/{id}`` and validate the
operations payload (contracts §5: valid shape, ≤ 5 findings, Hindi present,
≤ 50 KB, no internal keys). Prints a table (file, status, seconds,
findings, ops bytes).

Exit policy: non-zero when any item is still pending after ``--timeout`` or
any ops payload is invalid. Terminal ``failed``/``cancelled`` items (and
upload rejections) are smoke *warnings* printed with ``failure_reason``,
unless ``--require-clean`` is passed. NOTE: ``GET /ops/...`` 404s until
``fx-integrate-df`` lands, so live smoke needs that stream merged; dry-run
never touches ``/ops``.

``--dry-run`` validates arguments and prints the plan without any network
I/O (used by ``tests/test_smoke_script.py``). ``--dry-run`` against
``tests/fixtures/smoke`` (checked-in generated tiny PDFs, no loan-file PII)
must exit 0. Live mode still requires 1–10 pdf/zip files.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

FINDING_CODES = frozenset(
    {
        "NAME_MISMATCH",
        "ID_MISMATCH",
        "ADDRESS_MISMATCH",
        "MISSING_DOCUMENT",
        "BANK_STATEMENT_OLD",
        "PAGE_UNREADABLE",
        "OCR_FAILED",
        "DATA_MISSING",
        "PROCESSING_ERROR",
    }
)

FORBIDDEN_KEYS = frozenset({"rule_id", "ocr_text", "structured_content"})
OPS_STATUS_VALUES = frozenset({"needs_review", "clean", "processing", "failed"})
OPS_SIZE_BUDGET_BYTES = 50 * 1024

# Terminal-but-not-completed outcomes are smoke warnings, not hard failures
# (see pipeline_failure_is_fatal). "rejected" = upload accepted the batch
# but refused this file (no application_id assigned).
WARNABLE_STATUSES = frozenset({"failed", "cancelled", "rejected"})


def pipeline_failure_is_fatal(
    status: str, *, timed_out: bool, require_clean: bool
) -> bool:
    """Decide whether a non-completed pipeline item fails the smoke run.

    - Still pending after ``--timeout`` (``timed_out=True``): always fatal.
    - Terminal ``failed``/``cancelled``/``rejected``: a warning printed with
      ``failure_reason``, unless ``--require-clean`` was passed.
    - ``completed``: never fatal here (the ops-payload check decides).
    - Anything else: fatal (unknown state, stay strict).
    """
    if timed_out:
        return True
    if status in WARNABLE_STATUSES:
        return require_clean
    if status == "completed":
        return False
    return True


def collect_files(files_dir: Path) -> list[Path]:
    """Return sorted ``*.pdf``/``*.zip`` entries in ``files_dir``."""
    candidates = [
        entry
        for entry in sorted(files_dir.iterdir())
        if entry.is_file() and entry.suffix.lower() in {".pdf", ".zip"}
    ]
    return candidates


def _has_forbidden_key(payload: object) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_KEYS:
                return str(key)
            found = _has_forbidden_key(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _has_forbidden_key(item)
            if found is not None:
                return found
    return None


def validate_ops_payload(payload: object) -> list[str]:
    """Return a list of validation errors (empty = valid) per contracts §5."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["payload is not a JSON object"]
    if not isinstance(payload.get("application_id"), int):
        errors.append("missing/invalid application_id")
    if payload.get("status") not in OPS_STATUS_VALUES:
        errors.append(f"invalid status: {payload.get('status')!r}")
    summary = payload.get("summary")
    if not isinstance(summary, dict) or not str(summary.get("en", "")).strip():
        errors.append("summary.en is missing or empty")
    if not isinstance(summary, dict) or not str(summary.get("hi", "")).strip():
        errors.append("summary.hi is missing or empty (Hindi required)")
    findings = payload.get("top_findings")
    if not isinstance(findings, list):
        errors.append("top_findings is not a list")
        findings = []
    if len(findings) > 5:
        errors.append(f"top_findings has {len(findings)} items (budget: ≤ 5)")
    for index, finding in enumerate(findings):
        prefix = f"top_findings[{index}]"
        if not isinstance(finding, dict):
            errors.append(f"{prefix} is not an object")
            continue
        if finding.get("code") not in FINDING_CODES:
            errors.append(f"{prefix}.code invalid: {finding.get('code')!r}")
        if finding.get("severity") not in {"HIGH", "MEDIUM", "LOW"}:
            errors.append(f"{prefix}.severity invalid: {finding.get('severity')!r}")
        for section in ("title", "detail"):
            block = finding.get(section)
            if not isinstance(block, dict) or not str(block.get("en", "")).strip():
                errors.append(f"{prefix}.{section}.en is missing or empty")
            if not isinstance(block, dict) or not str(block.get("hi", "")).strip():
                errors.append(f"{prefix}.{section}.hi is missing or empty (Hindi required)")
        if not isinstance(finding.get("pages"), list):
            errors.append(f"{prefix}.pages is not a list")
        evidence = finding.get("evidence")
        if evidence is not None:
            if not isinstance(evidence, dict):
                errors.append(f"{prefix}.evidence is not an object")
            elif not isinstance(evidence.get("page"), int):
                errors.append(f"{prefix}.evidence.page is not an int")
    if not isinstance(payload.get("pages_to_verify"), list):
        errors.append("pages_to_verify is not a list")
    checklist = payload.get("checklist")
    if not isinstance(checklist, dict):
        errors.append("checklist is not an object")
    else:
        for key in ("total", "found", "missing", "not_checked", "rows"):
            if key not in checklist:
                errors.append(f"checklist.{key} is missing")
        if not isinstance(checklist.get("rows"), list):
            errors.append("checklist.rows is not a list")
    forbidden = _has_forbidden_key(payload)
    if forbidden is not None:
        errors.append(f"forbidden internal key present: {forbidden}")
    return errors


def print_plan(
    api: str, email: str, paths: list[Path], timeout: float, poll_interval: float
) -> None:
    names = ", ".join(path.name for path in paths) if paths else "(none)"
    print("Smoke plan (dry run, no network I/O):")
    print(f"  api:            {api}")
    print(f"  login:          POST {api}/auth/login as {email}")
    print(f"  upload:         POST {api}/upload/batch ({len(paths)} file(s): {names})")
    print(f"  poll:           GET {api}/upload/batch/{{id}} every {poll_interval:g}s")
    print("  ops check:      GET {api}/ops/applications/{id} per completed item")
    print("                  (valid payload, ≤ 5 findings, Hindi present, ≤ 50 KB)")
    print(f"  timeout:        {timeout:g}s; terminal = completed|failed|cancelled")


def print_table(rows: list[dict[str, object]]) -> None:
    headers = ("file", "status", "seconds", "findings", "ops_bytes")
    widths = [len(header) for header in headers]
    text_rows: list[tuple[str, str, str, str, str]] = []
    for row in rows:
        cells = (
            str(row.get("file", "-")),
            str(row.get("status", "-")),
            str(row.get("seconds", "-")),
            str(row.get("findings", "-")),
            str(row.get("ops_bytes", "-")),
        )
        text_rows.append(cells)
        for index, cell in enumerate(cells):
            widths[index] = max(widths[index], len(cell))
    fmt = "  ".join(f"{{:<{width}}}" for width in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * width for width in widths)))
    for cells in text_rows:
        print(fmt.format(*cells))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="API base URL, e.g. http://localhost:8000")
    parser.add_argument("--email", required=True, help="login email (admin)")
    parser.add_argument("--password", required=True, help="login password")
    parser.add_argument("--files", required=True, help="directory with PDFs/ZIPs to upload")
    parser.add_argument("--timeout", type=float, default=1800, help="overall timeout in seconds")
    parser.add_argument(
        "--poll-interval", type=float, default=5.0, help="batch status poll interval in seconds"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate arguments and print the plan without any network I/O",
    )
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="fail on failed/cancelled/rejected pipeline items "
        "(default: warn with failure_reason and exit 0 if ops payloads pass)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    api = str(args.api).rstrip("/")
    if not api.startswith(("http://", "https://")):
        print(f"error: --api must be an http(s) URL, got {args.api!r}", file=sys.stderr)
        return 2
    files_dir = Path(str(args.files))
    if not files_dir.is_dir():
        print(f"error: --files is not a directory: {files_dir}", file=sys.stderr)
        return 2
    if not str(args.email).strip() or not str(args.password):
        print("error: --email/--password must be non-empty", file=sys.stderr)
        return 2
    if not args.timeout or float(args.timeout) <= 0:
        print("error: --timeout must be a positive number of seconds", file=sys.stderr)
        return 2
    paths = collect_files(files_dir)
    if not paths:
        print(f"error: no .pdf/.zip files found in {files_dir}", file=sys.stderr)
        return 2
    if len(paths) > 10:
        print(
            f"error: {len(paths)} files found; a batch accepts at most 10 "
            "(split into smaller dirs)",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        print_plan(api, str(args.email), paths, float(args.timeout), float(args.poll_interval))
        return 0

    try:
        import requests
    except ImportError:
        print("error: the 'requests' package is required (pip install -r requirements.txt)",
              file=sys.stderr)
        return 2

    started = time.monotonic()
    deadline = started + float(args.timeout)
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    try:
        login_response = session.post(
            f"{api}/auth/login",
            json={"email": args.email, "password": args.password},
            timeout=30,
        )
    except Exception as exc:
        print(f"error: login request failed: {exc}", file=sys.stderr)
        return 1
    if login_response.status_code != 200:
        print(
            f"error: login failed with HTTP {login_response.status_code}: "
            f"{login_response.text[:300]}",
            file=sys.stderr,
        )
        return 1
    try:
        token = login_response.json().get("token") or login_response.json().get("access_token")
    except ValueError:
        token = None
    if not token:
        print("error: login response did not contain a token", file=sys.stderr)
        return 1
    session.headers.update({"Authorization": f"Bearer {token}"})

    multipart = []
    handles = []
    for path in paths:
        content_type = "application/zip" if path.suffix.lower() == ".zip" else "application/pdf"
        handle = path.open("rb")
        handles.append(handle)
        multipart.append(("files", (path.name, handle, content_type)))
    try:
        upload_response = session.post(f"{api}/upload/batch", files=multipart, timeout=300)
    except Exception as exc:
        print(f"error: batch upload failed: {exc}", file=sys.stderr)
        return 1
    finally:
        for handle in handles:
            handle.close()
    if upload_response.status_code != 200:
        print(
            f"error: POST /upload/batch failed with HTTP {upload_response.status_code}: "
            f"{upload_response.text[:500]}",
            file=sys.stderr,
        )
        return 1
    try:
        batch = upload_response.json()
    except ValueError:
        print("error: batch upload response was not JSON", file=sys.stderr)
        return 1
    batch_id = batch.get("batch_id")
    if not batch_id:
        print("error: batch upload response did not contain batch_id", file=sys.stderr)
        return 1
    print(f"batch_id: {batch_id}")

    rejected = [
        item for item in batch.get("items", []) if item.get("application_id") is None
    ]
    for item in rejected:
        print(f"rejected: {item.get('filename')} — {item.get('reason')}")

    latest: dict[int, dict[str, object]] = {}
    poll_interval = max(1.0, float(args.poll_interval))
    while True:
        now = time.monotonic()
        if now > deadline:
            break
        try:
            status_response = session.get(f"{api}/upload/batch/{batch_id}", timeout=30)
        except Exception as exc:
            print(f"warning: batch poll failed: {exc}", file=sys.stderr)
            time.sleep(poll_interval)
            continue
        if status_response.status_code != 200:
            print(
                f"warning: GET /upload/batch/{batch_id} -> HTTP "
                f"{status_response.status_code}",
                file=sys.stderr,
            )
            time.sleep(poll_interval)
            continue
        try:
            items = status_response.json().get("items", [])
        except ValueError:
            items = []
        for item in items:
            app_id = item.get("application_id")
            if isinstance(app_id, int):
                latest[app_id] = item
        pending = [item for item in items if str(item.get("status")) not in TERMINAL_STATUSES]
        if not pending and items:
            break
        time.sleep(poll_interval)

    rows: list[dict[str, object]] = []
    failures = 0
    warnings = 0
    for item in rejected:
        reason = item.get("reason") or "no reason returned"
        if pipeline_failure_is_fatal(
            "rejected", timed_out=False, require_clean=args.require_clean
        ):
            failures += 1
        else:
            warnings += 1
            print(f"warning: {item.get('filename')} rejected: {reason}")
        rows.append(
            {
                "file": str(item.get("filename", "-")),
                "status": "rejected",
                "seconds": f"{time.monotonic() - started:.1f}",
                "findings": "-",
                "ops_bytes": "-",
            }
        )

    for item in sorted(latest.values(), key=lambda entry: str(entry.get("filename", ""))):
        filename = str(item.get("filename", "-"))
        status = str(item.get("status", "?"))
        elapsed = time.monotonic() - started
        app_id = item.get("application_id")
        if status not in TERMINAL_STATUSES:
            failures += 1
            print(f"timeout: {filename} still {status} after {args.timeout:g}s")
            rows.append(
                {
                    "file": filename,
                    "status": status,
                    "seconds": f"{elapsed:.1f}",
                    "findings": "-",
                    "ops_bytes": "-",
                }
            )
            continue
        if status != "completed":
            reason = item.get("failure_reason") or "no failure_reason returned"
            if pipeline_failure_is_fatal(
                status, timed_out=False, require_clean=args.require_clean
            ):
                failures += 1
                print(f"failed: {filename} (application {app_id}): {reason}")
            else:
                warnings += 1
                print(f"warning: {filename} (application {app_id}) status={status}: {reason}")
            rows.append(
                {
                    "file": filename,
                    "status": status,
                    "seconds": f"{elapsed:.1f}",
                    "findings": "-",
                    "ops_bytes": "-",
                }
            )
            continue
        try:
            ops_response = session.get(f"{api}/ops/applications/{app_id}", timeout=60)
        except Exception as exc:
            failures += 1
            print(f"invalid: {filename} ops fetch failed: {exc}")
            rows.append(
                {
                    "file": filename,
                    "status": status,
                    "seconds": f"{elapsed:.1f}",
                    "findings": "?",
                    "ops_bytes": "?",
                }
            )
            continue
        if ops_response.status_code != 200:
            failures += 1
            print(
                f"invalid: {filename} GET /ops/applications/{app_id} -> "
                f"HTTP {ops_response.status_code}: {ops_response.text[:300]}"
            )
            rows.append(
                {
                    "file": filename,
                    "status": status,
                    "seconds": f"{elapsed:.1f}",
                    "findings": "?",
                    "ops_bytes": len(ops_response.content),
                }
            )
            continue
        try:
            payload = ops_response.json()
        except ValueError:
            failures += 1
            print(f"invalid: {filename} ops response was not JSON")
            rows.append(
                {
                    "file": filename,
                    "status": status,
                    "seconds": f"{elapsed:.1f}",
                    "findings": "?",
                    "ops_bytes": len(ops_response.content),
                }
            )
            continue
        ops_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        errors = validate_ops_payload(payload)
        if ops_bytes > OPS_SIZE_BUDGET_BYTES:
            errors.append(f"ops payload {ops_bytes} bytes exceeds 50 KB budget")
        findings = payload.get("top_findings", [])
        count = len(findings) if isinstance(findings, list) else "?"
        if errors:
            failures += 1
            print(f"invalid: {filename} ops payload errors: {'; '.join(errors)}")
        rows.append(
            {
                "file": filename,
                "status": status,
                "seconds": f"{elapsed:.1f}",
                "findings": count,
                "ops_bytes": ops_bytes,
            }
        )

    print_table(rows)
    if failures:
        print(f"smoke FAILED: {failures} problem item(s)", file=sys.stderr)
        return 1
    suffix = f" (+{warnings} warning(s))" if warnings else ""
    print(f"smoke OK: {len(rows)} file(s), all terminal with valid ops payloads{suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
