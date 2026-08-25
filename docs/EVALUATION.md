# Evaluation

Evaluation separates deterministic correctness from model variability.

- Unit fixtures validate metrics, periods, funnels, retention, and contribution arithmetic exactly.
- The safety corpus must reject every destructive, injected, multi-statement, system-table, and unbounded query.
- A curated benchmark stores expected intent, metric, dimensions, tables, and approximate answer for roughly 50 questions.
- Live provider evaluation is optional and emits timestamped results with the provider/model named.
- README metrics are published only after a real evaluation run.

The current deterministic planner benchmark is 50/50 (`PYTHONPATH=backend backend/.venv/bin/python evals/run_benchmark.py`). This score covers intent, governed metric, and dimension resolution only; it is not an LLM quality score.
