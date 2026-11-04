"""Run the CLI in isolated databases and capture its actual output and trace."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

EX = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--mode", choices=["mock", "live"], default="mock")
mode = parser.parse_args().mode
cases = ["normal", "overbudget"] if mode == "live" else ["normal", "overbudget", "missing", "failure", "impossible", "late"]
with tempfile.TemporaryDirectory() as temp:
    for case in cases:
        folder = EX / case
        cmd = [sys.executable, "-m", "content_planner", "run", "--mode", mode, "--input",
               str(folder/"input.json"), "--db", str(Path(temp)/(case+".db")), "--now", "2030-11-04T09:00:00+08:00"]
        if case == "overbudget":
            cmd += ["--catalog", str(folder/"catalog.json")]
        if case == "failure":
            cmd += ["--fail-save"]
        p = subprocess.run(cmd, capture_output=True, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        if p.returncode not in (0, 2):
            raise RuntimeError(p.stderr)
        result = json.loads(p.stdout)
        trace = result.pop("trace")
        for label, data in [("output", result), ("trace", {"mode":mode, "steps":trace})]:
            (folder/f"{mode}-{label}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
        print(case, mode, result["status"], len(trace))

