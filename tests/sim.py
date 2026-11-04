"""Salesforce simulado (somente respostas locais) e avaliador baseado no oraculo."""
from __future__ import annotations

import re
import urllib.parse
from typing import Any, Callable

from connector.transport import Response, TransportError
from tests import oracle

CASE = "500SYN000000001AAA"
OWNER = "005SYN000000001AAA"
OTHER = "005SYN000000002AAA"
SUBJECT = "Action Guard - Case closure follow-up"
REASON = "Resolved - Customer confirmed"
TOKEN = "SECRET-TOKEN-VALUE-123"
CLIENT_SECRET = "SECRET-CLIENT-VALUE-456"


class FakeSalesforce:
    """Implementa o Transport. `behavior(sim)` roda quando a mensagem do agente chega."""

    def __init__(self, behavior: Callable[["FakeSalesforce"], None] | None = None):
        self.cases = {CASE: {"Id": CASE, "Status": "New", "OwnerId": OWNER, "Closure_Reason__c": None,
                             "ClosedDate": None, "IsClosed": False, "Priority": "Medium", "Subject": "Caso sintetico"}}
        self.tasks: list[dict[str, Any]] = []
        self.deleted: set[str] = set()
        self.behavior = behavior or close_ok
        self.log: list[tuple[str, str]] = []
        self.action_calls = 0
        self.oauth_status = 200
        self.page_size: int | None = None
        self.omit_fields: set[str] = set()          # campos que a API "esquece" de devolver
        self.fail_task_query_after_action = False
        self.message_error: str | None = None       # "timeout" | "500" | "400"
        self.open_status = 200
        self.close_fails = False
        self._pages: dict[str, list] = {}
        self._cursor: dict[str, int] = {}
        self._n = 0

    # -- Transport --
    def request(self, method, url, *, headers=None, body=None, timeout=30.0):
        self.log.append((method, url))
        if url.endswith("/services/oauth2/token"):
            if self.oauth_status != 200:
                return Response(self.oauth_status, {"error": "invalid_client"})
            return Response(200, {"access_token": TOKEN, "instance_url": "https://example.my.salesforce.com"})
        assert headers and headers.get("Authorization") == f"Bearer {TOKEN}", "chamada sem token"
        if "/einstein/ai-agent/v1" in url:
            return self._agent(method, url, body)
        return self._rest(method, url)

    def _agent(self, method, url, body):
        if method == "POST" and url.endswith("/sessions"):
            if self.open_status != 200:
                return Response(self.open_status, {"message": "erro"})
            return Response(200, {"sessionId": "sess-001"})
        if method == "POST" and url.endswith("/messages"):
            self.action_calls += 1
            if self.message_error == "timeout":
                self.behavior(self)  # a acao pode ter rodado mesmo com timeout
                raise TransportError("timeout", timed_out=True)
            if self.message_error in ("500", "400"):
                return Response(int(self.message_error), {"message": "erro"})
            self.behavior(self)
            return Response(200, {"messages": [{"type": "Inform", "message": "Case fechado e tarefa criada."}], "result": []})
        if method == "DELETE":
            if self.close_fails:
                raise TransportError("timeout", timed_out=True)
            return Response(200, None)
        raise AssertionError(url)

    def _rest(self, method, url):
        parsed = urllib.parse.urlparse(url)
        if "/query/" in parsed.path:                       # proxima pagina
            key = parsed.path.rsplit("/", 1)[1]
            return self._page(key)
        q = urllib.parse.parse_qs(parsed.query)["q"][0]
        all_ = parsed.path.endswith("/queryAll")
        m = re.match(r"SELECT (.+) FROM (\w+) WHERE (\w+) (=|IN) (.+)$", q)
        assert m, q
        fields = [f.strip() for f in m.group(1).split(",")]
        obj, flt, rhs = m.group(2), m.group(3), m.group(5)
        ids = re.findall(r"'([^']+)'", rhs)
        if obj == "Task" and self.fail_task_query_after_action and self.action_calls:
            return Response(500, [{"errorCode": "UNKNOWN_EXCEPTION", "message": "falha"}])
        rows = self._select(obj, flt, ids, all_)
        out = []
        for r in rows:
            o = {"attributes": {"type": obj}}
            o.update({k: r[k] for k in ["Id"] + fields if k in r and k not in self.omit_fields or k == "Id"})
            if "IsDeleted" in fields:
                o["IsDeleted"] = r["Id"] in self.deleted
            out.append(o)
        if self.page_size and len(out) > self.page_size:
            return self._paginate(out)
        return Response(200, {"totalSize": len(out), "done": True, "records": out})

    def _select(self, obj, flt, ids, all_):
        if obj == "Case":
            rows = [c for c in self.cases.values() if c["Id"] in ids]
            if all_:
                rows += [{"Id": i} for i in self.deleted if i in ids and i not in self.cases]
            return rows
        return [t for t in self.tasks if t.get(flt) in ids]

    def _paginate(self, out):
        self._n += 1
        key = f"01g{self._n}"
        self._pages[key] = [out[i:i + self.page_size] for i in range(0, len(out), self.page_size)]
        self._cursor[key] = 0
        return self._page(key)

    def _page(self, key):
        pages, idx = self._pages[key], self._cursor[key]
        more = idx + 1 < len(pages)
        body = {"totalSize": sum(map(len, pages)), "done": not more, "records": pages[idx]}
        if more:
            self._cursor[key] = idx + 1
            body["nextRecordsUrl"] = f"/services/data/v68.0/query/{key}"
        return Response(200, body)

    # -- efeitos de negocio --
    def add_task(self, n=1, subject=SUBJECT):
        for _ in range(n):
            tid = f"00TSYN{len(self.tasks) + 1:09d}AAA"
            self.tasks.append({"Id": tid, "Subject": subject, "WhatId": CASE, "OwnerId": OWNER,
                               "Status": "Not Started", "CreatedDate": "2026-11-04T19:27:14.000+0000"})


def _close(sim, reason=REASON, owner=OWNER):
    c = sim.cases[CASE]
    c.update(Status="Closed", Closure_Reason__c=reason, IsClosed=True, ClosedDate="2026-11-04T19:27:14.000+0000", OwnerId=owner)


def close_ok(sim):
    _close(sim); sim.add_task(1)

def reason_not_persisted(sim):
    _close(sim, reason=None); sim.add_task(1)

def owner_changed(sim):
    _close(sim, owner=OTHER); sim.add_task(1)

def no_task(sim):
    _close(sim)

def many_tasks(sim):
    _close(sim); sim.add_task(2)

def nothing(sim):
    pass


def oracle_evaluator(plan, before, after):
    results = []
    for c in plan["checks"]:
        st = oracle.expected_status(c, plan, before, after)
        results.append({"schema_version": "1.0", "run_id": before["run_id"], "check_id": c["check_id"],
                        "kind": c["kind"], "status": st, "reason": f"{c['kind']} -> {st} (oraculo)",
                        "evidence": {"record_ids": [before["primary_record"]["id"]], "fields": [c.get("field", "*")]}})
    return results, oracle.unexpected_changes(plan, before, after)
