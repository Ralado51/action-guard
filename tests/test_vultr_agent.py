"""Vultr agent runner against a simulated org and a scripted model. No network, no real writes."""
import json

import pytest

from connector.auth import get_token
from connector.config import SalesforceConfig
from connector.ids import to_sfid18
from connector.rest import SalesforceRest
from connector.transport import Response, TransportError
from planner.client import VultrChatClient
from planner.config import PlannerConfig
from vultr_agent.agent import FOLLOWUP_SUBJECT, parse_action, run_agent
from vultr_agent.tools import Guard, SalesforceTools, ToolRefused
from tests.test_salesforce_integration import ENV

CASE = to_sfid18("500SYN000000001")
OTHER = to_sfid18("500SYN000000002")


class Org:
    """Minimal Salesforce: token, queries by Id, PATCH Case, POST Task."""
    def __init__(self, subject="[SYNTHETIC] Demo", status="New"):
        self.cases = {CASE: {"Subject": subject, "Status": status, "Closure_Reason__c": None},
                      OTHER: {"Subject": "[SYNTHETIC] Other", "Status": "New", "Closure_Reason__c": None}}
        self.tasks, self.writes, self.patch_timeout = [], [], False

    def request(self, method, url, *, headers=None, body=None, timeout=30.0):
        if url.endswith("/services/oauth2/token"):
            return Response(200, {"access_token": "TOK", "instance_url": "https://x.my.salesforce.com"})
        if method == "GET":
            import urllib.parse, re
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]
            cid = re.search(r"'([^']+)'", q).group(1)
            if " FROM Case " in q:
                c = next((v for k, v in self.cases.items() if k[:15] == cid[:15]), None)
                rows = [{"Subject": c["Subject"], "Status": c["Status"], "IsClosed": c["Status"] == "Closed",
                         "Closure_Reason__c": c["Closure_Reason__c"]}] if c else []
            else:
                rows = [{"Subject": t["Subject"]} for t in self.tasks if t["WhatId"] == cid]
            return Response(200, {"done": True, "records": rows})
        self.writes.append((method, url))
        if method == "PATCH":
            if self.patch_timeout:
                raise TransportError("timeout", timed_out=True)
            cid = url.rsplit("/", 1)[1]
            self.cases[cid].update(json.loads(body))
            return Response(204, None)
        if method == "POST":
            f = json.loads(body); self.tasks.append(f)
            return Response(201, {"id": "00T" + str(len(self.tasks)).zfill(15)})
        raise AssertionError(method)


class Model:
    def __init__(self, replies): self.replies, self.calls = list(replies), 0
    def request(self, method, url, *, headers=None, body=None, timeout=30.0):
        self.calls += 1
        text = self.replies.pop(0)
        return Response(200, {"model": "m", "choices": [{"finish_reason": "stop", "message": {"content": text}}]})


def setup(org, replies, allowed=(CASE,), steps=6):
    cfg = SalesforceConfig.from_env(ENV)
    rest = SalesforceRest(cfg, get_token(cfg, org), org)
    tools = SalesforceTools(rest, Guard(frozenset(a[:15] for a in allowed), max_writes=3))
    client = VultrChatClient(PlannerConfig(api_key="k", model="m", max_calls=steps), Model(replies))
    return tools, client


def call(tool, **args): return json.dumps({"tool": tool, "args": args})
FINAL = json.dumps({"final": "Closed the Case and created the task."})


def test_happy_path_records_every_call_and_the_claim():
    org = Org()
    tools, client = setup(org, [call("read_case", case_id=CASE), call("close_case", case_id=CASE, closure_reason="Duplicate"),
                                call("create_followup_task", case_id=CASE, subject=FOLLOWUP_SUBJECT), FINAL])
    ev = run_agent(client, tools, CASE, "Duplicate", model="m")
    assert ev["outcome"] == "finished" and ev["final_message"].startswith("Closed")
    assert [s.get("request", {}).get("tool") for s in ev["steps"]] == ["read_case", "close_case", "create_followup_task", None]
    assert org.cases[CASE]["Status"] == "Closed" and len(org.tasks) == 1 and ev["writes"] == 2
    assert all("at" in s for s in ev["steps"])


def test_case_outside_allowlist_is_refused_and_nothing_is_sent():
    org = Org()
    tools, client = setup(org, [call("close_case", case_id=OTHER, closure_reason="Duplicate"), FINAL])
    ev = run_agent(client, tools, CASE, "Duplicate", model="m")
    assert "not in the list authorized" in ev["steps"][0]["result"]["refused"]
    assert org.writes == [] and org.cases[OTHER]["Status"] == "New"


def test_fifteen_char_id_of_authorized_case_is_accepted():
    org = Org()
    tools, client = setup(org, [call("read_case", case_id=CASE[:15]), FINAL])
    ev = run_agent(client, tools, CASE, "Duplicate", model="m")
    assert ev["steps"][0]["result"]["found"] is True


def test_unmarked_case_is_never_written():
    org = Org(subject="Real customer issue")
    tools, client = setup(org, [call("close_case", case_id=CASE, closure_reason="Duplicate"), FINAL])
    ev = run_agent(client, tools, CASE, "Duplicate", model="m")
    assert "not marked as synthetic" in ev["steps"][0]["result"]["refused"] and org.writes == []


def test_uncertain_write_stops_the_run_and_is_not_retried():
    org = Org(); org.patch_timeout = True
    tools, client = setup(org, [call("close_case", case_id=CASE, closure_reason="Duplicate"), FINAL])
    ev = run_agent(client, tools, CASE, "Duplicate", model="m")
    assert ev["outcome"] == "uncertain_write" and ev["final_message"] is None
    assert len([w for w in org.writes if w[0] == "PATCH"]) == 1 and client.transport.calls == 1


def test_write_cap_and_step_limit():
    org = Org()
    tools, client = setup(org, [call("create_followup_task", case_id=CASE, subject="a")] * 5, steps=5)
    ev = run_agent(client, tools, CASE, "Duplicate", model="m", max_steps=5)
    assert ev["outcome"] == "step_limit" and ev["writes"] == 3 and len(org.tasks) == 3
    assert any("Write limit" in str(s.get("result")) for s in ev["steps"])


@pytest.mark.parametrize("bad", ["not json at all", json.dumps({"tool": "drop_table", "args": {}}),
                                 json.dumps({"tool": "close_case", "args": {"case_id": CASE}})])
def test_invalid_actions_never_reach_salesforce(bad):
    org = Org()
    tools, client = setup(org, [bad, FINAL])
    ev = run_agent(client, tools, CASE, "Duplicate", model="m")
    assert org.writes == [] and ev["steps"][0]["error"] in ("invalid_action", "invalid_tool_call") and ev["outcome"] == "finished"


def test_reason_must_be_a_known_value():
    org = Org()
    tools, client = setup(org, [call("close_case", case_id=CASE, closure_reason="whatever"), FINAL])
    ev = run_agent(client, tools, CASE, "Duplicate", model="m")
    assert "closure_reason must be one of" in ev["steps"][0]["result"]["refused"] and org.writes == []


def test_parse_action_handles_fences_and_braces_in_strings():
    assert parse_action('```json\n{"final": "done {ok}"}\n```') == {"final": "done {ok}"}
    with pytest.raises(ValueError):
        parse_action("nothing")


def test_cli_refuses_without_confirm_write(tmp_path, monkeypatch, capsys):
    from vultr_agent.__main__ import main
    for k, v in ENV.items(): monkeypatch.setenv(k, v)
    monkeypatch.setenv("SF_CLIENT_ID", "id"); monkeypatch.setenv("SF_CLIENT_SECRET", "s")
    (tmp_path / "a.json").write_text(json.dumps({"case_ids": [CASE]}))
    assert main(["run", "--authorized", str(tmp_path / "a.json")], transport=Org()) == 1
    assert "--confirm-write" in capsys.readouterr().out
