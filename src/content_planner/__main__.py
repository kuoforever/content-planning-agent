import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .runner import CATALOG, run


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--mode", choices=["live", "mock"], required=True)
    parser.add_argument("--db", default="planner.db")
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--now", help="Fixed timezone-aware clock for reproducible evaluations")
    parser.add_argument("--fail-save", action="store_true", help="Simulate a storage failure")
    args = parser.parse_args()
    try:
        task = json.loads(args.input.read_text(encoding="utf-8-sig"))
        if not isinstance(task, dict):
            raise ValueError("input must be an object")
        fixed = datetime.fromisoformat(args.now) if args.now else None
        if fixed and fixed.tzinfo is None:
            raise ValueError("--now requires timezone")
        result = run(task, args.mode, args.db, args.catalog, (lambda: fixed) if fixed else None, args.fail_save)
    except (ValueError, OSError) as exc:
        result = {"status": "incomplete", "mode": args.mode, "reason": str(exc), "trace": []}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

