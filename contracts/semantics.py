"""Validacao semantica: regras entre campos que o JSON Schema nao expressa.

- validate_plan_semantics(plan): o plano e coerente consigo mesmo.
- validate_snapshot_pair(plan, before, after): o coletor cumpriu o contrato.

Ambas devolvem uma lista de problemas (vazia = ok). O motor deve chamar as duas e
registrar os problemas em report.limitations. Um par de snapshots com problemas
nunca pode produzir `passed` nas verificacoes que dependem da evidencia faltante.
"""
from __future__ import annotations

from typing import Any


def validate_plan_semantics(plan: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    monitored: dict[str, set[str]] = {}
    for m in plan["monitored"]["objects"]:
        if m["object"] in monitored:
            issues.append(f"objeto monitorado duplicado: {m['object']}")
        monitored[m["object"]] = set(m["fields"])

    ids = [c["check_id"] for c in plan["checks"]]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        issues.append(f"check_id duplicado: {dup}")

    if sum(c["kind"] == "no_unexpected_change" for c in plan["checks"]) > 1:
        issues.append("no maximo uma verificacao no_unexpected_change por plano")

    def need(obj: str, field: str | None, where: str) -> None:
        if obj not in monitored:
            issues.append(f"{where}: objeto {obj} nao esta em monitored")
        elif field is not None and field not in monitored[obj]:
            issues.append(f"{where}: campo {obj}.{field} nao esta em monitored")

    for c in plan["checks"]:
        where = f"check {c['check_id']}"
        if c["kind"] == "no_unexpected_change":
            for ref in c.get("allowed_changes", []):
                obj, field = ref.split(".", 1)
                need(obj, field, f"{where} allowed_changes")
            continue
        need(c["object"], c.get("field"), where)
        if c["kind"] == "record_created":
            need(c["object"], c["link_field"], f"{where} link_field")

    for pre in plan.get("preconditions", []):
        if "object" in pre:
            need(pre["object"], pre.get("field"), f"precondition {pre['id']}")
    return issues


def _tracked_ids(plan, before) -> dict[str, set[str]]:
    mon = {m["object"] for m in plan["monitored"]["objects"]}
    return {obj: {r["id"] for r in before["records"].get(obj, [])} for obj in mon}


def validate_snapshot_pair(plan: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if before["phase"] != "before" or after["phase"] != "after":
        issues.append("fases invertidas ou repetidas")
    if before["run_id"] != after["run_id"]:
        issues.append("run_id diferente entre os snapshots")
    if before["primary_record"] != after["primary_record"]:
        issues.append("primary_record diferente entre os snapshots")

    fields_of = {m["object"]: m["fields"] for m in plan["monitored"]["objects"]}
    for name, snap in (("before", before), ("after", after)):
        errored = {e["object"] for e in snap.get("collection_errors", [])}
        for obj, fields in fields_of.items():
            if obj in errored:
                continue
            if obj not in snap["records"]:
                issues.append(f"{name}: objeto monitorado {obj} ausente de records sem collection_errors")
                continue
            for rec in snap["records"][obj]:
                for f in fields:
                    if f not in rec["fields"]:
                        issues.append(f"{name}: campo monitorado {obj}.{f} nao coletado em {rec['id']}")

    tracked = _tracked_ids(plan, before)
    absent = {(a["object"], a["id"]) for a in after.get("confirmed_absent", [])}
    after_ids = {obj: {r["id"] for r in after["records"].get(obj, [])} for obj in tracked}
    errored_after = {e["object"] for e in after.get("collection_errors", [])}
    for obj, ids in tracked.items():
        if obj in errored_after:
            continue
        for rid in sorted(ids):
            if rid not in after_ids.get(obj, set()) and (obj, rid) not in absent:
                issues.append(f"after: {obj} {rid} sumiu sem estar em records nem em confirmed_absent")
    for obj, rid in sorted(absent):
        if rid not in tracked.get(obj, set()):
            issues.append(f"confirmed_absent: {obj} {rid} nao existia no snapshot anterior")
        if rid in after_ids.get(obj, set()):
            issues.append(f"confirmed_absent: {obj} {rid} tambem aparece em records")
    return issues
