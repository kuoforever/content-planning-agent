"""Capture every attempt in a separate directory, including failures."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from content_planner.runner import CATALOG, PROMPT
from content_planner.model import definitions

EX = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--mode", choices=["mock", "live"], default="mock")
parser.add_argument("--repeat", type=int, choices=range(1, 6), default=1)
args = parser.parse_args()
cases = ["normal", "overbudget"] if args.mode == "live" else ["normal", "overbudget", "missing", "failure", "impossible", "late"]
batch = EX / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
batch.mkdir(parents=True, exist_ok=False)
def git(*args):
    return subprocess.check_output(["git", *args], cwd=EX.parent, text=True).strip()
manifest = {"mode": args.mode, "model": os.getenv("LLM_MODEL") if args.mode == "live" else "deterministic-mock",
            "commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain")),
            "prompt": PROMPT, "tools": definitions(), "max_steps": 12, "max_output_tokens": 180,
            "source_sha256": {str(p.relative_to(EX.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted((EX.parent/"src").rglob("*.py"))}}
(batch/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf8")
summary = []
with tempfile.TemporaryDirectory() as temp:
    for repeat in range(args.repeat):
        for case in cases:
            source = EX / case
            folder = batch / f"{repeat+1}-{case}"
            folder.mkdir()
            (folder/"input.json").write_bytes((source/"input.json").read_bytes())
            catalog = source/"catalog.json" if case == "overbudget" else CATALOG
            (folder/"catalog.json").write_bytes(catalog.read_bytes())
            cmd = [sys.executable, "-m", "content_planner", "run", "--mode", args.mode,
                   "--input", str(folder/"input.json"), "--catalog", str(folder/"catalog.json"),
                   "--db", str(Path(temp)/f"{repeat}-{case}.db"), "--now", "2030-11-04T09:00:00+08:00"]
            if case == "failure":
                cmd += ["--fail-save"]
            p = subprocess.run(cmd, capture_output=True, encoding="utf8",
                               env=dict(os.environ, PYTHONIOENCODING="utf8"))
            (folder/"stdout.json").write_text(p.stdout, encoding="utf8")
            (folder/"stderr.txt").write_text(p.stderr, encoding="utf8")
            result = json.loads(p.stdout) if p.returncode in (0, 2) else {"status":"process_failed"}
            trace = result.get("trace", [])
            quotes = [s["result"].get("total_cost") for s in trace if s["action"] == "estimate_plan"]
            summary.append({"case":case, "repeat":repeat+1, "status":result["status"],
                            "exit_code":p.returncode, "quote_sequence":quotes,
                            "replanned":case == "overbudget" and quotes[:2] == [12,8] and result["status"] == "completed",
                            "model_requests":len(result.get("model_calls", []))})
            (batch/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf8")
            print(case, repeat+1, result["status"], quotes, flush=True)
            if args.mode == "live" and not trace:
                raise SystemExit("Stopped live batch after request failure; evidence saved to " + str(batch))
print(batch)
