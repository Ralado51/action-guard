"""Operator registry: admin-issued personal keys, server-owned approver name, no secrets in public lists."""
import pytest
from fastapi.testclient import TestClient

from web.app import main as m
from web.app.operators import OperatorRegistry

ADMIN = {"Authorization": "Bearer admin-token-for-tests-1234567890"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTION_GUARD_API_TOKEN", "admin-token-for-tests-1234567890")
    reg = OperatorRegistry(tmp_path / "ops")
    m.app.dependency_overrides[m.operator_registry] = lambda: reg
    yield TestClient(m.app), reg
    m.app.dependency_overrides.clear()


def test_admin_registers_operator_and_key_works_once_shown(env):
    c, reg = env
    r = c.post("/api/operators", json={"name": "Maria Silva", "role": "operator"}, headers=ADMIN)
    assert r.status_code == 201 and r.json()["key"].startswith("agk_")
    key = r.json()["key"]
    me = c.get("/api/operators/me", headers={"Authorization": "Bearer " + key}).json()
    assert me["name"] == "Maria Silva" and me["role"] == "operator"
    pub = c.get("/api/operators").json()
    assert [o["name"] for o in pub["operators"]] == ["Maria Silva"]
    assert key not in str(pub) and "key_hash" not in str(pub)
    assert key not in (reg.db.read_bytes().decode("latin-1"))        # only the hash is stored


def test_operator_cannot_register_others_and_bad_keys_fail(env):
    c, _ = env
    key = c.post("/api/operators", json={"name": "Joao", "role": "operator"}, headers=ADMIN).json()["key"]
    h = {"Authorization": "Bearer " + key}
    assert c.post("/api/operators", json={"name": "Eve"}, headers=h).status_code == 403
    assert c.get("/api/operators/me", headers={"Authorization": "Bearer agk_wrong"}).status_code == 401
    assert c.get("/api/operators/me").status_code == 401


def test_revoked_key_stops_working_and_names_are_unique(env):
    c, _ = env
    r = c.post("/api/operators", json={"name": "Ana", "role": "reviewer"}, headers=ADMIN).json()
    assert c.post("/api/operators", json={"name": "ana"}, headers=ADMIN).status_code == 409
    assert c.delete("/api/operators/" + r["operator"]["id"], headers=ADMIN).status_code == 200
    assert c.get("/api/operators/me", headers={"Authorization": "Bearer " + r["key"]}).status_code == 401
    assert c.get("/api/operators").json()["operators"] == []


def test_invalid_name_and_role_rejected(env):
    c, _ = env
    assert c.post("/api/operators", json={"name": "<b>x</b>"}, headers=ADMIN).status_code == 422
    assert c.post("/api/operators", json={"name": "Okay Name", "role": "root"}, headers=ADMIN).status_code == 422
