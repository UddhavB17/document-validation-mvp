"""Worker supervision tests: launcher, watchdog, admin start endpoint."""

from __future__ import annotations

import pytest

import database.db as db
from database.db import init_db


def _seed_fresh_heartbeat(worker_id: str = "test-worker") -> None:
    from database.worker_heartbeat import update_heartbeat

    update_heartbeat(worker_id)


def test_launcher_noop_when_heartbeat_fresh(tmp_path, monkeypatch) -> None:
    import services.worker_launcher as launcher

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    init_db()
    _seed_fresh_heartbeat()

    spawned: list = []
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: spawned.append((a, k)))

    result = launcher.ensure_worker_running("test")
    assert result["started"] is False
    assert spawned == []
    assert launcher.is_worker_alive() is True
    assert launcher.has_active_work() is False


def test_launcher_spawns_detached_worker_with_logs_when_stale(tmp_path, monkeypatch) -> None:
    import sys

    import services.worker_launcher as launcher

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    init_db()

    calls: list = []

    class FakeProc:
        pid = 4242

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return FakeProc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    result = launcher.ensure_worker_running("test")
    assert result["started"] is True
    assert result["pid"] == 4242
    assert result["out_log"].endswith("worker-out.log")
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert list(args) == [sys.executable, "-m", "services.worker"]
    assert str(kwargs.get("cwd", "")) == str(launcher.repo_root())


def test_watchdog_disabled_in_production(monkeypatch) -> None:
    import services.worker_watchdog as watchdog

    monkeypatch.setenv("DMEF_ENV", "production")
    monkeypatch.delenv("DMEF_WORKER_WATCHDOG", raising=False)
    assert watchdog._watchdog_enabled() is False
    assert watchdog.start_worker_watchdog() is False


@pytest.mark.parametrize("value", ["false", "0", "off", "no"])
def test_watchdog_explicit_opt_out_disables_local_spawning(monkeypatch, value) -> None:
    import services.worker_watchdog as watchdog

    monkeypatch.setenv("DMEF_ENV", "local")
    monkeypatch.setenv("DMEF_WORKER_WATCHDOG", value)

    assert watchdog._watchdog_enabled() is False


def test_watchdog_heals_stale_worker_with_pending_work(monkeypatch) -> None:
    import services.worker_launcher as launcher
    import services.worker_watchdog as watchdog

    monkeypatch.setenv("DMEF_ENV", "local")
    monkeypatch.delenv("DMEF_WORKER_WATCHDOG", raising=False)
    assert watchdog._watchdog_enabled() is True

    monkeypatch.setattr(launcher, "has_active_work", lambda: True)
    monkeypatch.setattr(launcher, "is_worker_alive", lambda: False)
    spawned: list = []
    monkeypatch.setattr(
        launcher,
        "ensure_worker_running",
        lambda reason: spawned.append(reason) or {"started": True},
    )
    monkeypatch.setattr(watchdog, "_min_spawn_gap_seconds", lambda: 0)
    watchdog._last_spawn_at = 0.0

    watchdog._watchdog_once()
    assert spawned == ["watchdog: active jobs with stale heartbeat"]


def test_watchdog_idle_when_no_work_or_worker_alive(monkeypatch) -> None:
    import services.worker_launcher as launcher
    import services.worker_watchdog as watchdog

    monkeypatch.setenv("DMEF_ENV", "local")
    monkeypatch.setattr(launcher, "has_active_work", lambda: False)
    monkeypatch.setattr(launcher, "is_worker_alive", lambda: False)
    spawned: list = []
    monkeypatch.setattr(launcher, "ensure_worker_running", lambda reason: spawned.append(reason))
    watchdog._watchdog_once()
    assert spawned == []

    monkeypatch.setattr(launcher, "has_active_work", lambda: True)
    monkeypatch.setattr(launcher, "is_worker_alive", lambda: True)
    watchdog._watchdog_once()
    assert spawned == []


def test_admin_worker_start_endpoint(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import routes.auth as auth_routes
    from main import app
    from services.auth.bootstrap import bootstrap_admin

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_AUTH_SECRET", "test-auth-secret")
    monkeypatch.setenv("DMEF_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("DMEF_BOOTSTRAP_ADMIN_PASSWORD", "Str0ngPassw0rd!")
    monkeypatch.setenv("DMEF_ENV", "local")
    init_db()
    bootstrap_admin()
    auth_routes._LOGIN_ATTEMPTS.clear()
    client = TestClient(app)

    token = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "Str0ngPassw0rd!"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Fresh heartbeat -> no spawn.
    _seed_fresh_heartbeat()
    spawned: list = []
    monkeypatch.setattr(
        "services.worker_launcher.ensure_worker_running",
        lambda reason: spawned.append(reason) or {"started": True},
    )
    response = client.post("/admin/worker/start", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["started"] is False
    assert spawned == []

    # Stale heartbeat -> supervisor spawns.
    with db.get_connection() as connection:
        connection.execute("DELETE FROM worker_heartbeat")
    response = client.post("/admin/worker/start", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["started"] is True
    assert spawned == ["admin panel"]

    # Production spawning needs an explicit opt-in, parsed by the same config
    # helper as other boolean runtime switches.
    monkeypatch.setenv("DMEF_ENV", "production")
    monkeypatch.setenv("DMEF_ALLOW_LOCAL_WORKER_SPAWN", "0")
    assert client.post("/admin/worker/start", headers=headers).status_code == 409
    assert spawned == ["admin panel"]
    monkeypatch.setenv("DMEF_ALLOW_LOCAL_WORKER_SPAWN", "1")
    assert client.post("/admin/worker/start", headers=headers).status_code == 200
    assert spawned == ["admin panel", "admin panel"]

    # Non-admin cannot start workers.
    from services.auth.service import create_user

    create_user(
        email="user@example.com",
        display_name="User",
        role="user",
        password="UserStr0ngPass!",
    )
    user_token = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "UserStr0ngPass!"},
    ).json()["token"]
    forbidden = client.post(
        "/admin/worker/start", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert forbidden.status_code == 403

    # No token at all.
    assert client.post("/admin/worker/start").status_code == 401


def test_worker_singleton_lock(tmp_path, monkeypatch) -> None:
    import services.worker as worker_module
    from services.worker import acquire_worker_lock, release_worker_lock

    monkeypatch.setenv("DMEF_WORKER_LOCK_FILE", str(tmp_path / "worker.lock"))

    first = acquire_worker_lock()
    assert first is not None
    try:
        # Same-process re-acquire through a second handle must fail while
        # the first is held (Windows semantics; POSIX may allow it, so only
        # assert the cross-process case below is strict).
        assert worker_module._lock_file is first
    finally:
        release_worker_lock()
    assert worker_module._lock_file is None
    # Re-acquirable after release.
    second = acquire_worker_lock()
    assert second is not None
    release_worker_lock()


def test_worker_singleton_lock_excludes_second_process(tmp_path, monkeypatch) -> None:
    import subprocess
    import sys
    import time

    from services.worker import acquire_worker_lock, release_worker_lock

    monkeypatch.setenv("DMEF_WORKER_LOCK_FILE", str(tmp_path / "worker.lock"))

    holder = acquire_worker_lock()
    assert holder is not None
    try:
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, '.');"
                "from services.worker import acquire_worker_lock;"
                "handle = acquire_worker_lock();"
                "print('HELD' if handle is None else 'FREE')",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert "HELD" in (probe.stdout or ""), probe.stderr[-500:]
        # A crashed holder releases the OS lock: no stale-lock state.
        release_worker_lock()
        time.sleep(0.5)
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, '.');"
                "from services.worker import acquire_worker_lock;"
                "handle = acquire_worker_lock();"
                "print('HELD' if handle is None else 'FREE')",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert "FREE" in (probe.stdout or ""), probe.stderr[-500:]
    finally:
        release_worker_lock()
