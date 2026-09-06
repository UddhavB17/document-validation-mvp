"""Authentication tests for ``ws-d-auth`` (contracts §6)."""

from __future__ import annotations

import os
import re
import time

import jwt
import pytest
from fastapi.testclient import TestClient

import database.db as db
import routes.auth as auth_routes
from database.db import get_connection, init_db
from main import app
from services.auth.bootstrap import bootstrap_admin
from services.auth.service import create_user
from services.auth.tokens import decode

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Str0ngPassw0rd!"
OPS_EMAIL = "ops@example.com"
OPS_PASSWORD = "0psStr0ngPass!"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_AUTH_SECRET", "test-auth-secret")
    monkeypatch.setenv("DMEF_BOOTSTRAP_ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("DMEF_BOOTSTRAP_ADMIN_PASSWORD", ADMIN_PASSWORD)
    init_db()
    bootstrap_admin()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_rate_limit():
    auth_routes._LOGIN_ATTEMPTS.clear()
    yield
    auth_routes._LOGIN_ATTEMPTS.clear()


def _login(client, email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def _admin_headers(client):
    return {"Authorization": f"Bearer {_login(client)['token']}"}


def _create_ops_user(client, headers):
    response = client.post(
        "/admin/users",
        headers=headers,
        json={
            "email": OPS_EMAIL,
            "display_name": "Ops Reviewer",
            "role": "operations",
            "password": OPS_PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_bootstrap_creates_admin_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_AUTH_SECRET", "test-auth-secret")
    monkeypatch.setenv("DMEF_BOOTSTRAP_ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("DMEF_BOOTSTRAP_ADMIN_PASSWORD", ADMIN_PASSWORD)
    init_db()

    first = bootstrap_admin()
    second = bootstrap_admin()

    assert first is not None and first["role"] == "admin"
    assert second is None
    with get_connection() as connection:
        total = connection.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
    assert total == 1


def test_bootstrap_requires_credentials_when_users_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.delenv("DMEF_BOOTSTRAP_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("DMEF_BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    init_db()

    with pytest.raises(RuntimeError, match="DMEF_BOOTSTRAP_ADMIN"):
        bootstrap_admin()


def test_missing_auth_secret_raises_clear_error(monkeypatch) -> None:
    monkeypatch.delenv("DMEF_AUTH_SECRET", raising=False)
    from services.auth.tokens import auth_secret

    with pytest.raises(RuntimeError, match="DMEF_AUTH_SECRET is not set"):
        auth_secret()


def test_login_success_returns_token_and_user(client) -> None:
    body = _login(client)

    assert body["user"] == {
        "id": body["user"]["id"],
        "email": ADMIN_EMAIL,
        "display_name": "Administrator",
        "role": "admin",
    }
    payload = decode(body["token"])
    assert payload["role"] == "admin"
    assert payload["email"] == ADMIN_EMAIL

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == ADMIN_EMAIL


def test_login_failure_returns_401_and_audits(client) -> None:
    assert (
        client.post(
            "/auth/login", json={"email": ADMIN_EMAIL, "password": "WrongPassword123"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": "WrongPassword123"}
        ).status_code
        == 401
    )
    _login(client)

    with get_connection() as connection:
        actions = [
            row["action"]
            for row in connection.execute(
                "SELECT action FROM audit_log WHERE application_id IS NULL ORDER BY id"
            ).fetchall()
        ]
    assert "login_failure" in actions
    assert "login_success" in actions


def test_expired_token_is_rejected(client) -> None:
    secret = os.environ["DMEF_AUTH_SECRET"]
    token = jwt.encode(
        {
            "sub": "1",
            "email": ADMIN_EMAIL,
            "role": "admin",
            "exp": int(time.time()) - 10,
        },
        secret,
        algorithm="HS256",
    )

    assert client.get("/auth/me").status_code == 401
    assert (
        client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code
        == 401
    )
    assert (
        client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )


def test_inactive_user_cannot_login_and_token_stops_working(client) -> None:
    headers = _admin_headers(client)
    ops = _create_ops_user(client, headers)
    ops_token = _login(client, OPS_EMAIL, OPS_PASSWORD)["token"]

    response = client.patch(
        f"/admin/users/{ops['id']}", headers=headers, json={"is_active": False}
    )
    assert response.status_code == 200

    assert (
        client.post(
            "/auth/login", json={"email": OPS_EMAIL, "password": OPS_PASSWORD}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/review/worklist", headers={"Authorization": f"Bearer {ops_token}"}
        ).status_code
        == 401
    )


def test_operations_user_forbidden_on_settings_but_ok_on_worklist(client) -> None:
    headers = _admin_headers(client)
    _create_ops_user(client, headers)
    ops_headers = {"Authorization": f"Bearer {_login(client, OPS_EMAIL, OPS_PASSWORD)['token']}"}

    assert client.get("/settings", headers=ops_headers).status_code == 403
    assert client.post("/upload/file", headers=ops_headers).status_code == 403

    worklist = client.get("/review/worklist", headers=ops_headers)
    assert worklist.status_code == 200
    assert worklist.json()["items"] == []


def test_admin_can_create_operations_user(client) -> None:
    headers = _admin_headers(client)
    created = _create_ops_user(client, headers)

    assert created["email"] == OPS_EMAIL
    assert created["role"] == "operations"
    assert "password_hash" not in str(created)
    body = _login(client, OPS_EMAIL, OPS_PASSWORD)
    assert body["user"]["role"] == "operations"

    with get_connection() as connection:
        actions = [
            row["action"]
            for row in connection.execute(
                "SELECT action FROM audit_log WHERE application_id IS NULL"
            ).fetchall()
        ]
    assert "user_created" in actions


def test_admin_user_endpoints_validate_input(client) -> None:
    headers = _admin_headers(client)

    bad_role = client.post(
        "/admin/users",
        headers=headers,
        json={
            "email": "bad@example.com",
            "display_name": "Bad",
            "role": "superuser",
            "password": "AVeryStr0ngPass!",
        },
    )
    assert bad_role.status_code == 400

    weak = client.post(
        "/admin/users",
        headers=headers,
        json={
            "email": "weak@example.com",
            "display_name": "Weak",
            "role": "operations",
            "password": "short",
        },
    )
    assert weak.status_code == 400

    with pytest.raises(ValueError, match="at least 10"):
        create_user(
            email="short@example.com",
            display_name="Short",
            role="operations",
            password="short",
        )
    with pytest.raises(ValueError, match="too common"):
        create_user(
            email="common@example.com",
            display_name="Common",
            role="operations",
            password="password123",
        )


def test_admin_cannot_deactivate_self(client) -> None:
    headers = _admin_headers(client)
    admin_id = client.get("/auth/me", headers=headers).json()["id"]

    response = client.patch(
        f"/admin/users/{admin_id}", headers=headers, json={"is_active": False}
    )
    assert response.status_code == 400

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200


def test_non_admin_cannot_manage_users(client) -> None:
    headers = _admin_headers(client)
    _create_ops_user(client, headers)
    ops_headers = {"Authorization": f"Bearer {_login(client, OPS_EMAIL, OPS_PASSWORD)['token']}"}

    assert client.get("/admin/users", headers=ops_headers).status_code == 403
    assert (
        client.post(
            "/admin/users",
            headers=ops_headers,
            json={
                "email": "x@example.com",
                "display_name": "X",
                "role": "operations",
                "password": "AVeryStr0ngPass!",
            },
        ).status_code
        == 403
    )


def test_change_password_and_admin_reset(client) -> None:
    headers = _admin_headers(client)
    ops = _create_ops_user(client, headers)
    ops_headers = {"Authorization": f"Bearer {_login(client, OPS_EMAIL, OPS_PASSWORD)['token']}"}

    changed = client.post(
        "/auth/change-password",
        headers=ops_headers,
        json={"current_password": OPS_PASSWORD, "new_password": "New0psPassword!"},
    )
    assert changed.status_code == 200
    assert (
        client.post(
            "/auth/login", json={"email": OPS_EMAIL, "password": OPS_PASSWORD}
        ).status_code
        == 401
    )
    fresh = _login(client, OPS_EMAIL, "New0psPassword!")
    assert fresh["user"]["email"] == OPS_EMAIL

    reset = client.post(
        f"/admin/users/{ops['id']}/password",
        headers=headers,
        json={"new_password": "Reset0psPass!!"},
    )
    assert reset.status_code == 200
    _login(client, OPS_EMAIL, "Reset0psPass!!")

    with get_connection() as connection:
        actions = [
            row["action"]
            for row in connection.execute(
                "SELECT action FROM audit_log WHERE application_id IS NULL"
            ).fetchall()
        ]
    assert "password_changed" in actions


def test_login_rate_limit(client) -> None:
    for _ in range(10):
        response = client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "WrongPassword123"},
        )
        assert response.status_code == 401
    limited = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "WrongPassword123"},
    )
    assert limited.status_code == 429


def test_logout_is_noop_ok(client) -> None:
    headers = _admin_headers(client)
    assert client.post("/auth/logout", headers=headers).status_code == 200


OPEN_PATHS = {
    "/health",
    "/auth/login",
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
}


def _iter_protected_routes():
    """Yield ``(method, path)`` for every API route, expanding the lazy
    ``_IncludedRouter`` wrappers FastAPI 0.141 keeps in ``app.routes``."""
    seen: set[tuple[str, str]] = set()
    for route in app.routes:
        inner = getattr(route, "original_router", None)
        candidates = list(inner.routes) if inner is not None else [route]
        for candidate in candidates:
            methods = getattr(candidate, "methods", None) or set()
            path = getattr(candidate, "path", None)
            if not path:
                continue
            for method in methods:
                if method in {"HEAD", "OPTIONS"}:
                    continue
                key = (method, path)
                if key not in seen:
                    seen.add(key)
                    yield key


def test_every_route_requires_auth(tmp_path, monkeypatch) -> None:
    """Every backend route except the open set returns 401 without a token."""
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_AUTH_SECRET", "test-auth-secret")
    init_db()
    unauthenticated = TestClient(app)

    checked = 0
    for method, path in _iter_protected_routes():
        if path in OPEN_PATHS:
            continue
        concrete = re.sub(r"\{[^}]+\}", "1", path)
        kwargs = {"json": {}} if method in {"POST", "PUT", "PATCH"} else {}
        response = unauthenticated.request(method, concrete, **kwargs)
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
        checked += 1
    assert checked > 10


def test_retention_run_accepts_scheduler_bearer(client, monkeypatch) -> None:
    """POST /admin/retention/run: scheduler bearer or admin JWT; else 401/403."""
    monkeypatch.setenv("DMEF_SCHEDULER_TOKEN", "scheduler-test-token")
    assert client.post("/admin/retention/run?dry_run=true").status_code == 401
    scheduled = client.post(
        "/admin/retention/run?dry_run=true",
        headers={"Authorization": "Bearer scheduler-test-token"},
    )
    assert scheduled.status_code == 200
    assert scheduled.json()["dry_run"] is True
    assert client.post(
        "/admin/retention/run?dry_run=true",
        headers=_admin_headers(client),
    ).status_code == 200
    _create_ops_user(client, _admin_headers(client))
    ops_token = _login(client, OPS_EMAIL, OPS_PASSWORD)["token"]
    assert client.post(
        "/admin/retention/run?dry_run=true",
        headers={"Authorization": f"Bearer {ops_token}"},
    ).status_code == 403
