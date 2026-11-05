import json
import sqlite3
import urllib.error

import pytest

from content_planner import model
from content_planner.runner import CATALOG, run

TASK = {"request_id":"errors", "theme":"demo", "budget":10, "deadline":"2099-01-01T00:00:00Z"}


@pytest.mark.parametrize("field,value", [
    ("asset_cost",-100), ("script_minutes",-1), ("asset_cost",True),
    ("script_cost","5"), ("asset_minutes",None), ("asset",""), ("description",None)])
def test_catalog_rejected(tmp_path, field, value):
    data=json.loads(CATALOG.read_text(encoding="utf8"))
    data["standard"][field]=value
    path=tmp_path/"catalog.json"
    path.write_text(json.dumps(data))
    result=run(TASK,"mock",":memory:",catalog=path)
    assert result["status"]=="incomplete" and not result["trace"] and "catalog" in result["reason"]


def test_duplicate_assets(tmp_path):
    data=json.loads(CATALOG.read_text(encoding="utf8"))
    data["economy"]["asset"]=data["standard"]["asset"]
    path=tmp_path/"catalog.json"
    path.write_text(json.dumps(data))
    assert "unique" in run(TASK,"mock",":memory:",catalog=path)["reason"]


@pytest.mark.parametrize("failure", [TimeoutError(), ValueError("invalid JSON")])
def test_model_failure_preserves_outputs(monkeypatch, failure):
    monkeypatch.setenv("LLM_BASE_URL","https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL","stub")
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(model.urllib.request,"urlopen",fail)
    def decide(messages):
        if len(messages)<6:
            return model.mock(messages)
        return model.live(messages)
    result=run(TASK,"live",":memory:",decide=decide)
    assert result["status"]=="incomplete" and result["scripts"] and result["quotes"]


def test_invalid_arguments_observed():
    def decide(messages):
        if len(messages)==2:
            return "estimate_plan",{"asset":17,"reason":"bad"},"1"
        return model.mock(messages)
    result=run(TASK,"mock",":memory:",decide=decide)
    assert result["trace"][0]["result"]["error"]=="invalid tool arguments"
    assert result["status"]=="incomplete"


def test_real_sqlite_failure(tmp_path):
    db=tmp_path/"state.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE plans (request_id TEXT PRIMARY KEY, signature TEXT, plan TEXT)")
        conn.execute("CREATE TRIGGER reject_plan BEFORE INSERT ON plans BEGIN SELECT RAISE(FAIL, 'disk failure test'); END")
    result=run(TASK,"mock",db)
    assert result["status"]=="incomplete" and result["scripts"]
    assert "disk failure test" in result["reason"]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]==0


def test_unverified_stop():
    result=run(TASK,"mock",":memory:",decide=lambda _:("stop",{"reason":"no plan"},"1"))
    assert result["stop_classification"]=="model_stopped"
    assert not result["feasibility_verified"]


def test_verified_infeasibility():
    result=run(dict(TASK,budget=0),"mock",":memory:")
    assert result["stop_classification"]=="all_candidates_infeasible"
    assert result["feasibility_verified"]

@pytest.mark.parametrize("body", ["not json", '{"choices": []}'])
def test_invalid_response_recorded(monkeypatch, body):
    import io
    monkeypatch.setenv("LLM_BASE_URL","https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL","stub")
    monkeypatch.setattr(model.urllib.request,"urlopen",lambda *a, **k: io.BytesIO(body.encode()))
    result=run(TASK,"live",":memory:")
    assert result["status"]=="incomplete"
    assert result["model_calls"][0]["status"]=="error"


def test_usage_recorded(monkeypatch):
    import io
    monkeypatch.setenv("LLM_BASE_URL","https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL","stub")
    body={"id":"response-id","model":"stub-version","usage":{"total_tokens":15},
          "choices":[{"message":{"tool_calls":[{"id":"call-1","function":{
              "name":"stop","arguments":json.dumps({"reason":"stopping"})}}]}}]}
    monkeypatch.setattr(model.urllib.request,"urlopen",lambda *a, **k: io.BytesIO(json.dumps(body).encode()))
    result=run(TASK,"live",":memory:")
    assert result["model_calls"][0]["usage"]["total_tokens"]==15
    assert result["model_calls"][0]["model"]=="stub-version"
