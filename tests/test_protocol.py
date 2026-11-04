"""Exercise the live HTTP adapter against a protocol stub, not a real LLM."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from content_planner.model import mock
from content_planner.runner import run


def test_http_roundtrip(monkeypatch):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            name, args, cid = mock(payload["messages"])
            message = {"tool_calls": [{"id": cid, "type": "function", "function": {
                "name": name, "arguments": json.dumps(args)}}]}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"choices":[{"message":message}]}).encode())

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
            monkeypatch.setenv("LLM_MODEL", "protocol-stub")
            monkeypatch.delenv("LLM_API_KEY", raising=False)
            task = {"request_id":"http", "theme":"demo", "budget":10, "deadline":"2099-01-01T00:00:00Z"}
            out = run(task, "live", ":memory:")
        finally:
            server.shutdown()
            worker.join()
    assert out["status"] == "completed"
    assert requests[0]["tools"] and len(requests) == 3
    observed = requests[1]["messages"][-1]
    assert observed["tool_call_id"] == "mock-1" and json.loads(observed["content"])["total_cost"] == 9

