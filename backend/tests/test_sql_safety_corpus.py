from __future__ import annotations

import pytest

from app.security.sql_validator import SQLSafetyPolicy, SQLValidator

validator = SQLValidator(SQLSafetyPolicy(max_rows=5000))


BASE_CASES = [
    "DROP TABLE analytics.users",
    "DELETE FROM analytics.users WHERE user_id = 1",
    "UPDATE analytics.subscriptions SET status='active'",
    "INSERT INTO analytics.transactions (amount) VALUES (1)",
    "ALTER TABLE analytics.events ADD COLUMN secret text",
    "TRUNCATE analytics.events",
    "GRANT SELECT ON analytics.users TO public",
    "REVOKE SELECT ON analytics.users FROM analytics_reader",
    "COPY analytics.users TO STDOUT",
    "SELECT * FROM analytics.users; DROP TABLE analytics.events",
    "SELECT * FROM analytics.users; SELECT * FROM analytics.events",
    "SELECT user_id FROM analytics.users /* injected statement */",
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM analytics.unknown_table",
    "SELECT amount FROM analytics.users",
    "SELECT * FROM analytics.users CROSS JOIN analytics.events",
    "SELECT * FROM analytics.users JOIN analytics.events ON true",
    "SELECT pg_read_file('/etc/passwd') FROM analytics.users",
    "SELECT current_setting('search_path') FROM analytics.users",
    "SELECT set_config('search_path','public',false) FROM analytics.users",
    "SELECT pg_sleep(1) FROM analytics.users",
    "SELECT current_user FROM analytics.users",
    "SELECT user_id FROM analytics.users LIMIT requested_limit",
    "SELECT pg_advisory_lock(1)",
    "SELECT pg_terminate_backend(pid) FROM analytics.users",
    "SELECT generate_series(1,100000000)",
    "SELECT nextval('users_user_id_seq') FROM analytics.users",
    "SELECT random() FROM analytics.users",
    "SELECT dblink_connect('analytics')",
    "SELECT regexp_split_to_table('a,b', ',')",
    "SELECT unnest(ARRAY[1,2])",
]

# Exercise the same policy across several injection variants. Keeping the
# corpus generated makes it easy to extend without weakening the assertion.
SQL_SAFETY_CORPUS = [
    query
    for base in BASE_CASES
    for query in (
        base,
        f" {base} ",
        f"\n{base}\n",
        f"({base})",
        f"{base};",
    )
]


@pytest.mark.parametrize("query", SQL_SAFETY_CORPUS)
def test_safety_corpus_rejects_every_unsafe_shape(query: str) -> None:
    result = validator.validate(query)
    assert not result.valid, (query, result)


def test_safe_set_operations_and_with_queries_remain_allowed() -> None:
    for query in (
        "SELECT user_id FROM analytics.users UNION SELECT user_id FROM analytics.users",
        "WITH recent AS (SELECT user_id FROM analytics.users) SELECT user_id FROM recent",
    ):
        result = validator.validate(query)
        assert result.valid, (query, result.errors)
