import pytest

from app.security.sql_validator import SQLSafetyPolicy, SQLValidator

validator = SQLValidator(SQLSafetyPolicy(max_rows=5000))


@pytest.mark.parametrize("query", [
    "DROP TABLE analytics.users",
    "DELETE FROM analytics.users",
    "UPDATE analytics.subscriptions SET status='active'",
    "INSERT INTO analytics.transactions (amount) VALUES (1)",
    "ALTER TABLE analytics.events ADD COLUMN secret text",
    "TRUNCATE analytics.events",
    "SELECT * FROM analytics.users; DROP TABLE analytics.events",
    "SELECT user_id FROM analytics.users /* ; DROP TABLE analytics.events */",
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT * FROM analytics.unknown_table",
    "SELECT amount FROM analytics.users",
    "SELECT * FROM analytics.users CROSS JOIN analytics.events",
    "SELECT pg_read_file('/etc/passwd') FROM analytics.users",
    "SELECT current_setting('search_path') FROM analytics.users",
    "SELECT pg_sleep(1) FROM analytics.users",
])
def test_unsafe_queries_are_rejected(query: str) -> None:
    result = validator.validate(query)
    assert not result.valid, (query, result)


def test_safe_query_is_qualified_and_limited() -> None:
    result = validator.validate("SELECT user_id, plan FROM analytics.users")
    assert result.valid, result.errors
    assert result.limited
    assert "LIMIT 5000" in (result.normalized_query or "")


def test_excessive_limit_is_rewritten() -> None:
    result = validator.validate("SELECT user_id FROM analytics.users LIMIT 999999")
    assert result.valid
    assert result.limited
    assert "LIMIT 5000" in (result.normalized_query or "")


def test_join_using_is_bounded() -> None:
    result = validator.validate("SELECT users.user_id FROM analytics.users JOIN analytics.events USING (user_id)")
    assert result.valid, result.errors
