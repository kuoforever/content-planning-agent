"""Bounded, repeatable stability evaluation. Never imports or reads credentials from files."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import uuid

from content_planner.model import definitions, live, mock
from content_planner.runner import CATALOG, PROMPT, run

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2030-11-04T09:00:00+08:00")
CASES = ("normal", "overbudget", "impossible", "late", "failure")


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def classify(case, result, saved_count):
    trace = result.get("trace", [])
    quotes = [s["result"] for s in trace if s["action"] == "estimate_plan" and "quote_id" in s["result"]]
    costs = [q["total_cost"] for q in quotes]
    calls = result.get("model_calls", [])
    if result.get("reason") == "batch request budget exhausted":
        return "budget_exhausted"
    if any(c.get("status") == "error" for c in calls):
        return "model_request_error"
    if case in ("normal", "overbudget"):
        expected = 9 if case == "normal" else 8
        plan = result.get("plan", {})
        if result["status"] == "completed":
            if saved_count != 1 or plan.get("total_cost") != expected or not plan.get("script"):
                return "invalid_saved_plan"
            if not quotes or quotes[0]["asset"] != "studio":
                return "skipped_candidate"
            if case == "overbudget":
                # Observe 12 first, then a later feasible 8; allow repeated searches/estimates.
                if costs[0] != 12 or not any(q["total_cost"] == 8 and q["feasible"] for q in quotes[1:]):
                    return "missing_replanning"
            return "pass"
        if trace and trace[-1]["action"] == "stop":
            return "premature_stop"
    elif case in ("impossible", "late"):
        if saved_count == 0 and result.get("stop_classification") == "all_candidates_infeasible":
            return "pass"
    elif case == "failure":
        failed_save = any(s["action"] == "save_plan" and "error" in s["result"] for s in trace)
        if failed_save and result["status"] == "incomplete" and result.get("scripts") and saved_count == 0:
            return "pass"
    return "task_failure"


def aggregate(rows, planned, mode):
    groups = {}
    for case in dict.fromkeys(r["case"] for r in rows):
        group = [r for r in rows if r["case"] == case]
        counts = dict(Counter(r["classification"] for r in group))
        valid = [r for r in group if r["classification"] not in ("model_request_error", "budget_exhausted")]
        passed = counts.get("pass", 0)
        groups[case] = {"attempts":len(group), "counts":counts, "passed":passed,
                        "success_rate_all_attempts":passed / len(group),
                        "success_rate_evaluable":passed / len(valid) if valid else None}
    return {"mode":mode, "planned":planned, "attempted":len(rows), "unrun":planned-len(rows),
            "requests":sum(r["requests"] for r in rows),
            "reported_tokens":sum(r["reported_tokens"] for r in rows),
            "calls_without_usage":sum(r["calls_without_usage"] for r in rows),
            "cases":groups,
            "acceptance":"pass" if len(rows)==planned and all(r["classification"]=="pass" for r in rows) else "not_passed",
            "interpretation":"Mock verifies the harness only. Live rates describe this small fixed sample; they do not prove general reliability."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["mock", "live"], required=True)
    parser.add_argument("--suite", choices=["core", "full"], default="core")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--max-requests", type=int, default=40)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20 or not 1 <= args.max_requests <= 240:
        parser.error("repeat must be 1..20; max-requests must be 1..240")
    if args.mode == "live" and not all(os.getenv(n) for n in ("LLM_BASE_URL", "LLM_MODEL")):
        parser.error("live mode requires LLM_BASE_URL and LLM_MODEL")
    cases = CASES[:2] if args.suite == "core" else CASES
    batch = ROOT/"examples"/"stability-runs"/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:8])
    batch.mkdir(parents=True, exist_ok=False)
    def git(*options):
        return subprocess.check_output(["git", *options], cwd=ROOT, text=True).strip()
    source_files = list((ROOT/"src").rglob("*.py")) + [Path(__file__)]
    write(batch/"manifest.json", {"mode":args.mode, "model":os.getenv("LLM_MODEL") if args.mode=="live" else "mock",
          "suite":args.suite, "repeat":args.repeat, "max_requests":args.max_requests,
          "max_steps_per_attempt":12, "max_completion_tokens":180, "clock":NOW.isoformat(),
          "commit":git("rev-parse","HEAD"), "dirty":bool(git("status","--porcelain")),
          "prompt":PROMPT, "tools":definitions(),
          "source_sha256":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}})
    rows = []
    request_count = 0
    aborted = False
    with tempfile.TemporaryDirectory() as temp:
        for repeat in range(args.repeat):
            for case in cases:
                if args.mode=="live" and request_count >= args.max_requests:
                    aborted = True
                    break
                folder = batch/f"{repeat+1}-{case}"
                folder.mkdir()
                task = json.loads((ROOT/"examples"/case/"input.json").read_text(encoding="utf8"))
                task["instructions"] = "请先评估标准候选方案（studio），再决定如何在预算和截止时间内完成活动。素材允许替换，预算和截止时间为硬性要求。"
                catalog = ROOT/"examples/overbudget/catalog.json" if case=="overbudget" else CATALOG
                write(folder/"input.json", task)
                (folder/"catalog.json").write_bytes(catalog.read_bytes())
                calls = []
                def decide(messages):
                    nonlocal request_count
                    if args.mode=="mock":
                        return mock(messages)
                    if request_count >= args.max_requests:
                        raise ValueError("batch request budget exhausted")
                    request_count += 1
                    return live(messages, telemetry=calls)
                db = Path(temp)/f"{repeat}-{case}.db"
                started = time.monotonic()
                result = run(task, args.mode, db, folder/"catalog.json", lambda:NOW, case=="failure", decide)
                result["model_calls"] = calls
                with closing(sqlite3.connect(db)) as conn:
                    saved = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
                classification = classify(case,result,saved)
                write(folder/"result.json",result)
                row = {"case":case, "repeat":repeat+1, "classification":classification,
                       "seconds":round(time.monotonic()-started,3), "saved_count":saved, "requests":len(calls),
                       "reported_tokens":sum((c.get("usage") or {}).get("total_tokens",0) for c in calls),
                       "calls_without_usage":sum(not c.get("usage") for c in calls)}
                rows.append(row)
                write(batch/"attempts.json",rows)
                write(batch/"summary.json",aggregate(rows,len(cases)*args.repeat,args.mode))
                print(case,repeat+1,classification,flush=True)
                if classification in ("model_request_error","budget_exhausted"):
                    aborted = True
                    break
            if aborted:
                break
    summary = aggregate(rows,len(cases)*args.repeat,args.mode)
    write(batch/"summary.json",summary)
    lines = ["# Stability evaluation", "", f"Mode: {args.mode}. Acceptance: {summary['acceptance']}.",
             f"Attempted {summary['attempted']}/{summary['planned']}; requests {summary['requests']}; reported tokens {summary['reported_tokens']}.",
             "", summary["interpretation"], ""]
    for case,stats in summary["cases"].items():
        lines.append(f"- {case}: {stats['passed']}/{stats['attempts']} passed; {stats['counts']}")
    (batch/"report.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    print(batch,flush=True)
    return 0 if summary["acceptance"]=="pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
