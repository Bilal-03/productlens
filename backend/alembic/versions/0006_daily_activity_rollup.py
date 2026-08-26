"""Materialize governed daily activity for bounded stickiness queries."""

from __future__ import annotations

from alembic import op

revision = "0006_daily_activity"
down_revision = "0005_analysis_notebook"
branch_labels = None
depends_on = None


DDL = r"""
CREATE TABLE IF NOT EXISTS core.daily_activity (
  activity_date DATE NOT NULL,
  user_id BIGINT NOT NULL REFERENCES core.users(user_id),
  PRIMARY KEY (activity_date, user_id)
);

-- The rollup is derived from the same governed activity vocabulary used by
-- the analytics compilers.  Convert explicitly in UTC so the result is
-- independent of the migration connection's session timezone.
INSERT INTO core.daily_activity (activity_date, user_id)
SELECT DISTINCT (event_timestamp AT TIME ZONE 'UTC')::date, user_id
FROM core.events
WHERE event_name IN (
  'dashboard_viewed', 'report_created', 'report_exported',
  'ai_assistant_used', 'integration_connected', 'team_member_invited'
)
ON CONFLICT (activity_date, user_id) DO NOTHING;

ANALYZE core.daily_activity;

CREATE OR REPLACE VIEW analytics.daily_activity AS
  SELECT activity_date, user_id
  FROM core.daily_activity;

REVOKE ALL ON core.daily_activity FROM PUBLIC;
REVOKE ALL ON analytics.daily_activity FROM PUBLIC;
GRANT ALL ON core.daily_activity TO migration_owner;
GRANT USAGE ON SCHEMA analytics TO analytics_reader;
GRANT SELECT ON analytics.daily_activity TO analytics_reader;
REVOKE USAGE ON SCHEMA analytics FROM app_writer;
REVOKE SELECT ON analytics.daily_activity FROM app_writer;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS analytics.daily_activity")
    op.execute("DROP TABLE IF EXISTS core.daily_activity")
