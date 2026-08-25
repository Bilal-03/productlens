from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.ai.planner import AmbiguousQuestion, QuestionPlanner, UnsafeQuestion


def main() -> None:
    benchmark = yaml.safe_load(Path(__file__).with_name("benchmark_questions.yml").read_text())
    planner = QuestionPlanner()
    results = []
    for item in benchmark["questions"]:
        try:
            plan = planner.plan(item["question"])
            if isinstance(plan, AmbiguousQuestion):
                actual = {"intent": "ambiguous", "metric": None, "dimensions": []}
            else:
                actual = {"intent": plan.intent.value, "metric": plan.metric, "dimensions": plan.dimensions}
        except UnsafeQuestion:
            actual = {"intent": "unsafe", "metric": None, "dimensions": []}
        results.append({"question": item["question"], "expected": item, "actual": actual, "passed": all(actual[key] == item[key] for key in ["intent", "metric", "dimensions"])})
    summary = {"total": len(results), "passed": sum(item["passed"] for item in results), "results": results}
    output = Path(__file__).with_name("results") / "offline-latest.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(summary, indent=2))
    print(json.dumps({"total": summary["total"], "passed": summary["passed"]}))


if __name__ == "__main__":
    main()

