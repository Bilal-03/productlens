"""P0/P1 completion metadata, explicit analytics views, and measured indexes.

Revision ID: 0002_p0p1_completion
"""

from __future__ import annotations

from alembic import op

revision = "0002_p0p1_completion"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


DDL = r"""
-- Keep the public analytics boundary explicit and PII-free. The source tables
-- remain owned by migration_owner; runtime analytics_reader receives SELECT on
-- these five approved views only.
CREATE OR REPLACE VIEW analytics.users AS
  SELECT user_id, signup_at, country, region, acquisition_channel, campaign,
         plan, company_size, signup_source
  FROM core.users;
CREATE OR REPLACE VIEW analytics.sessions AS
  SELECT session_id, user_id, started_at, ended_at, device, browser,
         operating_system, channel, campaign, landing_page
  FROM core.sessions;
CREATE OR REPLACE VIEW analytics.events AS
  SELECT event_id, user_id, session_id, event_name, event_timestamp, page,
         feature, properties
  FROM core.events;
CREATE OR REPLACE VIEW analytics.subscriptions AS
  SELECT subscription_id, user_id, plan, status, started_at, trial_started_at,
         trial_ended_at, cancelled_at, mrr, billing_interval
  FROM core.subscriptions;
CREATE OR REPLACE VIEW analytics.transactions AS
  SELECT transaction_id, user_id, subscription_id, timestamp, amount, currency,
         status, payment_method, transaction_type, failure_reason
  FROM core.transactions;

REVOKE SELECT ON ALL TABLES IN SCHEMA analytics FROM analytics_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics REVOKE SELECT ON TABLES FROM analytics_reader;
GRANT USAGE ON SCHEMA analytics TO analytics_reader;
GRANT SELECT ON analytics.users, analytics.sessions, analytics.events,
  analytics.subscriptions, analytics.transactions TO analytics_reader;

-- app_writer is limited to operational metadata. It must not become a
-- second analytics execution identity merely because the initial migration
-- granted broad view access for local development.
REVOKE USAGE ON SCHEMA analytics FROM app_writer;
REVOKE SELECT ON ALL TABLES IN SCHEMA analytics FROM app_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics REVOKE SELECT ON TABLES FROM app_writer;

ALTER TABLE operational.query_audit ADD COLUMN IF NOT EXISTS provider TEXT;
ALTER TABLE operational.query_audit ADD COLUMN IF NOT EXISTS model TEXT;
ALTER TABLE operational.query_audit ADD COLUMN IF NOT EXISTS input_tokens INTEGER;
ALTER TABLE operational.query_audit ADD COLUMN IF NOT EXISTS output_tokens INTEGER;

CREATE INDEX IF NOT EXISTS idx_events_feature_time ON core.events(feature, event_timestamp)
  WHERE feature IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_lifecycle_user_time ON core.events(user_id, event_name, event_timestamp)
  WHERE event_name IN ('subscription_started', 'subscription_cancelled');
CREATE INDEX IF NOT EXISTS idx_transactions_type_status_time ON core.transactions(transaction_type, status, timestamp);
CREATE INDEX IF NOT EXISTS idx_transactions_failure_time ON core.transactions(failure_reason, timestamp)
  WHERE failure_reason IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_subscriptions_cancelled ON core.subscriptions(cancelled_at)
  WHERE cancelled_at IS NOT NULL;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_events_feature_time;
        DROP INDEX IF EXISTS idx_events_lifecycle_user_time;
        DROP INDEX IF EXISTS idx_transactions_type_status_time;
        DROP INDEX IF EXISTS idx_transactions_failure_time;
        DROP INDEX IF EXISTS idx_subscriptions_cancelled;
        ALTER TABLE operational.query_audit DROP COLUMN IF EXISTS provider;
        ALTER TABLE operational.query_audit DROP COLUMN IF EXISTS model;
        ALTER TABLE operational.query_audit DROP COLUMN IF EXISTS input_tokens;
        ALTER TABLE operational.query_audit DROP COLUMN IF EXISTS output_tokens;
        """
    )
