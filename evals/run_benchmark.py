from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import yaml
from app.ai.planner import (
    AdHocQuestion,
    AmbiguousQuestion,
    QuestionPlanner,
    UnsafeQuestion,
)
from app.analytics.service import AnalyticsService
from app.analytics.sql_compiler import compile_metric
from app.analytics.time_ranges import resolve_period
from app.config import get_settings
from app.database.service import DatabaseService, DatabaseUnavailable
from app.models.contracts import AnalyticsRequest
from app.security.sql_validator import SQLValidator


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the deterministic ProductLens benchmark")
    parser.add_argument(
        "--with-database",
        action="store_true",
        help="Execute current-period governed metrics against the configured database",
    )
    args = parser.parse_args()
    benchmark = yaml.safe_load(Path(__file__).with_name("benchmark_questions.yml").read_text())
    planner = QuestionPlanner()
    results = []
    validator = SQLValidator()
    analytics = None
    if args.with_database:
        database = DatabaseService(get_settings())
        analytics = AnalyticsService(database, validator)
    for item in benchmark["questions"]:
        try:
            plan = planner.plan(item["question"])
            if isinstance(plan, AmbiguousQuestion):
                actual = {"intent": "ambiguous", "metric": None, "dimensions": []}
            elif isinstance(plan, AdHocQuestion):
                actual = {"intent": "ad_hoc", "metric": None, "dimensions": []}
            else:
                actual = {"intent": plan.intent.value, "metric": plan.metric, "dimensions": plan.dimensions}
        except UnsafeQuestion:
            actual = {"intent": "unsafe", "metric": None, "dimensions": []}
        planner_passed = all(actual[key] == item[key] for key in ["intent", "metric", "dimensions"])
        tables_passed = None
        chart_passed = None
        numeric_status = "not_run"
        if actual["metric"]:
            try:
                proposal = compile_metric(actual["metric"], resolve_period("last_30_days"))
                validation = validator.validate(proposal.query)
                tables_passed = validation.valid and set(item.get("tables", [])).issubset(set(validation.tables))
            except (ValueError, KeyError):
                tables_passed = False
        expected_chart = item.get("chart_type")
        if expected_chart:
            inferred_chart = {
                "funnel": "funnel",
                "retention": "heatmap",
                "cohort": "heatmap",
                "comparison": "line",
                "trend": "line",
                "ranking": "bar",
                "segmentation": "bar",
                "feature_adoption": "bar",
            }.get(actual["intent"], "bar")
            chart_passed = inferred_chart == expected_chart
        if analytics is not None and actual["metric"]:
            try:
                dimension = actual["dimensions"][0] if actual["dimensions"] else None
                payload = analytics.metric(
                    AnalyticsRequest(metric=actual["metric"], period="last_30_days", dimension=dimension)
                )
                # Governed metric responses use ``current`` while the enriched
                # feature-adoption contract uses ``rows``. Retention windows
                # may legitimately contain only nulls when every cohort is
                # immature, so that case is not a numerical failure.
                if isinstance(payload.get("current"), list):
                    candidate_rows = payload["current"]
                    values = [float(row.get("value")) for row in candidate_rows if row.get("value") is not None]
                elif isinstance(payload.get("rows"), list):
                    candidate_rows = payload["rows"]
                    values = [float(row.get("adoption_rate")) for row in candidate_rows if row.get("adoption_rate") is not None]
                else:
                    values = []
                numeric_status = (
                    "passed"
                    if values and all(math.isfinite(value) for value in values)
                    else "not_applicable"
                    if not values
                    else "failed"
                )
            except (DatabaseUnavailable, ValueError, KeyError):
                numeric_status = "failed"
        elif actual["metric"]:
            numeric_status = "not_run_offline"
        else:
            numeric_status = "not_applicable"
        results.append(
            {
                "question": item["question"],
                "expected": item,
                "actual": actual,
                "checks": {"planner": planner_passed, "tables": tables_passed, "chart": chart_passed, "numeric": numeric_status},
                "passed": planner_passed and tables_passed is not False and chart_passed is not False and numeric_status != "failed",
            }
        )
    summary = {
        "total": len(results),
        "passed": sum(item["passed"] for item in results),
        "planner_passed": sum(item["checks"]["planner"] for item in results),
        "tables_checked": sum(item["checks"]["tables"] is not None for item in results),
        "tables_passed": sum(item["checks"]["tables"] is True for item in results),
        "chart_checked": sum(item["checks"]["chart"] is not None for item in results),
        "chart_passed": sum(item["checks"]["chart"] is True for item in results),
        "numeric_status": (
            "passed"
            if args.with_database and all(item["checks"]["numeric"] in {"passed", "not_applicable"} for item in results)
            else "failed"
            if args.with_database
            else "not_run_offline"
        ),
        "results": results,
    }
    output_name = "database-latest.json" if args.with_database else "offline-latest.json"
    output = Path(__file__).with_name("results") / output_name
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(summary, indent=2))
    print(json.dumps({"total": summary["total"], "passed": summary["passed"]}))
    if args.with_database and summary["numeric_status"] == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
