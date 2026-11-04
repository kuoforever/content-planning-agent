import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from content_planner.runner import CATALOG, run

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples"
NOW = datetime.fromisoformat("2030-11-04T09:00:00+08:00")


def example(case):
    return json.loads((EX / case / "input.json").read_text(encoding="utf-8"))


def perform(db, case="normal", **kwargs):
    catalog = EX / "overbudget/catalog.json" if case == "overbudget" else CATALOG
    return run(example(case), "mock", db, catalog, lambda: NOW, **kwargs)


@pytest.mark.parametrize("case,cost", [("normal", 9), ("overbudget", 8)])
def test_cost_and_trace(tmp_path, case, cost):
    out = perform(tmp_path/"p.db", case)
    assert out["plan"]["total_cost"] == cost
    trace = out["trace"]
    assert trace[0]["result"]["total_cost"] == (9 if case == "normal" else 12)
    assert trace[1]["action"] == ("generate_script" if case == "normal" else "search_assets")


@pytest.mark.parametrize("field", ["budget", "deadline"])
def test_missing(field):
    task = example("normal")
    del task[field]
    result = run(task, "mock", ":memory:")
    assert result["status"] == "needs_input" and result["missing"] == [field]


@pytest.mark.parametrize("case,field,gap", [("impossible", "budget_gap", 2), ("late", "time_gap_seconds", 1800)])
def test_infeasible(case, field, gap):
    out = perform(":memory:", case)
    assert out["status"] == "incomplete"
    assert out["quotes"]["q-cards"][field] == gap
    assert not out["scripts"]


def test_save_failure(tmp_path):
    db = tmp_path/"state.db"
    out = perform(db, fail_save=True)
    assert out["status"] == "incomplete" and out["scripts"]["q-studio"]
    assert out["steps"][-2] == {"action": "save_plan", "status": "failed"}
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM plans").fetchone() == (0,)


def test_process_replay(tmp_path):
    db = tmp_path/"state.db"
    cmd = [sys.executable, "-m", "content_planner", "run", "--mode", "mock", "--input",
           str(EX/"normal/input.json"), "--db", str(db), "--now", NOW.isoformat()]
    first, repeat = [json.loads(subprocess.check_output(cmd)) for _ in range(2)]
    assert first["plan"] == repeat["plan"] and repeat["reused"]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM plans").fetchone() == (1,)
    out = run(dict(example("normal"), theme="changed"), "mock", db)
    assert "conflict" in out["reason"]


def test_limit_and_guard():
    def decide(msgs):
        if len(msgs) == 2:
            return "estimate_plan", {"asset":"studio","reason":"quote"}, "a"
        return "generate_script", {"quote_id":"q-studio","reason":"attempt"}, str(len(msgs))
    out = perform(":memory:", "impossible", decide=decide)
    assert len(out["trace"]) == 12 and "limit" in out["reason"] and not out["scripts"]
    assert out["trace"][-1]["result"]["budget_gap"] == 3


def test_save_requires_matching_script():
    from content_planner.model import mock
    def decide(msgs):
        if len(msgs) == 4:
            return "save_plan", {"quote_id":"q-studio","reason":"attempt"}, "x"
        return mock(msgs)
    out = perform(":memory:", decide=decide)
    assert "matching script" in out["reason"] and "plan" not in out


def test_live_no_fallback(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    out = run(example("normal"), "live", ":memory:")
    assert out["status"] == "incomplete" and not out["trace"]

