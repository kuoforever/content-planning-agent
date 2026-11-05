import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stability",ROOT/"examples/stability.py")
stability = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stability)


def test_pass_requires_observed_replan():
    result=json.loads((ROOT/"examples/overbudget/live-output.json").read_text(encoding="utf8"))
    result["trace"]=json.loads((ROOT/"examples/overbudget/live-trace.json").read_text(encoding="utf8"))["steps"]
    assert stability.classify("overbudget",result,1)=="pass"
    result["trace"]=[s for s in result["trace"] if s["result"].get("total_cost")!=12]
    assert stability.classify("overbudget",result,1)!="pass"


def test_transport_error_is_separate():
    result={"status":"incomplete","trace":[],"model_calls":[{"status":"error"}]}
    assert stability.classify("normal",result,0)=="model_request_error"
    row={"case":"normal","classification":"model_request_error","requests":1,"reported_tokens":0,"calls_without_usage":1}
    summary=stability.aggregate([row],6,"live")
    assert summary["unrun"]==5
    assert summary["cases"]["normal"]["success_rate_evaluable"] is None
    assert summary["acceptance"]=="not_passed"


@pytest.mark.parametrize("error", [False, True])
def test_batch_budget_and_failure_stop(tmp_path, monkeypatch, error):
    (tmp_path/"examples").mkdir()
    (tmp_path/"src").mkdir()
    for case in ("normal","overbudget"):
        shutil.copytree(ROOT/"examples"/case,tmp_path/"examples"/case)
    shutil.copy(ROOT/"examples/stability.py",tmp_path/"examples/stability.py")
    monkeypatch.setattr(stability,"ROOT",tmp_path)
    monkeypatch.setattr(stability,"__file__",str(tmp_path/"examples/stability.py"))
    monkeypatch.setattr(stability.subprocess,"check_output",lambda *a,**k:"test-revision")
    monkeypatch.setenv("LLM_BASE_URL","https://example.invalid")
    monkeypatch.setenv("LLM_MODEL","stub")
    calls=[]
    def fake_live(messages, telemetry):
        calls.append(1)
        telemetry.append({"status":"error" if error else "received"})
        if error:
            raise ValueError("connection failure")
        return "search_assets",{"tier":"standard","reason":"repeat"},"id"
    monkeypatch.setattr(stability,"live",fake_live)
    monkeypatch.setattr(sys,"argv",["stability","--mode","live","--max-requests","2"])
    assert stability.main()==2
    assert len(calls)==(1 if error else 2)
    batch=next((tmp_path/"examples/stability-runs").iterdir())
    summary=json.loads((batch/"summary.json").read_text())
    assert summary["attempted"]==1 and summary["unrun"]==5
    assert (batch/"1-normal/result.json").exists()
    assert (batch/"report.md").exists()
