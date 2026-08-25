"""Bootstrap ProductLens database roles on a new PostgreSQL/Supabase project.

This command is run once with the provider's administrator connection. It does
not print passwords and is intentionally separate from application startup,
migrations, and deterministic seeding.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import psycopg
from psycopg import sql
from psycopg.sql import Composable
from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class RoleSpec:
    name: str
    password_env: str
    noinherit: bool = False
    createrole: bool = False


ROLE_SPECS = (
    RoleSpec("migration_owner", "MIGRATION_OWNER_PASSWORD", noinherit=True, createrole=True),
    RoleSpec("app_writer", "APP_WRITER_PASSWORD"),
    RoleSpec("analytics_reader", "ANALYTICS_READER_PASSWORD"),
)


def psycopg_url(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def _required_password(name: str) -> str:
    value = os.getenv(name, "")
    if len(value) < 16:
        raise ValueError(f"{name} must be at least 16 characters")
    if "\n" in value or "\r" in value:
        raise ValueError(f"{name} must not contain a newline")
    return value


def _role_options(spec: RoleSpec) -> list[Composable]:
    options: list[Composable] = [sql.SQL("LOGIN")]
    options.append(sql.SQL("NOINHERIT") if spec.noinherit else sql.SQL("INHERIT"))
    if spec.createrole:
        options.append(sql.SQL("CREATEROLE"))
    return options


def _role_statement(action: str, spec: RoleSpec, password: str) -> sql.Composed:
    options = sql.SQL(" ").join(_role_options(spec))
    return sql.SQL("{} ROLE {} {} PASSWORD {}").format(
        sql.SQL(action),
        sql.Identifier(spec.name),
        options,
        sql.Literal(password),
    )


def bootstrap_roles(admin_url: str) -> dict[str, object]:
    passwords = {spec.name: _required_password(spec.password_env) for spec in ROLE_SPECS}
    with psycopg.connect(psycopg_url(admin_url)) as connection:
        with connection.cursor() as cursor:
            database_row = cursor.execute("SELECT current_database()").fetchone()
            if database_row is None:
                raise RuntimeError("Could not resolve the administration database")
            database = str(database_row[0])
            for spec in ROLE_SPECS:
                exists = cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (spec.name,)).fetchone()
                action = "ALTER" if exists else "CREATE"
                cursor.execute(_role_statement(action, spec, passwords[spec.name]))

            cursor.execute(
                sql.SQL("GRANT CREATE ON DATABASE {} TO {};").format(
                    sql.Identifier(database), sql.Identifier("migration_owner")
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {};").format(
                    sql.Identifier("migration_owner")
                )
            )
            cursor.execute(
                sql.SQL("GRANT analytics_reader TO migration_owner WITH ADMIN OPTION")
            )
            cursor.execute(sql.SQL("GRANT app_writer TO migration_owner WITH ADMIN OPTION"))
        connection.commit()

    return {"database": database, "roles": [spec.name for spec in ROLE_SPECS]}


def main() -> None:
    admin_url = os.getenv("DATABASE_SUPERUSER_URL", "")
    if not admin_url:
        raise SystemExit("DATABASE_SUPERUSER_URL is required for one-time role bootstrap")
    try:
        result = bootstrap_roles(admin_url)
    except (OSError, ValueError, psycopg.Error) as exc:
        raise SystemExit(f"Role bootstrap failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
