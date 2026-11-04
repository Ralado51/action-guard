import pytest
from fastapi.testclient import TestClient

from web.app.main import app

client = TestClient(app)
HASH = "sha256:" + "a" * 64


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "action-guard"}


@pytest.mark.parametrize("method,url,body", [
    ("post", "/api/plans", {"rule_text_pt": "Ao encerrar um Case..."}),
    ("get", "/api/plans/p1", None),
    ("put", "/api/plans/p1", {"plan": {}}),
    ("post", "/api/plans/p1/approve", {"approved_by": "airton", "approved_plan_hash": HASH}),
    ("post", "/api/runs", {"approved_plan_id": "p1"}),
    ("get", "/api/runs/r1", None),
    ("get", "/api/runs/r1/report", None),
])
def test_contract_routes_exist_but_are_not_implemented(method, url, body):
    r = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
    assert r.status_code == 501
    assert r.json() == {"detail": "not implemented"}


@pytest.mark.parametrize("url,body", [
    ("/api/plans", {"rule_text_pt": ""}),
    ("/api/plans", {"rule_text_pt": "x", "process": "other"}),
    ("/api/plans/p1/approve", {"approved_by": "airton", "approved_plan_hash": "abc"}),
    ("/api/runs", {}),
])
def test_invalid_bodies_are_rejected(url, body):
    assert client.post(url, json=body).status_code == 422
