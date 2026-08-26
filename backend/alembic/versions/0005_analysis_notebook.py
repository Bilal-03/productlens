"""Session-scoped saved analysis notebook."""

from __future__ import annotations

from alembic import op

revision = "0005_analysis_notebook"
down_revision = "0004_advanced_perf"
branch_labels = None
depends_on = None


DDL = r"""
CREATE TABLE IF NOT EXISTS operational.saved_insights (
  insight_id UUID PRIMARY KEY,
  session_hash CHAR(64) NOT NULL,
  source_query_id UUID NOT NULL,
  title VARCHAR(160) NOT NULL,
  response JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_hash, source_query_id)
);

CREATE INDEX IF NOT EXISTS idx_saved_insights_session_time
  ON operational.saved_insights(session_hash, created_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON operational.saved_insights TO app_writer;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS operational.saved_insights")
