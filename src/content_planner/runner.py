import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .model import ACTIONS, live, mock

CATALOG = Path(__file__).with_name("data") / "catalog.json"
PROMPT = ("Plan an executable content campaign within budget and deadline. Start with the user's "
          "candidate. Use one provided tool at a time. Base costs and success claims on observations. "
          "Only save a feasible generated plan. Stop if the task cannot be fulfilled.")


def run(task, mode, db, catalog=CATALOG, clock=None, fail_save=False, decide=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    start = clock()
    out = {"request_id": task.get("request_id"), "mode": mode, "status": "incomplete",
           "steps": [], "quotes": {}, "scripts": {}, "trace": []}
    missing = [k for k in ("request_id", "theme", "budget", "deadline")
               if task.get(k) is None or task.get(k) == ""]
    if missing:
        return dict(out, status="needs_input", missing=missing)
    try:
        if not all(isinstance(task[k], str) and task[k].strip() for k in ("theme", "request_id")):
            raise ValueError("theme and request_id must be nonempty strings")
        if type(task["budget"]) is not int or task["budget"] < 0:
            raise ValueError("budget must be a nonnegative integer")
        deadline = datetime.fromisoformat(task["deadline"])
        if deadline.tzinfo is None:
            raise ValueError("deadline requires a timezone")
        entries = json.loads(Path(catalog).read_text(encoding="utf-8-sig"))
        signature = hashlib.sha256(json.dumps([task, mode, entries], sort_keys=True).encode()).hexdigest()
        with closing(sqlite3.connect(db, timeout=15)) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS plans (request_id TEXT PRIMARY KEY, signature TEXT, plan TEXT)")
            def existing():
                row = conn.execute("SELECT signature, plan FROM plans WHERE request_id=?",
                                   (task["request_id"],)).fetchone()
                if not row:
                    return None
                if row[0] != signature:
                    raise ValueError("request_id conflict: input, catalog or mode changed")
                return json.loads(row[1])

            if cached := existing():
                return dict(out, status="completed", plan=cached, reused=True)
            context = dict(task, candidate_asset="studio", available_tiers=list(entries), current_time=start.isoformat())
            messages = [{"role": "system", "content": PROMPT},
                        {"role": "user", "content": json.dumps(context, ensure_ascii=False)}]
            choose = decide or (live if mode == "live" else mock)
            assets = {v["asset"]: v for v in entries.values()}

            def timing(quote):
                finish = clock() + timedelta(minutes=quote["minutes"])
                return {"estimated_finish": finish.isoformat(),
                        "time_gap_seconds": max(0, (finish - deadline).total_seconds())}

            def execute(name, args):
                if name == "stop":
                    return {"stopped": args["reason"]}
                if name == "search_assets":
                    asset = entries[args["tier"]]
                    return {"asset": asset["asset"], "description": asset["description"]}
                if name == "estimate_plan":
                    asset = assets[args["asset"]]
                    items = [{"activity": activity, "cost": asset[prefix+"_cost"],
                              "minutes": asset[prefix+"_minutes"]}
                             for activity, prefix in [(asset["description"], "asset"), ("撰写并校对脚本", "script")]]
                    quote = {"quote_id": "q-"+args["asset"], "asset": args["asset"], "activities": items,
                             "total_cost": sum(i["cost"] for i in items), "minutes": sum(i["minutes"] for i in items)}
                    quote.update(timing(quote))
                    quote["budget_gap"] = max(0, quote["total_cost"] - task["budget"])
                    quote["feasible"] = not (quote["budget_gap"] or quote["time_gap_seconds"])
                    out["quotes"][quote["quote_id"]] = quote
                    return quote
                qid = args["quote_id"]
                quote = out["quotes"][qid]
                current = timing(quote)
                if quote["budget_gap"] or current["time_gap_seconds"]:
                    return {"error": "quote exceeds constraints", "budget_gap": quote["budget_gap"], **current}
                if name == "generate_script":
                    script = [{"shot": assets[quote["asset"]]["description"], "caption": task["theme"]},
                              {"shot": "主题说明卡", "caption": f"本期聚焦{task['theme']}，你最想了解哪一点？"}]
                    out["scripts"][qid] = script
                    return {"quote_id": qid, "script": script}
                if qid not in out["scripts"]:
                    return {"error": "generate the matching script first"}
                if fail_save:
                    return {"error": "injected save failure"}
                plan = {**quote, **current, "theme": task["theme"], "script": out["scripts"][qid],
                        "plan_id": str(uuid.uuid4())}
                with conn:
                    conn.execute("INSERT OR IGNORE INTO plans VALUES (?,?,?)",
                                 (task["request_id"], signature, json.dumps(plan)))
                    saved = existing()
                return {"plan": saved}

            for step in range(1, 13):
                name, args, call_id = choose(messages)
                try:
                    key = ACTIONS[name][1]
                    keys = {"reason", key} if key else {"reason"}
                    if not isinstance(args, dict) or set(args) != keys or not all(
                            isinstance(v, str) and v.strip() for v in args.values()):
                        raise ValueError("invalid tool arguments")
                    result = execute(name, args)
                except (KeyError, ValueError, sqlite3.Error) as exc:
                    result = {"error": str(exc)}
                out["trace"].append({"step": step, "action": name, "arguments": args, "result": result})
                out["steps"].append({"action": name, "status": "failed" if "error" in result else "success"})
                if "plan" in result:
                    return dict(out, status="completed", plan=result["plan"])
                if "stopped" in result:
                    return dict(out, reason=result["stopped"])
                messages.extend([{"role": "assistant", "content": None, "tool_calls": [{
                    "id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
                    {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False)}])
            return dict(out, reason="step limit reached (12)")
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError, IndexError, AttributeError) as exc:
        return dict(out, reason=str(exc))

