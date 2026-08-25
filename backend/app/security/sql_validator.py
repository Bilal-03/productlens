from __future__ import annotations

import re
from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.models.contracts import SQLValidation
from app.semantic.registry import registry


@dataclass(frozen=True)
class SQLSafetyPolicy:
    max_rows: int = 5000
    max_joins: int = 6
    max_nested_queries: int = 8
    allowed_schemas: frozenset[str] = frozenset({"analytics"})
    blocked_functions: frozenset[str] = frozenset(
        {
            "pg_read_file",
            "pg_read_binary_file",
            "pg_ls_dir",
            "dblink",
            "lo_import",
            "lo_export",
            "current_setting",
            "set_config",
            "pg_backend_pid",
            "pg_sleep",
            "version",
            "current_user",
            "session_user",
        }
    )


class SQLValidator:
    def __init__(self, policy: SQLSafetyPolicy | None = None) -> None:
        self.policy = policy or SQLSafetyPolicy()

    def validate(self, query: str) -> SQLValidation:
        errors: list[str] = []
        if not query.strip():
            return SQLValidation(valid=False, errors=["Query is empty"], failure_kind="syntax")
        if re.search(r"--|/\*|\*/", query):
            return SQLValidation(
                valid=False,
                errors=["SQL comments are not allowed"],
                failure_kind="unsafe",
            )
        try:
            statements = parse(query, read="postgres")
        except ParseError:
            return SQLValidation(valid=False, errors=["SQL could not be parsed"], failure_kind="syntax")
        if len(statements) != 1:
            return SQLValidation(
                valid=False,
                errors=["Exactly one SQL statement is required"],
                failure_kind="unsafe",
            )
        root = statements[0]
        if root is None:
            return SQLValidation(valid=False, errors=["SQL could not be parsed"], failure_kind="syntax")
        if not isinstance(root, exp.Query):
            errors.append("Only SELECT queries are allowed")

        blocked_nodes = (
            exp.Insert,
            exp.Update,
            exp.Delete,
            exp.Drop,
            exp.Create,
            exp.Alter,
            exp.Command,
            exp.Copy,
            exp.Lock,
            exp.Transaction,
            exp.Grant,
            exp.Revoke,
        )
        if any(root.find(node) is not None for node in blocked_nodes):
            errors.append("The query contains a prohibited operation")
        if root.find(exp.Into) is not None:
            errors.append("SELECT INTO is not allowed")
        joins = list(root.find_all(exp.Join))
        if len(joins) > self.policy.max_joins:
            errors.append(f"Queries may use at most {self.policy.max_joins} joins")
        if any(
            join.args.get("kind") == "CROSS"
            or (not join.args.get("on") and not join.args.get("using"))
            for join in joins
        ):
            errors.append("Cross or unbounded joins are not allowed")
        nested = list(root.find_all(exp.Subquery)) + list(root.find_all(exp.CTE))
        if len(nested) > self.policy.max_nested_queries:
            errors.append("Query nesting exceeds the safety budget")

        tables: list[str] = []
        cte_names = {cte.alias_or_name for cte in root.find_all(exp.CTE)}
        cte_aliases = {
            table.alias_or_name
            for table in root.find_all(exp.Table)
            if table.name in cte_names
        }
        table_columns: dict[str, set[str]] = {}
        known_table_names: set[str] = set()
        for table in root.find_all(exp.Table):
            name = table.name
            if name in cte_names:
                continue
            schema = table.db
            if schema and schema not in self.policy.allowed_schemas:
                errors.append(f"Schema '{schema}' is not allowed")
            if name not in registry.tables:
                errors.append(f"Table '{name}' is not allowlisted")
            else:
                visible_columns = set(registry.tables[name].columns) - set(registry.tables[name].pii_columns)
                table_columns[name] = visible_columns
                table_columns[table.alias_or_name] = visible_columns
                known_table_names.add(name)
            tables.append(name)

        for function in root.find_all(exp.Func):
            function_name = function.name if isinstance(function, exp.Anonymous) else function.sql_name()  # type: ignore[no-untyped-call]
            if function_name.lower() in self.policy.blocked_functions:
                errors.append("The query uses a prohibited function")

        columns = sorted({column.name for column in root.find_all(exp.Column)})
        output_aliases = {alias.alias for alias in root.find_all(exp.Alias) if alias.alias}
        allowed_columns = {
            column
            for table in registry.tables.values()
            for column in table.columns
            if column not in table.pii_columns
        }
        for column_name in columns:
            if column_name != "*" and column_name not in allowed_columns and column_name not in output_aliases:
                errors.append(f"Column '{column_name}' is not allowlisted")
        for column in root.find_all(exp.Column):
            name = column.name
            if name == "*" or name in output_aliases:
                continue
            qualifier = column.table
            if qualifier and (qualifier in cte_names or qualifier in cte_aliases):
                continue
            if qualifier and qualifier in table_columns and name not in table_columns[qualifier]:
                errors.append(f"Column '{name}' is not allowlisted for table '{qualifier}'")
            elif not qualifier and len(known_table_names) == 1:
                only_table = next(iter(known_table_names))
                if name not in table_columns[only_table]:
                    errors.append(f"Column '{name}' is not allowlisted for table '{only_table}'")

        limited = False
        if isinstance(root, exp.Query) and root.args.get("limit") is None:
            root = root.limit(self.policy.max_rows)
            limited = True
        elif limit := root.args.get("limit"):
            expression = limit.expression
            if isinstance(expression, exp.Literal) and expression.is_int:
                if int(expression.this) > self.policy.max_rows:
                    limit.set("expression", exp.Literal.number(self.policy.max_rows))
                    limited = True
            else:
                errors.append("LIMIT must be a fixed integer")

        deduped = list(dict.fromkeys(errors))
        failure_kind: str | None = None
        if deduped:
            # Only parser/schema failures are eligible for the single repair attempt.
            # Anything that crosses the safety boundary is deliberately classified as
            # unsafe, even when it also contains an unknown table or column.
            unsafe_prefixes = (
                "Only SELECT queries are allowed",
                "The query contains a prohibited operation",
                "SELECT INTO is not allowed",
                "Schema '",
                "Cross or unbounded joins are not allowed",
                "The query uses a prohibited function",
                "Exactly one SQL statement is required",
                "SQL comments are not allowed",
            )
            complexity_prefixes = (
                "Queries may use at most",
                "Query nesting exceeds",
                "LIMIT must be a fixed integer",
            )
            schema_prefixes = ("Table '", "Column '")
            if any(error.startswith(unsafe_prefixes) for error in deduped):
                failure_kind = "unsafe"
            elif any(error.startswith(complexity_prefixes) for error in deduped):
                failure_kind = "complexity"
            elif any(error.startswith(schema_prefixes) for error in deduped):
                failure_kind = "schema"
            elif deduped == ["SQL could not be parsed"]:
                failure_kind = "syntax"
            else:
                failure_kind = "complexity"

        return SQLValidation(
            valid=not deduped,
            normalized_query=root.sql(dialect="postgres", pretty=True) if not deduped else None,
            errors=deduped,
            tables=sorted(set(tables)),
            columns=columns,
            limited=limited,
            failure_kind=failure_kind,
        )
