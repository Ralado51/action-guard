"""CLI for the acceptance process (local files only; nothing here touches Salesforce).

  python -m acceptance open --report audit_report.json --actor "Name"
  python -m acceptance list | show --id F-xxxx | assign --id F-xxxx --actor "Name" --assignee "Other"
  python -m acceptance fix --id F-xxxx --actor "Name" --note "what was corrected"
  python -m acceptance revalidate --id F-xxxx --actor "Name" --report new_report.json
  python -m acceptance close --id F-xxxx --actor "Name"  |  accept-risk --id ... --justification "..."
  python -m acceptance export --id F-xxxx --report r1.json --report r2.json --out dossier.json [--mask]
  python -m acceptance verify --bundle dossier.json
"""
from __future__ import annotations

import argparse
import json
import sys

from .dossier import build_bundle, verify_bundle
from .findings import FindingError, FindingStore


def _load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m acceptance")
    ap.add_argument("--dir", default="findings")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("open", "list", "show", "assign", "fix", "revalidate", "close", "accept-risk", "export", "verify", "publish"):
        p = sub.add_parser(name)
        p.add_argument("--id"); p.add_argument("--actor"); p.add_argument("--assignee"); p.add_argument("--note")
        p.add_argument("--justification"); p.add_argument("--report", action="append"); p.add_argument("--out")
        p.add_argument("--bundle", action="append"); p.add_argument("--calibration"); p.add_argument("--mask", action="store_true")
    a = ap.parse_args(argv)
    st = FindingStore(a.dir)
    try:
        if a.cmd == "publish":
            bundles = [_load(b) for b in a.bundle or []]
            for b in bundles:
                if not b["manifest"].get("masked") or verify_bundle(b):
                    raise ValueError("Only verified, masked bundles can be published.")
            from audit.mask import mask_report
            cal = mask_report(_load(a.calibration)) if a.calibration else None
            with open(a.out, "w", encoding="utf-8") as fh:
                json.dump({"calibration": cal, "bundles": bundles}, fh, ensure_ascii=False, separators=(",", ":"))
            print("Published:", a.out)
            return 0
        if a.cmd == "verify":
            problems = verify_bundle(_load(a.bundle[0]))
            print("OK: the bundle matches its manifest." if not problems else "PROBLEMS:\n- " + "\n- ".join(problems))
            return 0 if not problems else 1
        if a.cmd == "open":
            ids = st.open_from_report(_load(a.report[0]), a.actor or "")
            print("Opened:", ", ".join(ids) or "nothing (no divergences, or already open)")
        elif a.cmd == "list":
            for s in st.list():
                print(f"{s['finding_id']}  {s['state']:<20} {s['severity']:<12} {s['case_id']}  assignee={s['assignee']}")
        elif a.cmd == "show":
            print(json.dumps(st.state(a.id), indent=2, ensure_ascii=False))
        elif a.cmd == "assign":
            st.assign(a.id, a.actor or "", a.assignee or ""); print("Assigned.")
        elif a.cmd == "fix":
            st.record_fix(a.id, a.actor or "", a.note or ""); print("Correction recorded. Run a NEW audit, then revalidate.")
        elif a.cmd == "revalidate":
            ok = st.revalidate(a.id, a.actor or "", _load(a.report[0]))
            print("Revalidation PASSED. You may close the finding." if ok else "Revalidation FAILED: the Case still does not meet the plan.")
        elif a.cmd == "close":
            st.close(a.id, a.actor or ""); print("Closed (with a passing revalidation on record).")
        elif a.cmd == "accept-risk":
            st.accept_risk(a.id, a.actor or "", a.justification or ""); print("Risk accepted and recorded as UNRESOLVED, with your justification.")
        elif a.cmd == "export":
            bundle = build_bundle(st, a.id, [_load(p) for p in a.report or []], mask=a.mask)
            with open(a.out, "w", encoding="utf-8") as fh:
                json.dump(bundle, fh, ensure_ascii=False, separators=(",", ":"))
            print("Dossier written:", a.out, "· manifest", bundle["manifest"]["manifest_sha256"])
        return 0
    except (FindingError, ValueError, OSError, KeyError) as e:
        print("Refused:", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
