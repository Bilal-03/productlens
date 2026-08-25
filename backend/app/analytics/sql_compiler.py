from __future__ import annotations

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
}


def period_sql(period: DateRange, column: str) -> str:
    return f"{column} >= '{period.start.isoformat()}'::date AND {column} < '{period.end.isoformat()}'::date"


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
        expression = DIMENSIONS[item.dimension]
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
          AND e.event_name IN ('dashboard_viewed','report_created','report_exported','ai_assistant_used','integration_connected','team_member_invited')
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
          AND e.event_name IN ('dashboard_viewed','report_created','report_exported','ai_assistant_used')
        LEFT JOIN analytics.sessions s ON s.session_id=e.session_id
        WHERE {period_sql(period, 'u.signup_at')} AND u.signup_at < '{period.end.isoformat()}'::date - interval '{day} days'
          {filters_sql}
        {group}
        """
    elif compiler == "feature_adoption":
        query = f"""
        WITH active AS (
          SELECT DISTINCT e.user_id FROM analytics.events e
          JOIN analytics.users u ON u.user_id=e.user_id
          JOIN analytics.sessions s ON s.session_id=e.session_id
          WHERE {period_sql(period, 'e.event_timestamp')} AND e.event_name='dashboard_viewed'
            {filters_sql}
        )
        SELECT COALESCE(e.feature, 'Other') AS segment,
          COUNT(DISTINCT e.user_id)::float AS numerator,
          (SELECT COUNT(*) FROM active)::float AS denominator,
          COUNT(DISTINCT e.user_id)::float / NULLIF((SELECT COUNT(*) FROM active),0) AS value
        FROM analytics.events e JOIN active a ON a.user_id=e.user_id
        JOIN analytics.users u ON u.user_id=e.user_id
        JOIN analytics.sessions s ON s.session_id=e.session_id
        WHERE {period_sql(period, 'e.event_timestamp')} AND e.feature IS NOT NULL
          {filters_sql}
        GROUP BY e.feature
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
    activation_cte = ""
    activation_join = ""
    if cohort_type == "activation":
        activation_cte = """
        activation_times AS (
          SELECT e.user_id,
            MIN(CASE WHEN e.event_name = 'onboarding_completed' THEN e.event_timestamp END) AS anchor_at
          FROM analytics.events e
          GROUP BY e.user_id
        ),"""
        activation_join = "LEFT JOIN activation_times a ON a.user_id = u.user_id"

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
    WITH first_sessions AS (
      SELECT s.user_id,
        MIN(s.device) AS device,
        MIN(s.browser) AS browser
      FROM analytics.sessions s
      GROUP BY s.user_id
    ), {activation_cte}
    cohort_users AS (
      SELECT u.user_id,
        u.signup_at,
        u.acquisition_channel,
        u.campaign,
        u.country,
        u.plan,
        u.company_size,
        COALESCE(s.device, 'Unknown') AS device,
        COALESCE(s.browser, 'Unknown') AS browser,
        {anchor_expression} AS anchor_at,
        date_trunc('week', {anchor_expression})::date AS cohort
      FROM analytics.users u
      LEFT JOIN first_sessions s ON s.user_id = u.user_id
      {activation_join}
      WHERE {anchor_expression} IS NOT NULL
        AND {anchor_expression} >= '{period.start.isoformat()}'::date
        AND {anchor_expression} < '{period.end.isoformat()}'::date
        {filter_sql}
    )
    SELECT c.cohort::text AS bucket,
      {segment} AS segment,
      COUNT(DISTINCT c.user_id)::float AS cohort_size,
      {', '.join(value_columns)}
    FROM cohort_users c
    LEFT JOIN analytics.events e ON e.user_id = c.user_id
      AND e.event_name IN ('dashboard_viewed', 'report_created', 'report_exported', 'ai_assistant_used')
      AND e.event_timestamp >= c.anchor_at + interval '1 day'
      AND e.event_timestamp < c.anchor_at + interval '{max_day + 1} days'
    GROUP BY c.cohort, {segment}
    ORDER BY c.cohort, segment
    """
    return SQLProposal(
        query=query.strip(),
        purpose=f"Calculate retention curve ({', '.join(f'D{day}' for day in normalized_windows)}) for {period.label}",
        tables_used=["users", "sessions", "events"],
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
    if dimension == "payment_method":
        raise ValueError("Payment method is not available for funnel analysis")
    if dimension and dimension not in DIMENSIONS:
        raise ValueError(f"Unknown funnel dimension: {dimension}")
    if filters and any(item.dimension == "payment_method" for item in filters):
        raise ValueError("Payment method is not available for funnel analysis")
    steps = {
        "acquisition": ["landing_page_viewed", "signup_started", "signup_completed"],
        "onboarding": ["signup_completed", "onboarding_started", "profile_completed", "integration_connected", "onboarding_completed"],
        "checkout": ["pricing_viewed", "checkout_started", "payment_submitted", "payment_success"],
    }[funnel]
    segment, group = segment_parts(dimension)
    filters_sql = _filter_sql(None, filters)
    values = ", ".join(f"'{step}'" for step in steps)
    order = "CASE e.event_name " + " ".join(f"WHEN '{step}' THEN {i}" for i, step in enumerate(steps, 1)) + " END"
    query = f"""
    SELECT {segment}, e.event_name AS stage, COUNT(DISTINCT e.user_id)::float AS users, {order} AS stage_order
    FROM analytics.events e JOIN analytics.sessions s ON s.session_id=e.session_id
    JOIN analytics.users u ON u.user_id=e.user_id
    WHERE {period_sql(period, 'e.event_timestamp')} AND e.event_name IN ({values})
      {filters_sql}
    {group + (', e.event_name' if group else 'GROUP BY e.event_name')}
    ORDER BY stage_order
    """
    return SQLProposal(query=query.strip(), purpose=f"Calculate the {funnel} funnel", tables_used=["events", "sessions", "users"], metrics_used=[f"{funnel}_funnel"])
