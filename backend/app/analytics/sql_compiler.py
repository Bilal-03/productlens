from __future__ import annotations

from datetime import timedelta

from app.models.contracts import DateRange, Filter, SQLProposal
from app.semantic.registry import registry

DIMENSIONS = {
    "channel": "u.acquisition_channel",
    "campaign": "u.campaign",
    "country": "u.country",
    "device": "s.device",
    "browser": "s.browser",
    "checkout_context": "concat_ws(' / ', s.device, s.browser, s.channel)",
    "plan": "u.plan",
    "company_size": "u.company_size",
    "feature": "e.feature",
    "payment_method": "t.payment_method",
    "cohort": "date_trunc('week', u.signup_at)::date",
    "customer_type": "CASE WHEN t.transaction_type = 'charge' THEN 'New Customer' ELSE 'Returning Customer' END",
    "revenue_motion": "t.transaction_type",
    "failure_reason": "COALESCE(t.failure_reason, 'none')",
}

DIAGNOSTIC_DIMENSIONS = {
    **DIMENSIONS,
    "customer_type": "customer_type",
    "revenue_motion": "t.transaction_type",
    "failure_reason": "COALESCE(t.failure_reason, 'none')",
}

QUALIFYING_ACTIVITY = "('dashboard_viewed','report_created','report_exported','ai_assistant_used','integration_connected','team_member_invited')"
ACQUISITION_DIMENSIONS = frozenset(
    {"channel", "campaign", "country", "device", "browser", "plan", "company_size"}
)
PROACTIVE_METRICS = frozenset(
    {
        "revenue",
        "signups",
        "activation_rate",
        "checkout_conversion",
        "payment_success_rate",
        "payment_failures",
        "churn_rate",
        "dau",
    }
)
PROACTIVE_SERIES_MAX_DAYS = 118  # 28-day baseline plus the 90-day analysis horizon.
EXPERIMENT_METRICS = frozenset({"activation_rate", "checkout_conversion", "payment_success_rate"})


def period_sql(period: DateRange, column: str) -> str:
    return f"{column} >= '{period.start.isoformat()}'::date AND {column} < '{period.end.isoformat()}'::date"


def compile_experiments() -> SQLProposal:
    """Compile the bounded experiment catalog used by the analysis UI."""

    query = """
    SELECT x.experiment_key, x.name, x.hypothesis, x.primary_metric,
      x.control_variant, x.status, x.started_at, x.ended_at,
      ARRAY_AGG(DISTINCT a.variant ORDER BY a.variant)
        FILTER (WHERE a.variant IS NOT NULL) AS variants
    FROM analytics.experiments x
    LEFT JOIN analytics.experiment_assignments a ON a.experiment_id=x.experiment_id
    GROUP BY x.experiment_id, x.experiment_key, x.name, x.hypothesis,
      x.primary_metric, x.control_variant, x.status, x.started_at, x.ended_at
    ORDER BY x.started_at DESC, x.experiment_key
    """
    return SQLProposal(
        query=query.strip(),
        purpose="List governed experiments and their assigned variants",
        tables_used=["experiments", "experiment_assignments"],
        metrics_used=[],
        assumptions=["Only analytics views are queried", "Variant labels come from recorded assignments"],
    )


def compile_experiment_analysis(
    experiment_key: str,
    period: DateRange,
    metric: str,
) -> SQLProposal:
    """Compile one assignment-level conversion query for a governed experiment."""

    if metric not in EXPERIMENT_METRICS:
        raise ValueError(f"Metric '{metric}' is not supported for experiment analysis")
    if not experiment_key.strip() or len(experiment_key) > 120:
        raise ValueError("Experiment key is invalid")
    key = _literal(experiment_key.strip())
    cohort = f"""
      SELECT a.user_id, a.variant, a.assigned_at, u.signup_at
      FROM analytics.experiment_assignments a
      JOIN analytics.experiments x ON x.experiment_id=a.experiment_id
      JOIN analytics.users u ON u.user_id=a.user_id
      WHERE x.experiment_key={key}
        AND a.assigned_at < '{period.end.isoformat()}'::date
        AND a.assigned_at >= GREATEST('{period.start.isoformat()}'::date, x.started_at)
        AND (x.ended_at IS NULL OR a.assigned_at < x.ended_at)
    """
    if metric == "activation_rate":
        query = f"""
        WITH assignment_cohort AS ({cohort}), eligible AS (
          SELECT c.*
          FROM assignment_cohort c
          WHERE EXISTS (
            SELECT 1 FROM analytics.events signup
            WHERE signup.user_id=c.user_id AND signup.event_name='signup_completed'
              AND signup.event_timestamp >= c.signup_at
              AND signup.event_timestamp < '{period.end.isoformat()}'::date
          )
        ), outcomes AS (
          SELECT c.variant, c.user_id,
            EXISTS (
              SELECT 1 FROM analytics.events e
              WHERE e.user_id=c.user_id AND e.event_name='onboarding_completed'
                AND e.event_timestamp >= c.signup_at
                AND e.event_timestamp < c.signup_at + interval '7 days'
                AND e.event_timestamp < '{period.end.isoformat()}'::date
            ) AS converted
          FROM eligible c
        )
        SELECT variant,
          COUNT(*)::int AS sample_size,
          COUNT(*) FILTER (WHERE converted)::int AS conversions,
          COUNT(*) FILTER (WHERE converted)::float / NULLIF(COUNT(*), 0) AS conversion_rate
        FROM outcomes
        GROUP BY variant
        ORDER BY variant
        """
        definition = "Assigned users who complete signup and onboarding within seven days of signup"
    else:
        event_name = "checkout_started" if metric == "checkout_conversion" else "payment_submitted"
        query = f"""
        WITH assignment_cohort AS ({cohort}), session_outcomes AS (
          SELECT c.variant, s.session_id,
            BOOL_OR(e.event_name='{event_name}') AS eligible,
            BOOL_OR(e.event_name='payment_success') AS converted
          FROM assignment_cohort c
          JOIN analytics.sessions s ON s.user_id=c.user_id AND s.started_at >= c.assigned_at
          JOIN analytics.events e ON e.session_id=s.session_id
          WHERE {period_sql(period, 'e.event_timestamp')}
            AND e.event_name IN ('{event_name}', 'payment_success')
          GROUP BY c.variant, s.session_id
        ), outcomes AS (
          SELECT variant, eligible, converted
          FROM session_outcomes
          WHERE eligible
        )
        SELECT variant,
          COUNT(*)::int AS sample_size,
          COUNT(*) FILTER (WHERE converted)::int AS conversions,
          COUNT(*) FILTER (WHERE converted)::float / NULLIF(COUNT(*), 0) AS conversion_rate
        FROM outcomes
        GROUP BY variant
        ORDER BY variant
        """
        definition = (
            "Assigned sessions that reach payment success after checkout start"
            if metric == "checkout_conversion"
            else "Assigned sessions with a payment submission that reach payment success"
        )
    return SQLProposal(
        query=query.strip(),
        purpose=f"Compare experiment variants on {metric}",
        tables_used=["experiments", "experiment_assignments", "users", "events", "sessions"],
        metrics_used=[metric],
        assumptions=["Assignments are user-level and evaluated after assignment", definition, "The period end is exclusive"],
    )


ADVANCED_RISK_DIMENSIONS = {
    "plan": "u.plan",
    "company_size": "u.company_size",
    "channel": "u.acquisition_channel",
}


def compile_churn_risk(period: DateRange, dimension: str) -> SQLProposal:
    if dimension not in ADVANCED_RISK_DIMENSIONS:
        raise ValueError(f"Churn risk dimension '{dimension}' is not supported")
    expression = ADVANCED_RISK_DIMENSIONS[dimension]
    query = f"""
    WITH active_subscriptions AS (
      SELECT sub.subscription_id, sub.user_id,
        COALESCE(({expression})::text, 'Unknown') AS segment,
        sub.cancelled_at,
        EXISTS (
          SELECT 1 FROM analytics.events e
          WHERE e.user_id=sub.user_id
            AND e.event_name IN {QUALIFYING_ACTIVITY}
            AND e.event_timestamp >= '{(period.end - timedelta(days=30)).isoformat()}'::date
            AND e.event_timestamp < '{period.end.isoformat()}'::date
        ) AS recently_active
      FROM analytics.subscriptions sub
      JOIN analytics.users u ON u.user_id=sub.user_id
      WHERE sub.started_at < '{period.start.isoformat()}'::date
        AND (sub.cancelled_at IS NULL OR sub.cancelled_at >= '{period.start.isoformat()}'::date)
    )
    SELECT segment,
      COUNT(DISTINCT subscription_id)::int AS active_subscriptions,
      COUNT(DISTINCT subscription_id) FILTER (
        WHERE cancelled_at >= '{period.start.isoformat()}'::date
          AND cancelled_at < '{period.end.isoformat()}'::date
      )::int AS cancellations,
      COUNT(DISTINCT subscription_id) FILTER (
        WHERE cancelled_at >= '{period.start.isoformat()}'::date
          AND cancelled_at < '{period.end.isoformat()}'::date
      )::float / NULLIF(COUNT(DISTINCT subscription_id), 0) AS churn_rate,
      COUNT(DISTINCT user_id) FILTER (WHERE recently_active)::float /
        NULLIF(COUNT(DISTINCT user_id), 0) AS recent_activity_rate
    FROM active_subscriptions
    GROUP BY segment
    ORDER BY segment
    """
    return SQLProposal(
        query=query.strip(),
        purpose=f"Calculate observed churn and recent activity by {dimension}",
        tables_used=["subscriptions", "users", "events"],
        metrics_used=["churn_rate", "dau"],
        assumptions=[
            "Active subscriptions are measured at period start",
            "Recent activity means qualifying activity in the trailing 30 days",
            "Risk bands are descriptive signals, not predictive model output",
        ],
    )


def compile_journeys(period: DateRange) -> SQLProposal:
    journey_events = "('landing_page_viewed','signup_completed','onboarding_completed','checkout_started','payment_success','report_created','ai_assistant_used')"
    query = f"""
    WITH ordered_events AS (
      SELECT e.user_id, e.event_name,
        ROW_NUMBER() OVER (PARTITION BY e.user_id ORDER BY e.event_timestamp, e.event_id) AS step
      FROM analytics.events e
      WHERE {period_sql(period, 'e.event_timestamp')}
        AND e.event_name IN {journey_events}
    ), paths AS (
      SELECT user_id,
        CONCAT_WS(' → ',
          MAX(event_name) FILTER (WHERE step=1),
          MAX(event_name) FILTER (WHERE step=2),
          MAX(event_name) FILTER (WHERE step=3),
          MAX(event_name) FILTER (WHERE step=4),
          MAX(event_name) FILTER (WHERE step=5)
        ) AS path
      FROM ordered_events
      GROUP BY user_id
    ), non_empty AS (
      SELECT user_id, path FROM paths WHERE path <> ''
    )
    SELECT path, COUNT(*)::int AS users,
      COUNT(*)::float / NULLIF(SUM(COUNT(*)) OVER (), 0) AS share
    FROM non_empty
    GROUP BY path
    ORDER BY users DESC, path
    LIMIT 10
    """
    return SQLProposal(
        query=query.strip(),
        purpose="Identify the ten most common five-step product journeys",
        tables_used=["events"],
        metrics_used=["journey_users"],
        assumptions=["Only governed product lifecycle events are included", "Paths are limited to five steps"],
    )


def compile_stickiness(period: DateRange) -> SQLProposal:
    activity_start = period.start - timedelta(days=29)
    query = f"""
    WITH activity AS (
      SELECT DISTINCT date_trunc('day', e.event_timestamp)::date AS bucket, e.user_id
      FROM analytics.events e
      WHERE e.event_timestamp >= '{activity_start.isoformat()}'::date
        AND e.event_timestamp < '{period.end.isoformat()}'::date
        AND e.event_name IN {QUALIFYING_ACTIVITY}
    ), daily AS (
      SELECT bucket, COUNT(DISTINCT user_id)::int AS dau
      FROM activity
      WHERE bucket >= '{period.start.isoformat()}'::date
      GROUP BY bucket
    ), user_windows AS (
      SELECT d.bucket, a.user_id,
        COUNT(*) FILTER (WHERE a.bucket > d.bucket - 7) AS active_days_7,
        COUNT(*) AS active_days_30
      FROM daily d
      JOIN activity a
        ON a.bucket > d.bucket - 30
       AND a.bucket <= d.bucket
      GROUP BY d.bucket, a.user_id
    ), rolling AS (
      SELECT bucket,
        COUNT(*) FILTER (WHERE active_days_7 > 0)::int AS wau,
        COUNT(*)::int AS mau,
        COUNT(*) FILTER (WHERE active_days_30 >= 10)::int AS power_users
      FROM user_windows
      GROUP BY bucket
    )
    SELECT d.bucket::text AS period, d.dau, r.wau, r.mau,
      d.dau::float / NULLIF(r.wau, 0) AS dau_wau,
      d.dau::float / NULLIF(r.mau, 0) AS dau_mau,
      r.power_users
    FROM daily d
    JOIN rolling r ON r.bucket = d.bucket
    ORDER BY d.bucket
    """
    return SQLProposal(
        query=query.strip(),
        purpose=f"Calculate daily stickiness and power users for {period.label}",
        tables_used=["events"],
        metrics_used=["dau", "wau", "mau", "stickiness", "power_users"],
        assumptions=["Qualifying product activity defines active users", "Power users have activity on at least ten days in a trailing 30-day window"],
    )


def compile_revenue_cohorts(period: DateRange) -> SQLProposal:
    query = f"""
    WITH cohort_users AS (
      SELECT u.user_id, u.signup_at, date_trunc('month', u.signup_at)::date AS cohort
      FROM analytics.users u
      WHERE {period_sql(period, 'u.signup_at')}
    ), user_revenue AS (
      SELECT c.cohort, c.user_id,
        COALESCE(SUM(CASE WHEN t.status='success' THEN t.amount
                          WHEN t.status='refunded' THEN -t.amount ELSE 0 END), 0)::float AS revenue
      FROM cohort_users c
      LEFT JOIN analytics.transactions t ON t.user_id=c.user_id
        AND t.timestamp >= c.signup_at
        AND t.timestamp >= '{period.start.isoformat()}'::date
        AND t.timestamp < '{period.end.isoformat()}'::date
      GROUP BY c.cohort, c.user_id
    )
    SELECT cohort::text AS cohort,
      COUNT(*)::int AS cohort_size,
      (cohort + interval '30 days' <= '{period.end.isoformat()}'::date) AS mature,
      SUM(revenue)::float AS revenue,
      SUM(revenue)::float / NULLIF(COUNT(*), 0) AS revenue_per_user,
      COUNT(*) FILTER (WHERE revenue > 0)::int AS active_revenue_users
    FROM user_revenue
    GROUP BY cohort
    ORDER BY cohort
    """
    return SQLProposal(
        query=query.strip(),
        purpose=f"Calculate observed revenue per user by monthly signup cohort for {period.label}",
        tables_used=["users", "transactions"],
        metrics_used=["revenue", "ltv"],
        assumptions=[
            "LTV is observed revenue per signed-up user through the period end",
            "Refunds are subtracted from revenue",
            "Immature cohorts are labeled, never treated as zero",
        ],
    )


def segment_parts(dimension: str | None) -> tuple[str, str]:
    if not dimension:
        return "'All'::text AS segment", ""
    expression = DIMENSIONS[dimension]
    return f"COALESCE(({expression})::text, 'Unknown') AS segment", f"GROUP BY {expression}"


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _filter_sql(metric_name: str | None, filters: list[Filter] | None) -> str:
    if not filters:
        return ""
    clauses: list[str] = []
    for item in filters:
        if metric_name is not None:
            registry.validate_dimension(metric_name, item.dimension)
        elif item.dimension not in registry.dimensions:
            raise ValueError(f"Unknown filter dimension: {item.dimension}")
        expression = DIMENSIONS.get(item.dimension) or DIAGNOSTIC_DIMENSIONS.get(item.dimension)
        if expression is None:
            raise ValueError(f"Unknown filter dimension: {item.dimension}")
        if item.operator == "in":
            if not isinstance(item.value, list) or not item.value:
                raise ValueError("An 'in' filter requires at least one value")
            values = ", ".join(_literal(str(value)) for value in item.value)
            clauses.append(f"AND COALESCE(({expression})::text, 'Unknown') IN ({values})")
        else:
            if isinstance(item.value, list):
                raise ValueError("An 'eq' filter accepts one value")
            clauses.append(f"AND COALESCE(({expression})::text, 'Unknown') = {_literal(str(item.value))}")
    return "\n          " + "\n          ".join(clauses)


def _acquisition_segment(dimension: str) -> str:
    if dimension == "all":
        return "'All'::text"
    expressions = {
        "channel": "u.acquisition_channel",
        "campaign": "u.campaign",
        "country": "u.country",
        "device": "s.device",
        "browser": "s.browser",
        "plan": "u.plan",
        "company_size": "u.company_size",
    }
    try:
        return expressions[dimension]
    except KeyError as exc:
        raise ValueError(f"Dimension '{dimension}' is not supported for acquisition analytics") from exc


def compile_acquisition(
    period: DateRange,
    dimension: str = "channel",
    filters: list[Filter] | None = None,
    *,
    stage: str | None = None,
) -> SQLProposal:
    """Compile one acquisition query containing all funnel stages.

    Acquisition is cohort-safe: signup, activation, and paid users are anchored
    to users whose first completed signup falls in the requested period. Visitor
    sessions are independently counted from landing-page views in that period.
    """

    if dimension != "all" and dimension not in ACQUISITION_DIMENSIONS:
        raise ValueError(f"Dimension '{dimension}' is not supported for acquisition analytics")
    if filters and any(item.dimension not in ACQUISITION_DIMENSIONS for item in filters):
        raise ValueError("Acquisition filters must use an acquisition dimension")
    segment_expression = _acquisition_segment(dimension)
    filter_sql = _filter_sql(None, filters)
    end = period.end.isoformat()
    stage_value = {
        "visitors": ("visitors", "visitors", "visitors"),
        "signups": ("signups", "signups", "visitors"),
        "activated_users": ("activated_users", "activated_users", "signups"),
        "paid_users": ("paid_users", "paid_users", "signups"),
        "channel_conversion": ("channel_conversion", "signups", "visitors"),
    }
    selected = None
    if stage is not None:
        try:
            selected = stage_value[stage]
        except KeyError as exc:
            raise ValueError(f"Unsupported acquisition stage: {stage}") from exc

    if selected:
        numerator = selected[1]
        denominator = selected[2]
        value = f"{numerator}::float / NULLIF({denominator}, 0)" if stage == "channel_conversion" else f"{numerator}::float"
        select_list = f"segment, {numerator}::float AS numerator, {denominator}::float AS denominator, {value} AS value"
    else:
        select_list = """segment, visitors, signups, activated_users, paid_users,
          signups::float / NULLIF(visitors, 0) AS signup_conversion,
          activated_users::float / NULLIF(signups, 0) AS activation_conversion,
          paid_users::float / NULLIF(signups, 0) AS paid_conversion,
          signups::float / NULLIF(visitors, 0) AS channel_conversion"""

    query = f"""
    WITH visitor_segments AS (
      SELECT COALESCE(({segment_expression})::text, 'Unknown') AS segment,
        COUNT(DISTINCT s.session_id)::float AS visitors
      FROM analytics.events e
      JOIN analytics.sessions s ON s.session_id=e.session_id
      JOIN analytics.users u ON u.user_id=e.user_id
      WHERE {period_sql(period, 'e.event_timestamp')}
        AND e.event_name='landing_page_viewed'
        {filter_sql}
      GROUP BY {segment_expression}
    ), signup_users AS (
      SELECT e.user_id, MIN(e.event_timestamp) AS signup_at,
        u.acquisition_channel, u.campaign, u.country, u.plan, u.company_size,
        MIN(s.device) AS device, MIN(s.browser) AS browser
      FROM analytics.events e
      JOIN analytics.sessions s ON s.session_id=e.session_id
      JOIN analytics.users u ON u.user_id=e.user_id
      WHERE e.event_name='signup_completed' AND {period_sql(period, 'e.event_timestamp')}
        {filter_sql}
      GROUP BY e.user_id, u.acquisition_channel, u.campaign, u.country, u.plan, u.company_size
    ), signup_enriched AS (
      SELECT su.*,
        EXISTS (
          SELECT 1 FROM analytics.events a
          WHERE a.user_id=su.user_id AND a.event_name='onboarding_completed'
            AND a.event_timestamp >= su.signup_at
            AND a.event_timestamp < su.signup_at + interval '7 days'
        ) AS activated,
        (EXISTS (
          SELECT 1 FROM analytics.transactions t
          WHERE t.user_id=su.user_id AND t.status='success' AND t.timestamp >= su.signup_at AND t.timestamp < '{end}'::date
        ) OR EXISTS (
          SELECT 1 FROM analytics.subscriptions sub
          WHERE sub.user_id=su.user_id AND sub.started_at < '{end}'::date
            AND (sub.cancelled_at IS NULL OR sub.cancelled_at >= '{end}'::date)
        )) AS paid
      FROM signup_users su
    ), signup_segments AS (
      SELECT COALESCE(({segment_expression.replace('u.', 'su.').replace('s.', 'su.')})::text, 'Unknown') AS segment,
        COUNT(DISTINCT su.user_id)::float AS signups,
        COUNT(DISTINCT su.user_id) FILTER (WHERE su.activated)::float AS activated_users,
        COUNT(DISTINCT su.user_id) FILTER (WHERE su.paid)::float AS paid_users
      FROM signup_enriched su
      GROUP BY {segment_expression.replace('u.', 'su.').replace('s.', 'su.')}
    ), combined AS (
      SELECT COALESCE(v.segment, s.segment) AS segment,
        COALESCE(v.visitors, 0)::float AS visitors,
        COALESCE(s.signups, 0)::float AS signups,
        COALESCE(s.activated_users, 0)::float AS activated_users,
        COALESCE(s.paid_users, 0)::float AS paid_users
      FROM visitor_segments v
      FULL OUTER JOIN signup_segments s ON s.segment=v.segment
    )
    SELECT {select_list}
    FROM combined
    ORDER BY segment
    """
    return SQLProposal(
        query=query.strip(),
        purpose=f"Calculate acquisition stages by {dimension} for {period.label}",
        tables_used=["events", "sessions", "users", "transactions", "subscriptions"],
        metrics_used=[stage or "acquisition"],
        assumptions=["UTC date boundaries", "Signup, activation, and paid stages use first signup cohorts"],
    )


def compile_retention_window(
    metric_name: str,
    period: DateRange,
    dimension: str | None = None,
    filters: list[Filter] | None = None,
) -> SQLProposal:
    definition = registry.metric(metric_name)
    if definition.retention_window == "weekly":
        start_day, end_day = 7, 14
    elif definition.retention_window == "monthly":
        start_day, end_day = 30, 60
    else:
        raise ValueError(f"Metric '{metric_name}' is not a windowed retention metric")
    registry.validate_dimension(metric_name, dimension)
    segment, group = segment_parts(dimension)
    filters_sql = _filter_sql(metric_name, filters)
    query = f"""
    SELECT {segment},
      COUNT(DISTINCT CASE WHEN u.signup_at < '{period.end.isoformat()}'::date - interval '{end_day} days'
        AND e.user_id IS NOT NULL THEN u.user_id END)::float AS numerator,
      COUNT(DISTINCT CASE WHEN u.signup_at < '{period.end.isoformat()}'::date - interval '{end_day} days'
        THEN u.user_id END)::float AS denominator,
      COUNT(DISTINCT CASE WHEN u.signup_at < '{period.end.isoformat()}'::date - interval '{end_day} days'
        AND e.user_id IS NOT NULL THEN u.user_id END)::float /
        NULLIF(COUNT(DISTINCT CASE WHEN u.signup_at < '{period.end.isoformat()}'::date - interval '{end_day} days'
          THEN u.user_id END), 0) AS value
    FROM analytics.users u
    LEFT JOIN analytics.events e ON e.user_id=u.user_id
      AND e.event_timestamp >= u.signup_at + interval '{start_day} days'
      AND e.event_timestamp < u.signup_at + interval '{end_day} days'
      AND e.event_name IN {QUALIFYING_ACTIVITY}
    LEFT JOIN analytics.sessions s ON s.session_id=e.session_id
    WHERE {period_sql(period, 'u.signup_at')}
      {filters_sql}
    {group}
    """
    return SQLProposal(
        query=query.strip(),
        purpose=f"Calculate {definition.label} for {period.label}",
        tables_used=["users", "events", "sessions"],
        metrics_used=[metric_name],
        assumptions=[f"Qualifying activity during days {start_day}–{end_day - 1} after signup", "Immature cohorts are excluded"],
    )


def compile_feature_adoption(
    period: DateRange,
    dimension: str | None = "feature",
    filters: list[Filter] | None = None,
) -> SQLProposal:
    registry.validate_dimension("feature_adoption", dimension)
    dimension = dimension or "feature"
    if dimension == "feature":
        active_segment = "'All'::text"
        group_key = "fu.feature"
        non_feature_predicate = "fu2.feature=fu.feature"
        order_key = "fu.feature"
    else:
        if dimension not in DIMENSIONS:
            raise ValueError(f"Dimension '{dimension}' is not supported for feature adoption")
        active_segment = f"COALESCE(({DIMENSIONS[dimension]})::text, 'Unknown')"
        group_key = "fu.segment"
        non_feature_predicate = "fu2.segment=fu.segment"
        order_key = "fu.segment"
    filters_sql = _filter_sql("feature_adoption", filters)
    query = f"""
    WITH active AS (
      SELECT e.user_id, MIN(u.signup_at) AS signup_at, {active_segment} AS segment
      FROM analytics.events e
      JOIN analytics.users u ON u.user_id=e.user_id
      JOIN analytics.sessions s ON s.session_id=e.session_id
      WHERE {period_sql(period, 'e.event_timestamp')}
        AND e.event_name='dashboard_viewed'
        {filters_sql}
      GROUP BY e.user_id, {active_segment}
    ), feature_usage AS (
      SELECT e.feature, e.user_id, MIN(a.signup_at) AS signup_at, a.segment, COUNT(*)::float AS uses
      FROM analytics.events e
      JOIN active a ON a.user_id=e.user_id
      JOIN analytics.sessions s ON s.session_id=e.session_id
      WHERE {period_sql(period, 'e.event_timestamp')} AND e.feature IS NOT NULL
      GROUP BY e.feature, e.user_id, a.segment
    )
    SELECT {group_key} AS segment,
      COUNT(DISTINCT fu.user_id)::float AS numerator,
      (SELECT COUNT(*)::float FROM active a0 WHERE a0.segment = {"'All'::text" if dimension == "feature" else "fu.segment"}) AS denominator,
      COUNT(DISTINCT fu.user_id)::float / NULLIF((SELECT COUNT(*)::float FROM active a0 WHERE a0.segment = {"'All'::text" if dimension == "feature" else "fu.segment"}), 0) AS value,
      COUNT(DISTINCT fu.user_id)::float AS adopting_users,
      (SELECT COUNT(*)::float FROM active a0 WHERE a0.segment = {"'All'::text" if dimension == "feature" else "fu.segment"}) AS eligible_users,
      SUM(fu.uses)::float AS total_uses,
      SUM(fu.uses)::float / NULLIF(COUNT(DISTINCT fu.user_id), 0) AS uses_per_adopter,
      COUNT(DISTINCT CASE WHEN fu.signup_at < '{period.end.isoformat()}'::date - interval '30 days'
        AND EXISTS (
          SELECT 1 FROM analytics.events r
          WHERE r.user_id=fu.user_id AND r.event_name IN {QUALIFYING_ACTIVITY}
            AND r.event_timestamp >= fu.signup_at + interval '30 days'
            AND r.event_timestamp < fu.signup_at + interval '31 days'
        ) THEN fu.user_id END)::float AS feature_d30_numerator,
      COUNT(DISTINCT CASE WHEN fu.signup_at < '{period.end.isoformat()}'::date - interval '30 days' THEN fu.user_id END)::float AS feature_d30_denominator,
      (SELECT COUNT(DISTINCT CASE WHEN a2.signup_at < '{period.end.isoformat()}'::date - interval '30 days'
        AND EXISTS (
          SELECT 1 FROM analytics.events r2
          WHERE r2.user_id=a2.user_id AND r2.event_name IN {QUALIFYING_ACTIVITY}
            AND r2.event_timestamp >= a2.signup_at + interval '30 days'
            AND r2.event_timestamp < a2.signup_at + interval '31 days'
        ) THEN a2.user_id END)
       FROM active a2
       WHERE a2.segment = {"'All'::text" if dimension == "feature" else "fu.segment"}
         AND NOT EXISTS (SELECT 1 FROM feature_usage fu2 WHERE {non_feature_predicate} AND fu2.user_id=a2.user_id))::float AS non_feature_d30_numerator,
      (SELECT COUNT(DISTINCT CASE WHEN a2.signup_at < '{period.end.isoformat()}'::date - interval '30 days' THEN a2.user_id END)
       FROM active a2
       WHERE a2.segment = {"'All'::text" if dimension == "feature" else "fu.segment"}
         AND NOT EXISTS (SELECT 1 FROM feature_usage fu2 WHERE {non_feature_predicate} AND fu2.user_id=a2.user_id))::float AS non_feature_d30_denominator
    FROM feature_usage fu
    GROUP BY {group_key}
    ORDER BY {order_key}
    """
    return SQLProposal(
        query=query.strip(),
        purpose=f"Calculate feature adoption and D30 association for {period.label}",
        tables_used=["events", "sessions", "users"],
        metrics_used=["feature_adoption"],
        assumptions=["Active eligible users are users with dashboard activity", "D30 results are observational associations"],
    )


def compile_paid_users(
    period: DateRange,
    dimension: str | None = None,
    filters: list[Filter] | None = None,
) -> SQLProposal:
    """Compile the period-end paid-user definition.

    This is intentionally separate from the acquisition funnel's cohort-paid
    stage. The governed ``paid_users`` KPI counts every user with a successful
    paid transaction in the period or an active paid subscription at the
    period end, then applies only approved user/session dimensions.
    """

    registry.validate_dimension("paid_users", dimension)
    segment_columns = {
        None: "'All'::text",
        "channel": "p.acquisition_channel",
        "campaign": "p.campaign",
        "country": "p.country",
        "device": "p.device",
        "browser": "p.browser",
        "plan": "p.plan",
        "company_size": "p.company_size",
    }
    try:
        segment_expression = segment_columns[dimension]
    except KeyError as exc:
        raise ValueError(f"Dimension '{dimension}' is not supported for paid users") from exc
    filter_sql = _filter_sql("paid_users", filters).replace("u.", "p.").replace("s.", "p.")
    end = period.end.isoformat()
    group = "" if dimension is None else f"GROUP BY {segment_expression}"
    query = f"""
    WITH first_sessions AS (
      SELECT user_id, MIN(device) AS device, MIN(browser) AS browser
      FROM analytics.sessions
      GROUP BY user_id
    ), paid_user_rows AS (
      SELECT DISTINCT u.user_id, u.acquisition_channel, u.campaign, u.country,
        u.plan, u.company_size, fs.device, fs.browser
      FROM analytics.users u
      LEFT JOIN first_sessions fs ON fs.user_id=u.user_id
      WHERE (
        EXISTS (
          SELECT 1 FROM analytics.transactions t
          WHERE t.user_id=u.user_id AND t.status='success'
            AND {period_sql(period, 't.timestamp')}
        )
        OR EXISTS (
          SELECT 1 FROM analytics.subscriptions sub
          WHERE sub.user_id=u.user_id AND sub.started_at < '{end}'::date
            AND (sub.cancelled_at IS NULL OR sub.cancelled_at >= '{end}'::date)
        )
      )
    )
    SELECT COALESCE(({segment_expression})::text, 'Unknown') AS segment,
      COUNT(DISTINCT p.user_id)::float AS numerator,
      COUNT(DISTINCT p.user_id)::float AS denominator,
      COUNT(DISTINCT p.user_id)::float AS value
    FROM paid_user_rows p
    WHERE 1=1 {filter_sql}
    {group}
    ORDER BY segment
    """
    return SQLProposal(
        query=query.strip(),
        purpose=f"Calculate paid users for {period.label}" + (f" by {dimension}" if dimension else ""),
        tables_used=["users", "sessions", "transactions", "subscriptions"],
        metrics_used=["paid_users"],
        assumptions=["Successful paid transactions are counted in the period", "Active subscriptions are evaluated at the exclusive period end"],
    )


def compile_metric(
    metric_name: str,
    period: DateRange,
    dimension: str | None = None,
    filters: list[Filter] | None = None,
) -> SQLProposal:
    definition = registry.metric(metric_name)
    registry.validate_dimension(metric_name, dimension)
    segment, group = segment_parts(dimension)
    filters_sql = _filter_sql(metric_name, filters)
    compiler = definition.compiler

    if metric_name == "paid_users":
        return compile_paid_users(period, dimension, filters)
    if compiler == "acquisition":
        return compile_acquisition(period, dimension or "all", filters, stage=definition.acquisition_stage)
    if compiler == "retention_window":
        return compile_retention_window(metric_name, period, dimension, filters)
    if compiler == "feature_adoption":
        return compile_feature_adoption(period, dimension or "feature", filters)

    if compiler == "event_conversion":
        query = f"""
        SELECT {segment},
          COUNT(DISTINCT CASE WHEN e.event_name = '{definition.numerator_event}' THEN e.session_id END)::float AS numerator,
          COUNT(DISTINCT CASE WHEN e.event_name = '{definition.denominator_event}' THEN e.session_id END)::float AS denominator,
          COUNT(DISTINCT CASE WHEN e.event_name = '{definition.numerator_event}' THEN e.session_id END)::float /
            NULLIF(COUNT(DISTINCT CASE WHEN e.event_name = '{definition.denominator_event}' THEN e.session_id END), 0) AS value
        FROM analytics.events e
        JOIN analytics.sessions s ON s.session_id = e.session_id
        JOIN analytics.users u ON u.user_id = e.user_id
        WHERE {period_sql(period, 'e.event_timestamp')}
          AND e.event_name IN ('{definition.numerator_event}', '{definition.denominator_event}')
          {filters_sql}
        {group}
        """
    elif compiler == "activation":
        query = f"""
        WITH signups AS (
          SELECT DISTINCT e.user_id, e.event_timestamp AS signup_time, s.session_id
          FROM analytics.events e JOIN analytics.sessions s ON s.session_id=e.session_id
          WHERE e.event_name='signup_completed' AND {period_sql(period, 'e.event_timestamp')}
        ), activated AS (
          SELECT DISTINCT signup.user_id
          FROM signups signup JOIN analytics.events activation ON activation.user_id=signup.user_id
          WHERE activation.event_name='onboarding_completed'
            AND activation.event_timestamp BETWEEN signup.signup_time AND signup.signup_time + interval '7 days'
        )
        SELECT {segment}, COUNT(DISTINCT a.user_id)::float AS numerator,
          COUNT(DISTINCT signup.user_id)::float AS denominator,
          COUNT(DISTINCT a.user_id)::float / NULLIF(COUNT(DISTINCT signup.user_id),0) AS value
        FROM signups signup
        JOIN analytics.users u ON u.user_id=signup.user_id
        JOIN analytics.sessions s ON s.session_id=signup.session_id
        LEFT JOIN activated a ON a.user_id=signup.user_id
        WHERE {period_sql(period, 'signup.signup_time')}
          {filters_sql}
        {group}
        """
    elif compiler == "active_users":
        query = f"""
        SELECT {segment}, COUNT(DISTINCT e.user_id)::float AS numerator,
          COUNT(DISTINCT e.user_id)::float AS denominator, COUNT(DISTINCT e.user_id)::float AS value
        FROM analytics.events e JOIN analytics.sessions s ON s.session_id=e.session_id
        JOIN analytics.users u ON u.user_id=e.user_id
        WHERE {period_sql(period, 'e.event_timestamp')}
          AND e.event_name IN {QUALIFYING_ACTIVITY}
          {filters_sql}
        {group}
        """
    elif compiler == "stickiness":
        end = period.end.isoformat()
        query = f"""
        SELECT {segment},
          COUNT(DISTINCT CASE WHEN e.event_timestamp >= '{end}'::date - interval '1 day' THEN e.user_id END)::float AS numerator,
          COUNT(DISTINCT CASE WHEN e.event_timestamp >= '{end}'::date - interval '30 days' THEN e.user_id END)::float AS denominator,
          COUNT(DISTINCT CASE WHEN e.event_timestamp >= '{end}'::date - interval '1 day' THEN e.user_id END)::float /
          NULLIF(COUNT(DISTINCT CASE WHEN e.event_timestamp >= '{end}'::date - interval '30 days' THEN e.user_id END),0) AS value
        FROM analytics.events e JOIN analytics.sessions s ON s.session_id=e.session_id
        JOIN analytics.users u ON u.user_id=e.user_id
        WHERE e.event_timestamp >= '{end}'::date - interval '30 days' AND e.event_timestamp < '{end}'::date
          {filters_sql}
        {group}
        """
    elif compiler in {"mrr", "arr", "arpu"}:
        multiplier = "12 *" if compiler == "arr" else ""
        raw = f"{multiplier} SUM(sub.mrr)::float"
        value = raw if compiler != "arpu" else "SUM(sub.mrr)::float / NULLIF(COUNT(DISTINCT sub.user_id),0)"
        query = f"""
        SELECT {segment}, {raw} AS numerator, COUNT(DISTINCT sub.user_id)::float AS denominator,
          {value} AS value
        FROM analytics.subscriptions sub JOIN analytics.users u ON u.user_id=sub.user_id
        WHERE sub.started_at < '{period.end.isoformat()}'::date
          AND (sub.cancelled_at IS NULL OR sub.cancelled_at >= '{period.end.isoformat()}'::date)
          {filters_sql}
        {group}
        """
    elif compiler == "revenue":
        query = f"""
        SELECT {segment},
          SUM(CASE WHEN t.status='success' THEN t.amount WHEN t.status='refunded' THEN -t.amount ELSE 0 END)::float AS numerator,
          COUNT(*)::float AS denominator,
          SUM(CASE WHEN t.status='success' THEN t.amount WHEN t.status='refunded' THEN -t.amount ELSE 0 END)::float AS value
        FROM analytics.transactions t JOIN analytics.users u ON u.user_id=t.user_id
        WHERE {period_sql(period, 't.timestamp')}
          {filters_sql}
        {group}
        """
    elif compiler == "payment_success":
        query = f"""
        SELECT {segment},
          COUNT(DISTINCT CASE WHEN e.event_name='payment_success' THEN e.session_id END)::float AS numerator,
          COUNT(DISTINCT CASE WHEN e.event_name='payment_submitted' THEN e.session_id END)::float AS denominator,
          COUNT(DISTINCT CASE WHEN e.event_name='payment_success' THEN e.session_id END)::float /
            NULLIF(COUNT(DISTINCT CASE WHEN e.event_name='payment_submitted' THEN e.session_id END),0) AS value
        FROM analytics.events e JOIN analytics.sessions s ON s.session_id=e.session_id
        JOIN analytics.users u ON u.user_id=e.user_id
        WHERE {period_sql(period, 'e.event_timestamp')} AND e.event_name IN ('payment_submitted','payment_success')
          {filters_sql}
        {group}
        """
    elif metric_name == "payment_failures":
        segment_expression = "'All'::text" if dimension is None else DIMENSIONS[dimension]
        attempt_segment = (
            "'All'::text AS segment"
            if dimension is None
            else f"COALESCE(({segment_expression})::text, 'Unknown') AS segment"
        )
        query = f"""
        WITH attempts AS (
          SELECT e.session_id, {attempt_segment},
            BOOL_OR(e.event_name='payment_failed') AS failed
          FROM analytics.events e JOIN analytics.sessions s ON s.session_id=e.session_id
          JOIN analytics.users u ON u.user_id=e.user_id
          WHERE {period_sql(period, 'e.event_timestamp')}
            AND e.event_name IN ('checkout_started', 'payment_failed')
            {filters_sql}
          GROUP BY e.session_id, {segment_expression}
        )
        SELECT segment,
          COUNT(*) FILTER (WHERE failed)::float AS numerator,
          COUNT(*)::float AS denominator,
          COUNT(*) FILTER (WHERE failed)::float AS value
        FROM attempts
        GROUP BY segment
        """
    elif compiler == "event_count":
        event_name = definition.event_name
        if not event_name:
            raise ValueError(f"Metric '{metric_name}' does not define an event name")
        query = f"""
        SELECT {segment},
          COUNT(DISTINCT e.session_id)::float AS numerator,
          COUNT(DISTINCT e.session_id)::float AS denominator,
          COUNT(DISTINCT e.session_id)::float AS value
        FROM analytics.events e JOIN analytics.sessions s ON s.session_id=e.session_id
        JOIN analytics.users u ON u.user_id=e.user_id
        WHERE {period_sql(period, 'e.event_timestamp')} AND e.event_name='{event_name}'
          {filters_sql}
        {group}
        """
    elif compiler == "churn":
        query = f"""
        SELECT {segment},
          COUNT(DISTINCT CASE WHEN sub.cancelled_at >= '{period.start.isoformat()}'::date AND sub.cancelled_at < '{period.end.isoformat()}'::date THEN sub.subscription_id END)::float AS numerator,
          COUNT(DISTINCT CASE WHEN sub.started_at < '{period.start.isoformat()}'::date AND (sub.cancelled_at IS NULL OR sub.cancelled_at >= '{period.start.isoformat()}'::date) THEN sub.subscription_id END)::float AS denominator,
          COUNT(DISTINCT CASE WHEN sub.cancelled_at >= '{period.start.isoformat()}'::date AND sub.cancelled_at < '{period.end.isoformat()}'::date THEN sub.subscription_id END)::float /
          NULLIF(COUNT(DISTINCT CASE WHEN sub.started_at < '{period.start.isoformat()}'::date AND (sub.cancelled_at IS NULL OR sub.cancelled_at >= '{period.start.isoformat()}'::date) THEN sub.subscription_id END),0) AS value
        FROM analytics.subscriptions sub JOIN analytics.users u ON u.user_id=sub.user_id
        WHERE 1=1
          {filters_sql}
        {group}
        """
    elif compiler == "trial_to_paid":
        query = f"""
        SELECT {segment},
          COUNT(DISTINCT CASE WHEN sub.started_at <= sub.trial_started_at + interval '30 days' THEN sub.subscription_id END)::float AS numerator,
          COUNT(DISTINCT sub.subscription_id)::float AS denominator,
          COUNT(DISTINCT CASE WHEN sub.started_at <= sub.trial_started_at + interval '30 days' THEN sub.subscription_id END)::float /
            NULLIF(COUNT(DISTINCT sub.subscription_id),0) AS value
        FROM analytics.subscriptions sub JOIN analytics.users u ON u.user_id=sub.user_id
        WHERE {period_sql(period, 'sub.trial_started_at')}
          {filters_sql}
        {group}
        """
    elif compiler == "retention":
        day = definition.retention_day or 30
        query = f"""
        SELECT {segment},
          COUNT(DISTINCT CASE WHEN e.user_id IS NOT NULL THEN u.user_id END)::float AS numerator,
          COUNT(DISTINCT u.user_id)::float AS denominator,
          COUNT(DISTINCT CASE WHEN e.user_id IS NOT NULL THEN u.user_id END)::float / NULLIF(COUNT(DISTINCT u.user_id),0) AS value
        FROM analytics.users u
        LEFT JOIN analytics.events e ON e.user_id=u.user_id
          AND e.event_timestamp >= u.signup_at + interval '{day} days'
          AND e.event_timestamp < u.signup_at + interval '{day + 1} days'
          AND e.event_name IN {QUALIFYING_ACTIVITY}
        LEFT JOIN analytics.sessions s ON s.session_id=e.session_id
        WHERE {period_sql(period, 'u.signup_at')} AND u.signup_at < '{period.end.isoformat()}'::date - interval '{day} days'
          {filters_sql}
        {group}
        """
    else:
        raise ValueError(f"Metric compiler is not implemented: {compiler}")

    return SQLProposal(
        query=query.strip(),
        purpose=f"Calculate {definition.label} for {period.label}" + (f" by {dimension}" if dimension else ""),
        tables_used=["users", "sessions", "events", "subscriptions", "transactions"],
        metrics_used=[metric_name],
        assumptions=["UTC date boundaries", "The period end is exclusive"],
    )


def compile_metric_series(
    metric_name: str,
    period: DateRange,
    dimension: str | None = None,
) -> SQLProposal:
    """Compile one bounded daily series query for proactive analytics.

    The query intentionally returns only days with source rows. The service
    fills missing days according to the metric kind, preserving zero-volume
    count metrics while keeping empty rate buckets unavailable.
    """

    if metric_name not in PROACTIVE_METRICS:
        raise ValueError(f"Metric '{metric_name}' is not supported for proactive analytics")
    duration_days = (period.end - period.start).days
    if duration_days < 1 or duration_days > PROACTIVE_SERIES_MAX_DAYS:
        raise ValueError(
            f"Proactive metric series must cover between 1 and {PROACTIVE_SERIES_MAX_DAYS} days"
        )
    registry.validate_dimension(metric_name, dimension)
    if dimension is not None and metric_name not in {
        "checkout_conversion",
        "payment_success_rate",
        "payment_failures",
    }:
        raise ValueError(f"Dimensioned proactive series are not implemented for {metric_name}")
    definition = registry.metric(metric_name)
    if metric_name == "revenue":
        query = f"""
        SELECT date_trunc('day', t.timestamp)::date AS bucket,
          SUM(CASE WHEN t.status='success' THEN t.amount
                   WHEN t.status='refunded' THEN -t.amount ELSE 0 END)::float AS numerator,
          COUNT(*)::float AS denominator,
          SUM(CASE WHEN t.status='success' THEN t.amount
                   WHEN t.status='refunded' THEN -t.amount ELSE 0 END)::float AS value
        FROM analytics.transactions t JOIN analytics.users u ON u.user_id=t.user_id
        WHERE {period_sql(period, 't.timestamp')}
        GROUP BY 1 ORDER BY 1
        """
        tables = ["transactions", "users"]
    elif metric_name == "signups":
        query = f"""
        SELECT date_trunc('day', e.event_timestamp)::date AS bucket,
          COUNT(DISTINCT e.user_id)::float AS numerator,
          COUNT(DISTINCT e.user_id)::float AS denominator,
          COUNT(DISTINCT e.user_id)::float AS value
        FROM analytics.events e
        WHERE {period_sql(period, 'e.event_timestamp')} AND e.event_name='signup_completed'
        GROUP BY 1 ORDER BY 1
        """
        tables = ["events"]
    elif metric_name == "activation_rate":
        query = f"""
        WITH signups AS (
          SELECT e.user_id, MIN(e.event_timestamp) AS signup_at
          FROM analytics.events e
          WHERE {period_sql(period, 'e.event_timestamp')} AND e.event_name='signup_completed'
          GROUP BY e.user_id
        )
        SELECT signup_at::date AS bucket,
          SUM(CASE WHEN EXISTS (
            SELECT 1 FROM analytics.events activation
            WHERE activation.user_id=signups.user_id
              AND activation.event_name='onboarding_completed'
              AND activation.event_timestamp >= signups.signup_at
              AND activation.event_timestamp < signups.signup_at + interval '7 days'
          ) THEN 1 ELSE 0 END)::float AS numerator,
          COUNT(*)::float AS denominator,
          SUM(CASE WHEN EXISTS (
            SELECT 1 FROM analytics.events activation
            WHERE activation.user_id=signups.user_id
              AND activation.event_name='onboarding_completed'
              AND activation.event_timestamp >= signups.signup_at
              AND activation.event_timestamp < signups.signup_at + interval '7 days'
          ) THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS value
        FROM signups
        GROUP BY 1 ORDER BY 1
        """
        tables = ["events"]
    elif metric_name in {"checkout_conversion", "payment_success_rate"}:
        denominator_event = "checkout_started" if metric_name == "checkout_conversion" else "payment_submitted"
        numerator_event = "payment_success"
        segment_expression = DIMENSIONS[dimension] if dimension else None
        segment_select = f", COALESCE(({segment_expression})::text, 'Unknown') AS segment" if segment_expression else ""
        segment_group = f", {segment_expression}" if segment_expression else ""
        outer_segment = ", segment" if segment_expression else ""
        outer_group = ", 2" if segment_expression else ""
        segment_joins = (
            " JOIN analytics.sessions s ON s.session_id=e.session_id"
            " JOIN analytics.users u ON u.user_id=e.user_id"
            if segment_expression
            else ""
        )
        query = f"""
        WITH attempts AS (
          SELECT e.session_id{segment_select},
            MIN(e.event_timestamp) FILTER (WHERE e.event_name='{denominator_event}') AS denominator_at,
            BOOL_OR(e.event_name='{numerator_event}') AS succeeded
          FROM analytics.events e{segment_joins}
          WHERE {period_sql(period, 'e.event_timestamp')}
            AND e.event_name IN ('{denominator_event}', '{numerator_event}')
          GROUP BY e.session_id{segment_group}
        )
        SELECT denominator_at::date AS bucket{outer_segment},
          COUNT(*) FILTER (WHERE succeeded)::float AS numerator,
          COUNT(*)::float AS denominator,
          COUNT(*) FILTER (WHERE succeeded)::float / NULLIF(COUNT(*), 0) AS value
        FROM attempts
        WHERE denominator_at IS NOT NULL
        GROUP BY 1{outer_group} ORDER BY 1
        """
        tables = ["events"]
    elif metric_name == "payment_failures":
        segment_expression = DIMENSIONS[dimension] if dimension else None
        segment_select = f", COALESCE(({segment_expression})::text, 'Unknown') AS segment" if segment_expression else ""
        segment_group = f", {segment_expression}" if segment_expression else ""
        outer_segment = ", segment" if segment_expression else ""
        outer_group = ", 2" if segment_expression else ""
        segment_joins = (
            " JOIN analytics.sessions s ON s.session_id=e.session_id"
            " JOIN analytics.users u ON u.user_id=e.user_id"
            if segment_expression
            else ""
        )
        query = f"""
        WITH attempts AS (
          SELECT e.session_id{segment_select},
            MIN(e.event_timestamp) FILTER (WHERE e.event_name='checkout_started') AS attempt_at,
            BOOL_OR(e.event_name='payment_failed') AS failed
          FROM analytics.events e{segment_joins}
          WHERE {period_sql(period, 'e.event_timestamp')}
            AND e.event_name IN ('checkout_started', 'payment_failed')
          GROUP BY e.session_id{segment_group}
        )
        SELECT attempt_at::date AS bucket{outer_segment},
          COUNT(*) FILTER (WHERE failed)::float AS numerator,
          COUNT(*)::float AS denominator,
          COUNT(*) FILTER (WHERE failed)::float AS value
        FROM attempts
        WHERE attempt_at IS NOT NULL
        GROUP BY 1{outer_group} ORDER BY 1
        """
        tables = ["events"]
    elif metric_name == "dau":
        query = f"""
        SELECT date_trunc('day', e.event_timestamp)::date AS bucket,
          COUNT(DISTINCT e.user_id)::float AS numerator,
          COUNT(DISTINCT e.user_id)::float AS denominator,
          COUNT(DISTINCT e.user_id)::float AS value
        FROM analytics.events e
        WHERE {period_sql(period, 'e.event_timestamp')}
          AND e.event_name IN {QUALIFYING_ACTIVITY}
        GROUP BY 1 ORDER BY 1
        """
        tables = ["events"]
    elif metric_name == "churn_rate":
        query = f"""
        WITH days AS (
          SELECT DISTINCT date_trunc('day', cancelled_at)::date AS bucket
          FROM analytics.subscriptions
          WHERE {period_sql(period, 'cancelled_at')}
        ), daily AS (
          SELECT days.bucket,
            COUNT(DISTINCT sub.subscription_id) FILTER (
              WHERE sub.cancelled_at >= days.bucket
                AND sub.cancelled_at < days.bucket + interval '1 day'
            )::float AS numerator,
            COUNT(DISTINCT sub.subscription_id) FILTER (
              WHERE sub.started_at < days.bucket
                AND (sub.cancelled_at IS NULL OR sub.cancelled_at >= days.bucket)
            )::float AS denominator
          FROM days
          JOIN analytics.subscriptions sub
            ON sub.started_at < days.bucket + interval '1 day'
          GROUP BY days.bucket
        )
        SELECT bucket, numerator, denominator,
          numerator / NULLIF(denominator, 0) AS value
        FROM daily ORDER BY bucket
        """
        tables = ["subscriptions"]
    else:
        raise ValueError(f"Metric '{metric_name}' is not supported for proactive analytics")
    return SQLProposal(
        query=query.strip(),
        purpose=f"Calculate the daily {definition.label} series for {period.label}",
        tables_used=tables,
        metrics_used=[metric_name],
        assumptions=["UTC day buckets", "The period end is exclusive", "Missing count buckets are filled as zero"],
    )


def compile_retention_curve(
    period: DateRange,
    windows: list[int],
    cohort_type: str = "signup",
    dimension: str | None = None,
    filters: list[Filter] | None = None,
) -> SQLProposal:
    """Compile a governed multi-window retention curve.

    One query returns weekly signup/activation cohorts, cohort sizes, and the
    requested D1/D7/D30 windows. Immature cohorts remain visible with null
    values rather than being incorrectly treated as zero retention.
    """

    normalized_windows = sorted(set(windows))
    if not normalized_windows or any(day not in {1, 7, 30} for day in normalized_windows):
        raise ValueError("Retention windows must be selected from D1, D7, and D30")
    if cohort_type not in {"signup", "activation"}:
        raise ValueError("Unsupported retention cohort type")
    registry.validate_dimension("d30_retention", dimension)
    if dimension == "checkout_context":
        raise ValueError("Checkout context is not available for retention curves")

    dimension_columns = {
        "channel": "acquisition_channel",
        "campaign": "campaign",
        "country": "country",
        "device": "device",
        "browser": "browser",
        "plan": "plan",
        "company_size": "company_size",
        "cohort": "cohort",
    }
    if dimension:
        try:
            segment_column = dimension_columns[dimension]
        except KeyError as exc:
            raise ValueError(f"Dimension '{dimension}' is not available for retention curves") from exc
        segment = f"COALESCE(c.{segment_column}::text, 'Unknown')"
    else:
        segment = "'All'::text"

    max_day = max(normalized_windows)
    filter_sql = _filter_sql("d30_retention", filters)
    anchor_expression = "u.signup_at" if cohort_type == "signup" else "a.anchor_at"

    # Device/browser are derived from the user's first session. Avoid scanning
    # and aggregating the entire sessions view for overall/channel/country/plan
    # cohorts, where those attributes are not needed. This keeps the governed
    # retention statement comfortably inside the five-second runtime budget on
    # the small Supabase instance used by the public demo.
    needs_session_attributes = dimension in {"device", "browser"} or any(
        item.dimension in {"device", "browser"} for item in (filters or [])
    )
    ctes: list[str] = []
    session_join = ""
    device_expression = "'Unknown'::text"
    browser_expression = "'Unknown'::text"
    if needs_session_attributes:
        ctes.append(
            """first_sessions AS (
          SELECT s.user_id,
            MIN(s.device) AS device,
            MIN(s.browser) AS browser
          FROM analytics.sessions s
          GROUP BY s.user_id
        )"""
        )
        session_join = "LEFT JOIN first_sessions s ON s.user_id = u.user_id"
        device_expression = "COALESCE(s.device, 'Unknown')"
        browser_expression = "COALESCE(s.browser, 'Unknown')"
    if cohort_type == "activation":
        ctes.append(
            """activation_times AS (
          SELECT e.user_id,
            MIN(CASE WHEN e.event_name = 'onboarding_completed' THEN e.event_timestamp END) AS anchor_at
          FROM analytics.events e
          GROUP BY e.user_id
        )"""
        )
        session_join += "\n      LEFT JOIN activation_times a ON a.user_id = u.user_id"

    ctes.append(
        f"""cohort_users AS (
      SELECT u.user_id,
        u.signup_at,
        u.acquisition_channel,
        u.campaign,
        u.country,
        u.plan,
        u.company_size,
        {device_expression} AS device,
        {browser_expression} AS browser,
        {anchor_expression} AS anchor_at,
        date_trunc('week', {anchor_expression})::date AS cohort
      FROM analytics.users u
      {session_join}
      WHERE {anchor_expression} IS NOT NULL
        AND {anchor_expression} >= '{period.start.isoformat()}'::date
        AND {anchor_expression} < '{period.end.isoformat()}'::date
        {filter_sql}
    )"""
    )

    value_columns: list[str] = []
    for day in normalized_windows:
        value_columns.append(
            f"""COUNT(DISTINCT CASE WHEN c.anchor_at < '{period.end.isoformat()}'::date - interval '{day} days'
                AND e.event_timestamp >= c.anchor_at + interval '{day} days'
                AND e.event_timestamp < c.anchor_at + interval '{day + 1} days' THEN c.user_id END)::float /
              NULLIF(COUNT(DISTINCT CASE WHEN c.anchor_at < '{period.end.isoformat()}'::date - interval '{day} days'
                THEN c.user_id END), 0) AS d{day}"""
        )

    query = f"""
    WITH {', '.join(ctes)}
    SELECT c.cohort::text AS bucket,
      {segment} AS segment,
      COUNT(DISTINCT c.user_id)::float AS cohort_size,
      {', '.join(value_columns)}
    FROM cohort_users c
    LEFT JOIN analytics.events e ON e.user_id = c.user_id
      AND e.event_name IN {QUALIFYING_ACTIVITY}
      AND e.event_timestamp >= c.anchor_at + interval '1 day'
      AND e.event_timestamp < c.anchor_at + interval '{max_day + 1} days'
    GROUP BY c.cohort, {segment}
    ORDER BY c.cohort, segment
    """
    return SQLProposal(
        query=query.strip(),
        purpose=f"Calculate retention curve ({', '.join(f'D{day}' for day in normalized_windows)}) for {period.label}",
        tables_used=["users", "events"] + (["sessions"] if needs_session_attributes else []),
        metrics_used=[f"d{day}_retention" for day in normalized_windows],
        assumptions=[
            "UTC date boundaries",
            "Weekly cohorts are anchored to signup or first activation",
            "Immature retention windows are returned as null",
        ],
    )


def compile_funnel(
    funnel: str,
    period: DateRange,
    dimension: str | None = None,
    filters: list[Filter] | None = None,
) -> SQLProposal:
    if funnel not in {"acquisition", "onboarding", "checkout"}:
        raise ValueError(f"Unknown funnel: {funnel}")

    # Funnel dimensions describe the context of the user's entry into the
    # funnel. Transaction-only dimensions belong to revenue diagnostics and
    # would otherwise reference aliases that are not present in this query.
    funnel_dimensions = {"channel", "campaign", "country", "device", "browser", "plan", "company_size"}
    if dimension and dimension not in funnel_dimensions:
        raise ValueError(f"Dimension '{dimension}' is not available for funnel analysis")
    if filters and any(item.dimension not in funnel_dimensions for item in filters):
        raise ValueError("Funnel filters must use acquisition, user, or session dimensions")

    steps = {
        "acquisition": ["landing_page_viewed", "signup_started", "signup_completed"],
        "onboarding": [
            "signup_completed",
            "onboarding_started",
            "profile_completed",
            "integration_connected",
            "onboarding_completed",
        ],
        "checkout": ["pricing_viewed", "checkout_started", "payment_submitted", "payment_success"],
    }[funnel]
    filters_sql = _filter_sql(None, filters)
    values = ", ".join(f"'{step}'" for step in steps)
    segment_expression = DIMENSIONS[dimension] if dimension else "'All'::text"
    segment_group = f", {DIMENSIONS[dimension]}" if dimension else ""

    # Build an ordered, cohort-safe funnel. The old event-level aggregation
    # counted every matching event in the period, allowing (for example)
    # integration events from returning users to exceed signup users. Each
    # stage below is now restricted to users who completed every prior stage in
    # order, so stage conversion and drop-off are always meaningful.
    ctes = [
        f"""funnel_base AS (
          SELECT e.user_id,
            COALESCE(({segment_expression})::text, 'Unknown') AS segment,
            MIN(CASE WHEN e.event_name = '{steps[0]}' THEN e.event_timestamp END) AS stage_1_at
          FROM analytics.events e
          JOIN analytics.sessions s ON s.session_id = e.session_id
          JOIN analytics.users u ON u.user_id = e.user_id
          WHERE {period_sql(period, 'e.event_timestamp')}
            AND e.event_name IN ({values})
            {filters_sql}
          GROUP BY e.user_id{segment_group}
        )"""
    ]
    previous_cte = "funnel_base"
    previous_stage_columns = ["stage_1_at"]
    for stage_number, step in enumerate(steps[1:], start=2):
        current_cte = f"funnel_stage_{stage_number}"
        group_columns = ", ".join(["previous.user_id", "previous.segment", *[f"previous.{column}" for column in previous_stage_columns]])
        ctes.append(
            f"""{current_cte} AS (
              SELECT previous.*,
                MIN(e.event_timestamp) AS stage_{stage_number}_at
              FROM {previous_cte} previous
              LEFT JOIN analytics.events e
                ON e.user_id = previous.user_id
                AND e.event_name = '{step}'
                AND e.event_timestamp >= previous.stage_{stage_number - 1}_at
                AND e.event_timestamp < '{period.end.isoformat()}'::date
              GROUP BY {group_columns}
            )"""
        )
        previous_cte = current_cte
        previous_stage_columns.append(f"stage_{stage_number}_at")

    stage_selects = [
        f"""SELECT segment,
          '{step}' AS stage,
          COUNT(DISTINCT CASE WHEN stage_{stage_number}_at IS NOT NULL THEN user_id END)::float AS users,
          {stage_number} AS stage_order
        FROM {previous_cte}
        GROUP BY segment"""
        for stage_number, step in enumerate(steps, start=1)
    ]
    query = f"WITH {', '.join(ctes)}\n" + "\nUNION ALL\n".join(stage_selects) + "\nORDER BY stage_order, segment"
    return SQLProposal(
        query=query.strip(),
        purpose=f"Calculate the {funnel} funnel",
        tables_used=["events", "sessions", "users"],
        metrics_used=[f"{funnel}_funnel"],
        assumptions=["Stages are ordered and cumulative within the resolved UTC period"],
    )
