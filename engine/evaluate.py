"""Evaluate monitored evidence. Missing observation is never a successful check.

New records are compared by ID, not by the total after execution. Changes only
cover monitored pre-existing records; additions are handled by record_created.
"""
from __future__ import annotations

import copy
from typing import Any

from contracts.semantics import validate_plan_semantics


def _index(snapshot, obj):
    if obj not in snapshot["records"] or any(
        e["object"] == obj for e in snapshot.get("collection_errors", [])
    ):
        return None
    rows = snapshot["records"][obj]
    if len({r["id"] for r in rows}) != len(rows):
        return None
    return {r["id"]: r["fields"] for r in rows}


def _read(snapshot, obj, rid):
    rows = _index(snapshot, obj)
    if rows is None:
        return "unknown", {}
    deleted = any(a["object"] == obj and a["id"] == rid
                  for a in snapshot.get("confirmed_absent", []))
    if rid in rows:
        return ("unknown", {}) if deleted else ("present", rows[rid])
    return ("deleted", {}) if deleted else ("unknown", {})


def _changes(plan, before, after, allowed):
    changes = []
    unknown = not (before["complete"] and after["complete"])
    for mon in plan["monitored"]["objects"]:
        obj = mon["object"]
        rows = _index(before, obj)
        if rows is None or _index(after, obj) is None:
            unknown = True
            continue
        for rid, fields in rows.items():
            state, later = _read(after, obj, rid)
            if state == "deleted":
                changes.append(dict(object=obj, record_id=rid, field="__record__",
                                    before="present", after="deleted"))
            elif state == "unknown":
                unknown = True
            else:
                for field in mon["fields"]:
                    if f"{obj}.{field}" in allowed:
                        continue
                    if field not in fields or field not in later:
                        unknown = True
                    elif fields[field] != later[field]:
                        changes.append(dict(object=obj, record_id=rid, field=field,
                                            before=fields[field], after=later[field]))
    return changes, unknown


def _created(check, before, after, rid):
    obj, link = check["object"], check["link_field"]
    old, new = _index(before, obj), _index(after, obj)
    if old is None or new is None:
        return "inconclusive", "Colecao nao observada integralmente.", [], {}
    matches, unknown, unmatched = [], [], []
    criteria = {link: rid, **check.get("match", {})}
    # The link must always target the primary record, even with a conflicting match.
    criteria[link] = rid
    for key in sorted(new.keys() - old.keys()):
        fields = new[key]
        if link not in fields:
            unknown.append(key)
        elif fields[link] == rid:
            if any(f not in fields for f in check.get("match", {})):
                unknown.append(key)
            elif all(fields.get(f) == v for f, v in check.get("match", {}).items()):
                matches.append(key)
            else:
                unmatched.append(key)   # nova e vinculada ao Case, mas nao e a Task esperada
    expected = check.get("expected_count", 1)
    status = ("failed" if len(matches) > expected else "inconclusive" if unknown
              else "passed" if len(matches) == expected else "failed")
    detail = {"matching_ids": matches, "unobserved_candidate_ids": unknown,
              "linked_unmatched_ids": unmatched, "expected_count": expected, "criteria": criteria}
    return status, f"{len(matches)} novos correspondentes; esperado {expected}; {len(unknown)} candidatos incertos.", matches + unknown, detail


def evaluate(plan: dict[str, Any], before: dict[str, Any], after: dict[str, Any]):
    """Return (CheckResult list, unexpected change list), without reading agent prose.

    Inputs follow the 1.0 contracts. Inconsistent plan semantics raise ValueError;
    incompatible snapshot identities make all checks inconclusive.
    """
    issues = validate_plan_semantics(plan)
    if issues:
        raise ValueError("Plano incoerente: " + "; ".join(issues))
    incompatible = (before["run_id"] != after["run_id"] or before["phase"] != "before"
                    or after["phase"] != "after" or before["primary_record"] != after["primary_record"])
    primary = before["primary_record"]
    obj, rid = primary["object"], primary["id"]
    allowed = next((set(c.get("allowed_changes", [])) for c in plan["checks"]
                    if c["kind"] == "no_unexpected_change"), set())
    changes, unobserved = _changes(plan, before, after, allowed) if not incompatible else ([], True)
    results = []
    for check in plan["checks"]:
        kind = check["kind"]
        evidence = {"record_ids": [rid], "fields": [check.get("field", "*")]}
        status, reason = "inconclusive", "Evidencia insuficiente para comparar."
        if incompatible:
            reason = "Identidades ou fases dos snapshots incompativeis."
        elif kind == "no_unexpected_change":
            status = "failed" if changes else "inconclusive" if unobserved else "passed"
            reason = f"{len(changes)} mudancas inesperadas comprovadas; evidencia incompleta={unobserved}."
            evidence["record_ids"] = sorted({c["record_id"] for c in changes})
            evidence["fields"] = sorted({f"{c['object']}.{c['field']}" for c in changes})
            evidence["after"] = copy.deepcopy(changes)
        elif kind == "record_created":
            status, reason, ids, detail = _created(check, before, after, rid)
            evidence = {"record_ids": ids, "fields": sorted({check["link_field"], *check.get("match", {})}),
                        "after": detail}
        elif kind in ("field_equals", "field_not_empty", "field_unchanged"):
            if check["object"] != obj:
                raise ValueError("Verificacao de campo deve mirar o registro principal.")
            field = check["field"]
            bs, bf = _read(before, obj, rid)
            state, af = _read(after, obj, rid)
            initial_known = bs == "present" and field in bf
            if initial_known:
                evidence["before"] = copy.deepcopy(bf[field])
            if state == "present" and field in af:
                evidence["after"] = copy.deepcopy(af[field])
            if kind == "field_unchanged" and not initial_known:
                pass
            elif state == "deleted":
                status, reason = "failed", "Exclusao do registro confirmada."
            elif state == "present" and field in af:
                value = af[field]
                ok = (value == check["expected"] if kind == "field_equals" else
                      value == bf[field] if kind == "field_unchanged" else value not in (None, ""))
                status = "passed" if ok else "failed"
                reason = f"{obj}.{field}: condicao {'atendida' if ok else 'nao atendida'} nos dados coletados."
        else:
            raise ValueError(f"Verificacao desconhecida: {kind}")
        results.append(dict(schema_version="1.0", run_id=before["run_id"], check_id=check["check_id"],
                            kind=kind, status=status, reason=reason, evidence=evidence))
    return results, copy.deepcopy(changes)
