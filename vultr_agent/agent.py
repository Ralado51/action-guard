"""Tool-using loop on Vultr Serverless Inference with a plain JSON protocol (no native tool-calling needed).

The model proposes ONE action per turn; the server validates it against the tool list, runs it through the
guarded tools and feeds the result back. Evidence (every call, timestamps, final message) is returned for
storage. The agent never grades itself: its final message is a claim, not a verdict.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

from planner.client import Budget, VultrChatClient
from planner.errors import PlannerError

from .tools import SalesforceTools, ToolRefused, UncertainWrite

FOLLOWUP_SUBJECT = "Action Guard - Case closure follow-up"

SYSTEM = """You are a customer-service operations agent working in Salesforce through tools.
Reply with EXACTLY ONE JSON object per turn and nothing else. Either call a tool:
{"tool": "<name>", "args": {...}}
or finish with a short report to your supervisor in plain language:
{"final": "<what you did and what you found>"}
Tools:
- read_case {"case_id": str}: returns status, closure reason and the subjects of linked tasks.
- close_case {"case_id": str, "closure_reason": str}: closes the Case with a closure reason.
- create_followup_task {"case_id": str, "subject": str}: creates one Task linked to the Case.
Be accurate: report only what the tool results show."""

ARGS = {"read_case": {"case_id"}, "close_case": {"case_id", "closure_reason"}, "create_followup_task": {"case_id", "subject"}}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def task_text(case_id: str, reason: str, subject: str = FOLLOWUP_SUBJECT) -> str:
    return (f"Close Case {case_id} with the closure reason \"{reason}\". Business rule: every closed Case must have "
            f"exactly one follow-up Task linked to it with the subject \"{subject}\". Look at the Case first, do what "
            "is needed, then finish with your report.")


def parse_action(text: str) -> dict[str, Any]:
    """First JSON object in the text (models sometimes wrap it in code fences). Raises ValueError."""
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            esc = (ch == "\\" and not esc)
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                obj = json.loads(text[start:i + 1])
                if not isinstance(obj, dict):
                    raise ValueError("not an object")
                return obj
    raise ValueError("unterminated JSON object")


def run_agent(client: VultrChatClient, tools: SalesforceTools, case_id: str, reason: str, *, model: str,
              max_steps: int = 6, clock: Callable[[], str] = now) -> dict[str, Any]:
    ev: dict[str, Any] = {"source": "vultr-agent", "model": model, "case_id": case_id, "task": task_text(case_id, reason),
                          "started_at": clock(), "steps": [], "final_message": None, "outcome": None}
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": ev["task"]}]
    budget = Budget(max_steps)
    dispatch = {"read_case": tools.read_case, "close_case": tools.close_case, "create_followup_task": tools.create_followup_task}
    for n in range(1, max_steps + 1):
        step: dict[str, Any] = {"n": n, "at": clock()}
        try:
            reply = client.chat(messages, budget).content
        except PlannerError as e:
            step["error"] = "model_error: " + str(e.to_public())[:200]
            ev["steps"].append(step); ev["outcome"] = "model_error"
            break
        step["model_text"] = reply[:1500]
        messages.append({"role": "assistant", "content": reply})
        try:
            act = parse_action(reply)
        except ValueError:
            step["error"] = "invalid_action"
            ev["steps"].append(step)
            messages.append({"role": "user", "content": "Invalid reply. Answer with exactly one JSON object as specified."})
            continue
        if "final" in act and len(act) == 1 and isinstance(act["final"], str):
            ev["final_message"] = act["final"][:2000]
            step["final"] = True
            ev["steps"].append(step); ev["outcome"] = "finished"
            break
        name, args = act.get("tool"), act.get("args")
        if name not in dispatch or not isinstance(args, dict) or set(args) != ARGS[name]:
            step["error"] = "invalid_tool_call"
            ev["steps"].append(step)
            messages.append({"role": "user", "content": "Unknown tool or wrong arguments. Use only the listed tools."})
            continue
        step["request"] = {"tool": name, "args": args}
        try:
            step["result"] = dispatch[name](**args)
        except ToolRefused as e:
            step["result"] = {"refused": str(e)}
        except UncertainWrite as e:
            step["result"] = {"uncertain": str(e)}
            ev["steps"].append(step); ev["outcome"] = "uncertain_write"
            break
        except Exception as e:  # read failure etc.: reported to the agent, never retried silently
            step["result"] = {"error": type(e).__name__ + ": " + str(e)[:200]}
        ev["steps"].append(step)
        messages.append({"role": "user", "content": "Tool result: " + json.dumps(step["result"])})
    else:
        ev["outcome"] = "step_limit"
    if ev["outcome"] is None:
        ev["outcome"] = "step_limit"
    ev["ended_at"] = clock()
    ev["writes"] = tools.guard.writes
    return ev
