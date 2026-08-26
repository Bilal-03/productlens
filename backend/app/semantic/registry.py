from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field


class MetricDefinition(BaseModel):
    name: str
    label: str
    description: str
    kind: Literal["count", "rate", "additive"]
    entity: str
    format: Literal["integer", "percentage", "currency"]
    compiler: str
    valid_dimensions: list[str]
    event_name: str | None = None
    numerator_event: str | None = None
    denominator_event: str | None = None
    retention_day: int | None = None
    retention_window: Literal["weekly", "monthly"] | None = None
    acquisition_stage: Literal["visitors", "signups", "activated_users", "paid_users", "channel_conversion"] | None = None


class DimensionDefinition(BaseModel):
    name: str
    label: str
    column: str
    table: str
    sample_values: list[str] = Field(default_factory=list)
    expression: str | None = None
    valid_metrics: list[str] = Field(default_factory=list)


class ColumnDefinition(BaseModel):
    name: str
    data_type: str
    description: str
    sample_values: list[str | int | float] = Field(default_factory=list)
    pii: bool = False


class TableDefinition(BaseModel):
    name: str
    description: str
    primary_key: str
    foreign_keys: dict[str, str] = Field(default_factory=dict)
    columns: list[str]
    pii_columns: list[str]
    allowed_dimensions: list[str] = Field(default_factory=list)
    column_metadata: dict[str, dict[str, Any]] = Field(default_factory=dict)


class SemanticRegistry:
    def __init__(self) -> None:
        self.base = Path(__file__).parent

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as handle:
            value = yaml.safe_load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"Invalid semantic catalog: {path}")
        return value

    @cached_property
    def metrics(self) -> dict[str, MetricDefinition]:
        raw = self._load(self.base / "metrics.yml")["metrics"]
        return {name: MetricDefinition(name=name, **value) for name, value in raw.items()}

    @cached_property
    def dimensions(self) -> dict[str, DimensionDefinition]:
        raw = self._load(self.base / "dimensions.yml")["dimensions"]
        return {name: DimensionDefinition(name=name, **value) for name, value in raw.items()}

    @cached_property
    def tables(self) -> dict[str, TableDefinition]:
        raw = self._load(self.base / "schema.yml")["tables"]
        return {name: TableDefinition(name=name, **value) for name, value in raw.items()}

    def metric(self, name: str) -> MetricDefinition:
        try:
            return self.metrics[name]
        except KeyError as exc:
            raise ValueError(f"Unsupported metric: {name}") from exc

    def validate_dimension(self, metric: str, dimension: str | None) -> None:
        if dimension is None:
            return
        definition = self.metric(metric)
        if dimension not in definition.valid_dimensions:
            raise ValueError(f"Dimension '{dimension}' is not valid for {metric}")

    def public_catalog(self) -> dict[str, Any]:
        tables: list[dict[str, Any]] = []
        for item in self.tables.values():
            column_metadata = [
                ColumnDefinition(
                    name=column,
                    data_type=str(item.column_metadata.get(column, {}).get("data_type", "unknown")),
                    description=str(item.column_metadata.get(column, {}).get("description", "")),
                    sample_values=list(item.column_metadata.get(column, {}).get("sample_values", [])),
                    pii=column in item.pii_columns,
                ).model_dump()
                for column in item.columns
            ]
            tables.append(
                {
                    **item.model_dump(exclude={"column_metadata"}),
                    "column_metadata": column_metadata,
                    "row_count": None,
                }
            )
        return {
            "metrics": [item.model_dump() for item in self.metrics.values()],
            "dimensions": [item.model_dump() for item in self.dimensions.values()],
            "tables": tables,
        }

    def public_catalog_with_counts(self, row_counts: dict[str, int] | None = None) -> dict[str, Any]:
        payload = self.public_catalog()
        counts = row_counts or {}
        for table in payload["tables"]:
            table["row_count"] = counts.get(table["name"])
        return payload

    def relevant_schema_context(self, question: str) -> dict[str, Any]:
        """Return a bounded, PII-free schema context for an ad-hoc SQL prompt.

        The model never receives the operational/core schemas or unclassified
        columns. Table selection is only a retrieval optimization; the SQL
        validator remains the authoritative allowlist at execution time.
        """

        normalized = " ".join(question.lower().split())
        table_hits: set[str] = set()
        dimension_hits: set[str] = set()
        for table_name, table in self.tables.items():
            haystack = " ".join([table_name, table.description, *table.columns]).lower()
            if table_name in normalized or any(column in normalized for column in table.columns) or any(
                token in normalized for token in haystack.split() if len(token) > 3
            ):
                table_hits.add(table_name)
        for dimension_name, dimension in self.dimensions.items():
            if dimension_name in normalized or dimension.label.lower() in normalized or any(
                sample.lower() in normalized for sample in dimension.sample_values
            ):
                dimension_hits.add(dimension_name)
                table_hits.add(dimension.table)

        # A question without explicit catalog terms still gets the complete,
        # compact approved catalog, never database metadata.
        selected_tables = set(self.tables) if not table_hits else set(table_hits)
        # Include one-hop related tables so joins can be generated without
        # asking the model to infer foreign-key names, while avoiding a broad
        # transitive dump of every view for a narrow question.
        if table_hits:
            for table_name, table in self.tables.items():
                references = {item.split(".", 1)[0] for item in table.foreign_keys.values()}
                referenced_by = {
                    candidate_name
                    for candidate_name, candidate in self.tables.items()
                    if table_name in {item.split(".", 1)[0] for item in candidate.foreign_keys.values()}
                }
                if table_name in table_hits or references & table_hits or referenced_by & table_hits:
                    selected_tables.add(table_name)
                    selected_tables.update(references)

        tables: list[dict[str, Any]] = []
        relationships: list[dict[str, str]] = []
        for table_name in sorted(selected_tables):
            table = self.tables[table_name]
            visible_columns = [column for column in table.columns if column not in table.pii_columns]
            tables.append(
                {
                    "name": f"analytics.{table.name}",
                    "description": table.description,
                    "primary_key": table.primary_key,
                    "columns": visible_columns,
                    "column_metadata": [
                        {
                            "name": column,
                            "data_type": str(table.column_metadata.get(column, {}).get("data_type", "unknown")),
                            "description": str(table.column_metadata.get(column, {}).get("description", "")),
                            "sample_values": list(table.column_metadata.get(column, {}).get("sample_values", [])),
                            "pii": column in table.pii_columns,
                        }
                        for column in visible_columns
                    ],
                    "allowed_dimensions": table.allowed_dimensions,
                }
            )
            for column, target in table.foreign_keys.items():
                target_table, target_column = target.split(".", 1)
                if target_table in selected_tables:
                    relationships.append(
                        {
                            "from": f"analytics.{table.name}.{column}",
                            "to": f"analytics.{target_table}.{target_column}",
                        }
                    )

        dimensions = [
            {
                "name": item.name,
                "label": item.label,
                "table": f"analytics.{item.table}",
                "column": item.column,
                "sample_values": item.sample_values,
                "expression": item.expression,
                "valid_metrics": item.valid_metrics,
            }
            for name, item in sorted(self.dimensions.items())
            if not dimension_hits or name in dimension_hits
        ]
        return {"tables": tables, "relationships": relationships, "dimensions": dimensions}


registry = SemanticRegistry()
