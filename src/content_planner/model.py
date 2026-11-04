import json
import os
import urllib.error
import urllib.request

ACTIONS = {
    "search_assets": ("Search the synthetic asset catalog by tier.", "tier"),
    "estimate_plan": ("Quote the catalog asset with its matching script package.", "asset"),
    "generate_script": ("Generate an editable script for a feasible quote.", "quote_id"),
    "save_plan": ("Persist a previously generated plan for this quote.", "quote_id"),
    "stop": ("End without saving when the goal cannot be achieved.", None),
}


def definitions():
    result = []
    for name, (description, key) in ACTIONS.items():
        props = {"reason": {"type": "string", "description": "Brief operational justification."}}
        if key:
            props[key] = {"type": "string"}
        if key == "tier":
            props[key]["enum"] = ["standard", "economy"]
        result.append({"type": "function", "function": {
            "name": name, "description": description, "parameters": {
                "type": "object", "properties": props, "required": list(props),
                "additionalProperties": False}}})
    return result


def live(messages):
    base = os.getenv("LLM_BASE_URL")
    model = os.getenv("LLM_MODEL")
    if not base or not model:
        raise ValueError("Configure LLM_BASE_URL and LLM_MODEL for live mode.")
    headers = {"Content-Type": "application/json"}
    if key := os.getenv("LLM_API_KEY"):
        headers["Authorization"] = "Bearer " + key
    payload = {"model": model, "messages": messages, "tools": definitions(), "tool_choice": "required"}
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions",
                                 json.dumps(payload).encode(), headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            msg = json.load(response)["choices"][0]["message"]
        calls = msg.get("tool_calls", [])
        if len(calls) != 1:
            raise ValueError("Expected one tool call.")
        call = calls[0]
        if not isinstance(call["id"], str) or not call["id"]:
            raise ValueError("Invalid tool call ID.")
        args = json.loads(call["function"]["arguments"])
        return call["function"]["name"], args, call["id"]
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Model endpoint returned HTTP {exc.code}") from exc


def mock(messages):
    observations = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
    last = observations[-1] if observations else {}
    if not observations:
        name, args = "estimate_plan", {"asset": "studio", "reason": "评估用户给定的标准候选方案"}
    elif "error" in last:
        name, args = "stop", {"reason": last["error"]}
    elif "script" in last:
        name, args = "save_plan", {"quote_id": last["quote_id"], "reason": "脚本已生成"}
    elif last.get("feasible"):
        name, args = "generate_script", {"quote_id": last["quote_id"], "reason": "报价和耗时可行"}
    elif "quote_id" in last and last["asset"] == "studio":
        name, args = "search_assets", {"tier": "economy", "reason": "当前报价或耗时超限"}
    elif "description" in last:
        name, args = "estimate_plan", {"asset": last["asset"], "reason": "核算替代素材"}
    else:
        name, args = "stop", {"reason": "候选方案无法满足约束"}
    return name, args, f"mock-{len(observations)+1}"

