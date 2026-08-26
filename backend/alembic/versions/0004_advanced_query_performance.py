"""Index and statistics refresh for advanced analytics queries.

Revision ID: 0004_advanced_perf
"""

from __future__ import annotations

from alembic import op

revision = "0004_advanced_perf"
down_revision = "0003_experiments_advanced"
branch_labels = None
depends_on = None


DDL = r"""
CREATE INDEX IF NOT EXISTS idx_events_advanced_activity_time_user
  ON core.events (event_timestamp, user_id)
  WHERE event_name IN (
    'dashboard_viewed', 'landing_page_viewed', 'signup_completed',
    'onboarding_completed', 'checkout_started', 'payment_success',
    'report_created', 'report_exported', 'ai_assistant_used',
    'integration_connected', 'team_member_invited'
  );

ANALYZE core.users, core.sessions, core.events, core.subscriptions,
  core.transactions, core.experiments, core.experiment_assignments;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS core.idx_events_advanced_activity_time_user")
