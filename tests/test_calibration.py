import json

from calibration.__main__ import FOLLOWUP, SPECS, main, remediate, score, seed
from audit.run import run_audit
from connector.auth import get_token
from connector.config import SalesforceConfig
from connector.rest import SalesforceRest
from connector.transport import Response
from tests.test_audit import approved_plan
from tests.test_salesforce_integration import ENV


class Org:
    """Stateful mini Salesforce: create/update/query for Case and Task."""
    def __init__(self): self.cases, self.tasks, self.n, self.writes = {}, [], 0, []

    def request(self, method, url, *, headers=None, body=None, timeout=30.0):
        import re, urllib.parse
        if url.endswith("/services/oauth2/token"):
            return Response(200, {"access_token": "T", "instance_url": "https://x.my.salesforce.com"})
        if method == "GET":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]
            ids = re.findall(r"'([^']+)'", q)
            if " FROM Case " in q:
                rows = [{**c, "Id": i} for i, c in self.cases.items() if i[:15] in {x[:15] for x in ids}]
            else:
                rows = [t for t in self.tasks if t["WhatId"][:15] in {x[:15] for x in ids}]
            want = [f.strip() for f in re.match(r"SELECT (.+) FROM", q).group(1).split(",")]
            return Response(200, {"done": True, "records": [{k: r.get(k) for k in want} | ({"Id": r["Id"]} if "Id" in r else {}) for r in rows]})   # like the real API: unset fields come back as null
        self.writes.append(method)
        if method == "POST":
            f = json.loads(body); self.n += 1
            if url.endswith("/Case"):
                cid = "500SYN%09dAAA" % self.n; self.cases[cid] = {**f, "IsClosed": False}; return Response(201, {"id": cid})
            self.tasks.append(f); return Response(201, {"id": "00T%015d" % self.n})
        if method == "PATCH":
            cid = url.rsplit("/", 1)[1]; self.cases[cid].update(json.loads(body)); self.cases[cid]["IsClosed"] = self.cases[cid]["Status"] == "Closed"
            return Response(204, None)


def client(org):
    cfg = SalesforceConfig.from_env(ENV)
    return SalesforceRest(cfg, get_token(cfg, org), org)


def test_seed_creates_controls_and_faults_and_never_reseeds(tmp_path):
    org = Org(); truth = seed(client(org), tmp_path)
    assert len(truth["cases"]) == len(SPECS) == 7 and sum(t["injected"] for t in truth["cases"].values()) == 4
    assert all(c["Subject"].startswith("[SYNTHETIC]") for c in org.cases.values())
    import pytest
    with pytest.raises(ValueError, match="already exists"):
        seed(client(org), tmp_path)


def test_audit_detects_every_injected_fault_with_no_false_alarms(tmp_path):
    org = Org(); truth = seed(client(org), tmp_path)
    rep = run_audit(approved_plan(), client(org), case_ids=list(truth["cases"]), list_all=True)
    res = score(truth, rep)
    assert (res["detected"], res["injected"], res["false_alarms"], res["controls"]) == (4, 4, 0, 3)
    by = {x["label"]: x["failed_checks"] for x in res["cases"]}
    assert by["fault_no_reason"] == ["chk_reason_filled"] and by["fault_duplicate_task"] == ["chk_followup_task"]


def test_remediation_fixes_what_is_fixable_and_is_idempotent(tmp_path):
    org = Org(); truth = seed(client(org), tmp_path)
    rest = client(org)
    assert "closure reason set" in remediate(rest, truth, "fault_no_reason")
    assert "Task created" in remediate(rest, truth, "fault_wrong_subject_task")
    assert "already fixed" in remediate(rest, truth, "fault_no_reason")
    import pytest
    with pytest.raises(ValueError, match="not auto-fixable"):
        remediate(rest, truth, "fault_duplicate_task")
    with pytest.raises(ValueError, match="not auto-fixable"):
        remediate(rest, truth, "control_1")
    rep = run_audit(approved_plan(), rest, case_ids=list(truth["cases"]), list_all=True)
    st = {x["label"]: x["detected_status"] for x in score(truth, rep)["cases"]}
    assert st["fault_no_reason"] == "correct" and st["fault_wrong_subject_task"] == "correct" and st["fault_duplicate_task"] == "incorrect"


def test_cli_refuses_writes_without_confirmation(tmp_path, monkeypatch):
    for k, v in ENV.items(): monkeypatch.setenv(k, v)
    monkeypatch.setenv("SF_CLIENT_ID", "i"); monkeypatch.setenv("SF_CLIENT_SECRET", "s")
    org = Org()
    assert main(["seed", "--out", str(tmp_path / "x")], transport=org) == 1 and org.writes == []
