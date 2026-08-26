from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import psycopg
from sqlalchemy.engine import make_url

from app.analytics.time_ranges import DATASET_AS_OF
from app.config import get_settings

SEED = 20260824


@dataclass(frozen=True)
class Profile:
    users: int
    sessions: int
    subscriptions: int
    transactions: int


PROFILES = {
    "smoke": Profile(users=800, sessions=4_500, subscriptions=450, transactions=1_400),
    "full": Profile(users=20_000, sessions=120_000, subscriptions=12_000, transactions=25_000),
}

CHANNELS = np.array(["Paid Social", "Organic Search", "Direct", "Referral", "Paid Search"])
CHANNEL_PROBS = np.array([0.34, 0.16, 0.22, 0.12, 0.16])
COUNTRIES = np.array(["United States", "India", "United Kingdom", "Germany", "Canada", "Australia"])
REGIONS = {
    "United States": "North America",
    "Canada": "North America",
    "India": "Asia Pacific",
    "Australia": "Asia Pacific",
    "United Kingdom": "Europe",
    "Germany": "Europe",
}
PLANS = np.array(["Free", "Starter", "Pro", "Business"])
COMPANY_SIZES = np.array(["Solo", "SMB", "Mid-market", "Enterprise"])
FEATURES = np.array(["AI Assistant", "Exports", "Integrations", "Team Invitations", "Advanced Reports"])


def utc_at(day: date, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(minutes=minute)


def weighted_user(rng: np.random.Generator, weights: np.ndarray) -> int:
    return int(rng.choice(len(weights), p=weights))


class DatasetGenerator:
    def __init__(self, profile: Profile, seed: int = SEED) -> None:
        self.profile = profile
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.as_of = DATASET_AS_OF
        self.start = self.as_of - timedelta(days=180)
        # ``as_of`` is an exclusive UTC boundary for every generated fact.
        # Keep an inclusive final instant for rows that are timestamped on the
        # last dataset day (August 23 for the portfolio seed).
        self.data_end = utc_at(self.as_of)
        self.last_data_timestamp = self.data_end - timedelta(microseconds=1)
        self.user_rows: list[tuple[Any, ...]] = []
        self.session_rows: list[tuple[Any, ...]] = []
        self.subscription_rows: list[tuple[Any, ...]] = []
        self.transaction_rows: list[tuple[Any, ...]] = []
        self.experiment_rows: list[tuple[Any, ...]] = []
        self.experiment_assignment_rows: list[tuple[Any, ...]] = []
        self.user_experiment_variant: dict[int, str] = {}
        self.user_signup: list[datetime] = []
        self.user_channel: list[str] = []
        self.user_plan: list[str] = []
        self.user_company: list[str] = []
        self.user_adopter: list[bool] = []

    def users(self) -> list[tuple[Any, ...]]:
        if self.user_rows:
            return self.user_rows
        for offset in range(self.profile.users):
            user_id = offset + 1
            signup_day = self.start + timedelta(days=int(self.rng.integers(0, 180)))
            signup_at = utc_at(signup_day, int(self.rng.integers(0, 1440)))
            channel = str(self.rng.choice(CHANNELS, p=CHANNEL_PROBS))
            country = str(self.rng.choice(COUNTRIES))
            company = str(self.rng.choice(COMPANY_SIZES, p=[0.22, 0.47, 0.23, 0.08]))
            plan_probs = [0.48, 0.27, 0.18, 0.07]
            if company in {"Mid-market", "Enterprise"}:
                plan_probs = [0.16, 0.24, 0.38, 0.22]
            plan = str(self.rng.choice(PLANS, p=plan_probs))
            adopter = bool(self.rng.random() < 0.32)
            campaign = {
                "Paid Social": "social-growth-26",
                "Paid Search": "search-intent-26",
                "Organic Search": "organic-content",
                "Referral": "customer-referral",
                "Direct": "direct-none",
            }[channel]
            self.user_rows.append(
                (user_id, signup_at, country, REGIONS[country], channel, campaign, plan, company, "web")
            )
            self.user_signup.append(signup_at)
            self.user_channel.append(channel)
            self.user_plan.append(plan)
            self.user_company.append(company)
            self.user_adopter.append(adopter)
        return self.user_rows

    def sessions(self) -> list[tuple[Any, ...]]:
        if self.session_rows:
            return self.session_rows
        self.users()
        weights = np.array(
            [
                (2.3 if adopter else 1.0)
                * (0.76 if channel == "Paid Social" else 1.14 if channel == "Organic Search" else 1.0)
                for adopter, channel in zip(self.user_adopter, self.user_channel, strict=True)
            ],
            dtype=float,
        )
        weights /= weights.sum()
        guaranteed_sessions = min(self.profile.users, self.profile.sessions)

        def build_session(session_id: int, user_index: int) -> tuple[Any, ...]:
            earliest = self.user_signup[user_index].date()
            available_days = max(1, (self.as_of - earliest).days)
            started_day = earliest + timedelta(days=int(self.rng.integers(0, available_days)))
            started = utc_at(started_day, int(self.rng.integers(0, 1440)))
            ended = min(
                started + timedelta(minutes=int(self.rng.integers(4, 55))),
                self.data_end,
            )
            device = str(self.rng.choice(["Desktop", "Mobile", "Tablet"], p=[0.52, 0.43, 0.05]))
            if device == "Mobile":
                browser = str(self.rng.choice(["Safari", "Chrome", "Firefox"], p=[0.48, 0.47, 0.05]))
                os_name = "iOS" if browser == "Safari" else "Android"
            else:
                browser = str(self.rng.choice(["Chrome", "Safari", "Firefox", "Edge"], p=[0.55, 0.18, 0.12, 0.15]))
                os_name = str(self.rng.choice(["macOS", "Windows", "Linux"], p=[0.34, 0.57, 0.09]))
            channel = self.user_channel[user_index]
            campaign = self.user_rows[user_index][5]
            landing_page = str(self.rng.choice(["/", "/pricing", "/templates", "/product"], p=[0.35, 0.3, 0.15, 0.2]))
            return (session_id, user_index + 1, started, ended, device, browser, os_name, channel, campaign, landing_page)

        # Give every synthetic user a first session so lifecycle events can be
        # linked to a valid user/session pair. Remaining sessions are sampled
        # with the product-usage weighting used by the portfolio dataset.
        for offset in range(guaranteed_sessions):
            self.session_rows.append(build_session(offset + 1, offset))
        for offset in range(guaranteed_sessions, self.profile.sessions):
            self.session_rows.append(build_session(offset + 1, weighted_user(self.rng, weights)))
        return self.session_rows

    def experiments(self) -> list[tuple[Any, ...]]:
        if self.experiment_rows:
            return self.experiment_rows
        self.users()
        started_at = utc_at(date(2026, 5, 1))
        self.experiment_rows.append(
            (
                1,
                "onboarding-redesign",
                "Onboarding redesign",
                "Reducing onboarding friction increases activation",
                "activation_rate",
                "control",
                "completed",
                started_at,
                self.data_end,
            )
        )
        return self.experiment_rows

    def experiment_assignments(self) -> list[tuple[Any, ...]]:
        if self.experiment_assignment_rows:
            return self.experiment_assignment_rows
        self.experiments()
        for user_id, signup_at in enumerate(self.user_signup, start=1):
            if signup_at.date() < date(2026, 5, 1):
                continue
            variant = "variant" if user_id % 2 == 0 else "control"
            self.user_experiment_variant[user_id] = variant
            self.experiment_assignment_rows.append((1, user_id, variant, signup_at))
        return self.experiment_assignment_rows

    def events(self) -> Iterator[tuple[Any, ...]]:
        sessions = self.sessions()
        self.experiment_assignments()
        first_session: dict[int, int] = {}
        session_start: dict[int, datetime] = {}
        for row in sessions:
            first_session.setdefault(int(row[1]), int(row[0]))
            session_start.setdefault(int(row[1]), row[2])
        event_id = 0
        for session in sessions:
            session_id, user_id, started, ended, device, browser, _, channel, _, landing_page = session
            minute_span = max(2, int((ended - started).total_seconds() // 60))

            def emit(name: str, sequence: int, page: str, feature: str | None = None, props: dict[str, Any] | None = None) -> tuple[Any, ...]:
                nonlocal event_id
                event_id += 1
                timestamp = min(
                    started + timedelta(minutes=min(sequence, minute_span - 1)),
                    self.last_data_timestamp,
                )
                return (event_id, user_id, session_id, name, timestamp, page, feature, json.dumps(props or {}))

            yield emit("dashboard_viewed", 1, "/dashboard")
            feature = str(self.rng.choice(FEATURES))
            feature_event = {
                "AI Assistant": "ai_assistant_used",
                "Exports": "report_exported",
                "Integrations": "integration_connected",
                "Team Invitations": "team_member_invited",
                "Advanced Reports": "report_created",
            }[feature]
            yield emit(feature_event, 2, "/dashboard", feature)
            if self.rng.random() < 0.62:
                yield emit("report_created", 3, "/reports", "Advanced Reports")
            if self.rng.random() < 0.48:
                yield emit("feature_search_used", 4, "/dashboard", "Search")

            if first_session[user_id] == session_id:
                yield emit("landing_page_viewed", 0, landing_page)
                yield emit("signup_started", 1, "/signup")
                signup_probability = 0.52 if channel == "Paid Social" else 0.90 if channel == "Organic Search" else 0.82
                if self.rng.random() < signup_probability:
                    yield emit("signup_completed", 2, "/signup/success")
                    yield emit("onboarding_started", 3, "/onboarding")
                    yield emit("profile_completed", 4, "/onboarding/profile")
                    friction = started.date() >= date(2026, 7, 15)
                    integration_probability = (
                        0.44
                        if friction
                        else 0.55
                        if channel == "Paid Social"
                        else 0.82
                        if channel == "Organic Search"
                        else 0.74
                    )
                    if self.user_adopter[user_id - 1] or self.rng.random() < integration_probability:
                        yield emit("integration_connected", 5, "/onboarding/integration", "Integrations")
                        if self.user_adopter[user_id - 1]:
                            yield emit("team_member_invited", 6, "/onboarding/team", "Team Invitations")
                        completion_probability = 0.72 if channel == "Paid Social" else 0.86 if channel == "Organic Search" else 0.82
                        if self.user_experiment_variant.get(user_id) == "variant":
                            completion_probability = 0.98
                        if self.rng.random() < completion_probability:
                            yield emit("onboarding_completed", 7, "/onboarding/complete")

            if self.rng.random() < 0.27:
                yield emit("pricing_viewed", 4, "/pricing")
                yield emit("checkout_started", 5, "/checkout")
                yield emit("payment_submitted", 6, "/checkout/payment")
                incident = (
                    started.date() >= date(2026, 8, 18)
                    and device == "Mobile"
                    and browser == "Safari"
                    and channel == "Paid Social"
                )
                success_probability = 0.58 if incident else 0.89
                if self.rng.random() < success_probability:
                    yield emit("payment_success", 7, "/checkout/success")
                else:
                    yield emit(
                        "payment_failed",
                        7,
                        "/checkout/error",
                        props={"failure_reason": "browser_payment_error" if incident else "card_declined"},
                    )

        # Subscription lifecycle events use the user's first session so the
        # event table remains fully referentially linked. They are emitted
        # after the session events because subscriptions are generated lazily
        # and are cached for the subsequent transaction load.
        for subscription_id, user_id, _, _, started, _, _, cancelled_at, _, _ in self.subscriptions():
            session_id = first_session.get(int(user_id))
            if session_id is None:
                continue
            yield (
                event_id := event_id + 1,
                user_id,
                session_id,
                "subscription_started",
                min(max(started, session_start[int(user_id)]), self.last_data_timestamp),
                "/billing",
                None,
                json.dumps({"subscription_id": subscription_id}),
            )
            if cancelled_at is not None:
                yield (
                    event_id := event_id + 1,
                    user_id,
                    session_id,
                    "subscription_cancelled",
                    min(cancelled_at, self.last_data_timestamp),
                    "/billing/cancelled",
                    None,
                    json.dumps({"subscription_id": subscription_id}),
                )

    def subscriptions(self) -> list[tuple[Any, ...]]:
        if self.subscription_rows:
            return self.subscription_rows
        self.users()
        selected = self.rng.choice(self.profile.users, size=self.profile.subscriptions, replace=False)
        for offset, user_index_raw in enumerate(selected):
            user_index = int(user_index_raw)
            subscription_id = offset + 1
            user_id = user_index + 1
            plan = self.user_plan[user_index]
            if plan == "Free":
                plan = str(self.rng.choice(["Starter", "Pro"], p=[0.72, 0.28]))
            started = min(
                self.user_signup[user_index] + timedelta(days=int(self.rng.integers(0, 22))),
                self.last_data_timestamp,
            )
            trial_started = started - timedelta(days=14)
            billing_interval = str(self.rng.choice(["monthly", "annual"], p=[0.78, 0.22]))
            base_mrr = {"Starter": 29.0, "Pro": 89.0, "Business": 249.0}[plan]
            churn_probability = 0.09
            scenario = self.user_company[user_index] == "SMB" and billing_interval == "monthly"
            if scenario and started.date() < date(2026, 8, 1):
                # Make the August MRR movement robust to the random mix of
                # new subscriptions: a substantial share of pre-August SMB
                # monthly subscriptions cancels during the incident month.
                churn_probability = 0.65
            cancelled = self.rng.random() < churn_probability
            cancelled_at = None
            status = "active"
            if cancelled:
                earliest_cancel = max(started.date(), date(2026, 8, 1) if scenario else started.date())
                cancellation_start = max(started, utc_at(earliest_cancel))
                available_seconds = max(
                    0,
                    int((self.last_data_timestamp - cancellation_start).total_seconds()),
                )
                cancelled_at = cancellation_start + timedelta(
                    seconds=int(self.rng.integers(0, available_seconds + 1))
                )
                status = "cancelled"
            self.subscription_rows.append(
                (subscription_id, user_id, plan, status, started, trial_started, started, cancelled_at, base_mrr, billing_interval)
            )
        return self.subscription_rows

    def transactions(self) -> list[tuple[Any, ...]]:
        if self.transaction_rows:
            return self.transaction_rows
        subscriptions = self.subscriptions()
        for offset in range(self.profile.transactions):
            transaction_id = offset + 1
            sub = subscriptions[int(self.rng.integers(0, len(subscriptions)))]
            subscription_id, user_id, plan, _, started, _, _, cancelled_at, mrr, interval = sub
            end_at = min(self.data_end, cancelled_at or self.data_end)
            available_seconds = max(1, int((end_at - started).total_seconds()))
            occurred = started + timedelta(
                seconds=int(self.rng.integers(0, available_seconds))
            )
            company = self.user_company[user_id - 1]
            scenario = company == "SMB" and interval == "monthly" and occurred.date() >= date(2026, 8, 1)
            # Failed August renewals are the second independent revenue
            # driver. The loader validates both the failed-renewal increase
            # and the resulting net-revenue decline from generated rows.
            success_probability = 0.20 if scenario else 0.93
            status = "success" if self.rng.random() < success_probability else "failed"
            tx_type = "charge" if occurred - started < timedelta(days=35) else "renewal"
            if status == "success" and self.rng.random() < 0.025:
                status = "refunded"
                tx_type = "refund"
            amount = float(mrr) * (12 if interval == "annual" else 1)
            method = str(self.rng.choice(["Card", "PayPal", "Bank Transfer"], p=[0.77, 0.16, 0.07]))
            failure = None if status != "failed" else ("renewal_declined" if scenario else "card_declined")
            self.transaction_rows.append(
                (transaction_id, user_id, subscription_id, occurred, amount, "USD", status, method, tx_type, failure)
            )
        return self.transaction_rows


def copy_rows(connection: psycopg.Connection[Any], table: str, columns: list[str], rows: Iterable[tuple[Any, ...]]) -> int:
    count = 0
    with connection.cursor() as cursor, cursor.copy(
        f"COPY {table} ({', '.join(columns)}) FROM STDIN"
    ) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def psycopg_url(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def load_dataset(generator: DatasetGenerator, profile_name: str) -> dict[str, int]:
    settings = get_settings()
    counts: dict[str, int] = {}
    with psycopg.connect(psycopg_url(settings.database_admin_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "TRUNCATE core.experiment_assignments, core.experiments, core.transactions, core.subscriptions, core.events, core.sessions, core.users RESTART IDENTITY CASCADE"
            )
            cursor.execute("TRUNCATE operational.dataset_metadata, operational.result_cache")
        counts["users"] = copy_rows(connection, "core.users", ["user_id", "signup_at", "country", "region", "acquisition_channel", "campaign", "plan", "company_size", "signup_source"], generator.users())
        counts["sessions"] = copy_rows(connection, "core.sessions", ["session_id", "user_id", "started_at", "ended_at", "device", "browser", "operating_system", "channel", "campaign", "landing_page"], generator.sessions())
        counts["experiments"] = copy_rows(connection, "core.experiments", ["experiment_id", "experiment_key", "name", "hypothesis", "primary_metric", "control_variant", "status", "started_at", "ended_at"], generator.experiments())
        counts["experiment_assignments"] = copy_rows(connection, "core.experiment_assignments", ["experiment_id", "user_id", "variant", "assigned_at"], generator.experiment_assignments())
        counts["events"] = copy_rows(connection, "core.events", ["event_id", "user_id", "session_id", "event_name", "event_timestamp", "page", "feature", "properties"], generator.events())
        counts["subscriptions"] = copy_rows(connection, "core.subscriptions", ["subscription_id", "user_id", "plan", "status", "started_at", "trial_started_at", "trial_ended_at", "cancelled_at", "mrr", "billing_interval"], generator.subscriptions())
        counts["transactions"] = copy_rows(connection, "core.transactions", ["transaction_id", "user_id", "subscription_id", "timestamp", "amount", "currency", "status", "payment_method", "transaction_type", "failure_reason"], generator.transactions())
        with connection.cursor() as cursor:
            identity_columns = {
                "users": "user_id",
                "sessions": "session_id",
                "experiments": "experiment_id",
                "events": "event_id",
                "subscriptions": "subscription_id",
                "transactions": "transaction_id",
            }
            for table, identity_column in identity_columns.items():
                cursor.execute(
                    f"SELECT setval(pg_get_serial_sequence('core.{table}', '{identity_column}'), COALESCE((SELECT max({identity_column}) FROM core.{table}), 1))"
                )
            cursor.execute(
                """INSERT INTO operational.dataset_metadata
                (dataset_version, dataset_as_of, seed, profile, row_counts, scenario_parameters)
                VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    f"{profile_name}-{generator.seed}",
                    generator.as_of,
                    generator.seed,
                    profile_name,
                    json.dumps(counts),
                    json.dumps({
                        "checkout_incident_start": "2026-08-18",
                        "onboarding_friction_start": "2026-07-15",
                        "revenue_incident_start": "2026-08-01",
                    }),
                ),
            )
        connection.commit()
    return counts


def validate_scenarios(url: str) -> dict[str, Any]:
    checkout_query = """
    WITH attempts AS (
      SELECT s.device, s.browser, s.channel,
             CASE WHEN e.event_name='payment_success' THEN 1 ELSE 0 END AS success,
             CASE WHEN e.event_name IN ('payment_success','payment_failed') THEN 1 ELSE 0 END AS attempt
      FROM core.events e JOIN core.sessions s USING(session_id)
      WHERE e.event_timestamp >= '2026-08-18' AND e.event_name IN ('payment_success','payment_failed')
    )
    SELECT SUM(success)::float / NULLIF(SUM(attempt),0) AS rate FROM attempts
    WHERE device='Mobile' AND browser='Safari' AND channel='Paid Social'
    """
    baseline_query = checkout_query.replace("e.event_timestamp >= '2026-08-18'", "e.event_timestamp >= '2026-08-10' AND e.event_timestamp < '2026-08-17'")
    onboarding_query = """
    WITH profiles AS (
      SELECT DISTINCT e.session_id, e.user_id,
             MIN(e.event_timestamp) FILTER (WHERE e.event_name='profile_completed') AS profile_at
      FROM core.events e
      WHERE e.event_name IN ('profile_completed','integration_connected')
        AND e.event_timestamp >= '2026-07-01' AND e.event_timestamp < '2026-08-24'
      GROUP BY e.session_id, e.user_id
      HAVING COUNT(*) FILTER (WHERE e.event_name='profile_completed') > 0
    )
    SELECT
      AVG(CASE WHEN profile_at >= '2026-07-15' AND EXISTS (
        SELECT 1 FROM core.events i
        WHERE i.session_id=profiles.session_id
          AND i.event_name='integration_connected'
          AND i.event_timestamp >= profiles.profile_at
      ) THEN 1.0 WHEN profile_at >= '2026-07-15' THEN 0.0 END) AS after_rate,
      AVG(CASE WHEN profile_at < '2026-07-15' AND EXISTS (
        SELECT 1 FROM core.events i
        WHERE i.session_id=profiles.session_id
          AND i.event_name='integration_connected'
          AND i.event_timestamp >= profiles.profile_at
      ) THEN 1.0 WHEN profile_at < '2026-07-15' THEN 0.0 END) AS before_rate
    FROM profiles
    """
    retention_association_query = """
    WITH eligible_users AS (
      SELECT user_id, signup_at
      FROM core.users
      WHERE signup_at < '2026-07-24'
    ), event_flags AS (
      SELECT u.user_id,
        BOOL_OR(e.event_name='integration_connected') AS integrated,
        BOOL_OR(e.event_name='team_member_invited') AS invited,
        BOOL_OR(
          e.event_name IN ('dashboard_viewed','report_created','report_exported','ai_assistant_used')
          AND e.event_timestamp >= u.signup_at + interval '30 days'
          AND e.event_timestamp < u.signup_at + interval '31 days'
        ) AS returned
      FROM eligible_users u
      JOIN core.events e ON e.user_id=u.user_id
      GROUP BY u.user_id
    ), eligible AS (
      SELECT u.user_id,
        COALESCE(f.integrated, false) AS integrated,
        COALESCE(f.invited, false) AS invited,
        COALESCE(f.returned, false) AS returned
      FROM eligible_users u
      LEFT JOIN event_flags f ON f.user_id=u.user_id
    )
    SELECT
      AVG(returned::int) FILTER (WHERE integrated AND invited) AS joined_rate,
      AVG(returned::int) FILTER (WHERE NOT (integrated AND invited)) AS other_rate,
      COUNT(*) FILTER (WHERE integrated AND invited) AS joined_users
    FROM eligible
    """
    revenue_query = """
    SELECT period, SUM(s.mrr)::float AS mrr
    FROM (VALUES ('previous'::text, '2026-07-24'::date), ('current'::text, '2026-08-24'::date)) periods(period, as_of)
    JOIN core.subscriptions s ON s.started_at < periods.as_of
      AND (s.cancelled_at IS NULL OR s.cancelled_at >= periods.as_of)
    JOIN core.users u ON u.user_id=s.user_id
    WHERE u.company_size='SMB' AND s.billing_interval='monthly'
    GROUP BY period
    """
    revenue_direction_query = """
    WITH periods(label, start_at, end_at) AS (
      VALUES
        ('previous'::text, '2026-07-01'::date, '2026-08-01'::date),
        ('current'::text, '2026-08-01'::date, '2026-08-24'::date)
    )
    SELECT p.label,
      COALESCE(SUM(CASE WHEN t.status='success' THEN t.amount
                        WHEN t.status='refunded' THEN -t.amount ELSE 0 END), 0)::float AS revenue,
      COUNT(*) FILTER (WHERE t.status='failed' AND t.transaction_type='renewal') AS failed_renewals
    FROM periods p
    LEFT JOIN core.transactions t ON t.timestamp >= p.start_at AND t.timestamp < p.end_at
    LEFT JOIN core.subscriptions s ON s.subscription_id=t.subscription_id
    LEFT JOIN core.users u ON u.user_id=t.user_id
    WHERE u.company_size='SMB' AND s.billing_interval='monthly'
    GROUP BY p.label
    """
    lifecycle_query = """
    SELECT
      COUNT(*) FILTER (WHERE event_name='subscription_started') AS started_events,
      COUNT(*) FILTER (WHERE event_name='subscription_cancelled') AS cancelled_events,
      (SELECT COUNT(*) FROM core.subscriptions) AS subscription_rows
    FROM core.events
    """
    acquisition_query = """
    WITH user_flags AS (
      SELECT u.user_id, u.acquisition_channel, u.signup_at,
        BOOL_OR(e.event_name='signup_completed') AS signed_up,
        BOOL_OR(e.event_name='onboarding_completed') AS activated,
        BOOL_OR(
          u.signup_at < '2026-07-24'
          AND e.event_name IN ('dashboard_viewed','report_created','report_exported','ai_assistant_used')
          AND e.event_timestamp >= u.signup_at + interval '30 days'
          AND e.event_timestamp < u.signup_at + interval '31 days'
        ) AS retained
      FROM core.users u
      JOIN core.events e ON e.user_id=u.user_id
      GROUP BY u.user_id, u.acquisition_channel, u.signup_at
    ), channel_cohorts AS (
      SELECT acquisition_channel,
        COUNT(*) FILTER (WHERE signed_up)::float AS signups,
        COUNT(*) FILTER (WHERE activated)::float AS activated,
        COUNT(*) FILTER (WHERE signup_at < '2026-07-24')::float AS cohort_size,
        COUNT(*) FILTER (WHERE signup_at < '2026-07-24' AND retained)::float AS retained
      FROM user_flags
      GROUP BY acquisition_channel
    )
      SELECT acquisition_channel,
        activated / NULLIF(signups, 0) AS activation_rate,
      retained / NULLIF(cohort_size, 0) AS retention_rate,
      signups
    FROM channel_cohorts
    WHERE acquisition_channel IN ('Paid Social', 'Organic Search')
    """
    with psycopg.connect(psycopg_url(url)) as connection, connection.cursor() as cursor:
        # Scenario validation is a trusted, one-time administration task. A
        # bounded longer timeout prevents Supabase's small compute tier from
        # cancelling the full-profile association check at its default limit.
        cursor.execute("SET statement_timeout = '120s'")
        cursor.execute("SELECT profile FROM operational.dataset_metadata ORDER BY generated_at DESC LIMIT 1")
        profile_row = cursor.fetchone()
        profile = str(profile_row[0]) if profile_row else "unknown"
        cursor.execute(checkout_query)
        incident_row = cursor.fetchone()
        incident = incident_row[0] if incident_row else None
        cursor.execute(baseline_query)
        baseline_row = cursor.fetchone()
        baseline = baseline_row[0] if baseline_row else None
        cursor.execute(onboarding_query)
        onboarding_row = cursor.fetchone()
        onboarding_after = onboarding_row[0] if onboarding_row else None
        onboarding_before = onboarding_row[1] if onboarding_row else None
        cursor.execute(retention_association_query)
        association_row = cursor.fetchone()
        joined_rate = association_row[0] if association_row else None
        other_rate = association_row[1] if association_row else None
        joined_users = association_row[2] if association_row else 0
        cursor.execute(revenue_query)
        revenue_rows = {str(row[0]): float(row[1]) for row in cursor.fetchall()}
        cursor.execute(revenue_direction_query)
        revenue_direction_rows = {
            str(row[0]): {"revenue": float(row[1] or 0), "failed_renewals": int(row[2] or 0)}
            for row in cursor.fetchall()
        }
        cursor.execute(lifecycle_query)
        lifecycle_row = cursor.fetchone()
        lifecycle_started = int(lifecycle_row[0] or 0) if lifecycle_row else 0
        lifecycle_cancelled = int(lifecycle_row[1] or 0) if lifecycle_row else 0
        lifecycle_subscriptions = int(lifecycle_row[2] or 0) if lifecycle_row else 0
        cursor.execute(acquisition_query)
        acquisition_rows = {str(row[0]): row for row in cursor.fetchall()}
    organic = acquisition_rows.get("Organic Search")
    paid_social = acquisition_rows.get("Paid Social")
    if incident is None or baseline is None or incident >= baseline:
        raise RuntimeError("Checkout scenario validation failed")
    if onboarding_after is None or onboarding_before is None or onboarding_after >= onboarding_before:
        raise RuntimeError("Onboarding friction scenario validation failed")
    if joined_rate is None or other_rate is None or joined_users < 100 or joined_rate <= other_rate:
        raise RuntimeError("Integration and team invitation retention scenario validation failed")
    if profile != "smoke" and revenue_rows.get("current", 0) >= revenue_rows.get("previous", 0):
        raise RuntimeError("SMB monthly MRR scenario validation failed")
    previous_revenue = revenue_direction_rows.get("previous", {})
    current_revenue = revenue_direction_rows.get("current", {})
    if profile != "smoke" and (
        current_revenue.get("revenue", 0) >= previous_revenue.get("revenue", 0)
        or current_revenue.get("failed_renewals", 0) <= previous_revenue.get("failed_renewals", 0)
    ):
        raise RuntimeError("SMB monthly revenue and failed-renewal scenario validation failed")
    if lifecycle_started != lifecycle_subscriptions or lifecycle_cancelled <= 0:
        raise RuntimeError("Subscription lifecycle event scenario validation failed")
    quality_direction_valid = bool(organic and paid_social and organic[1] > paid_social[1])
    if profile != "smoke":
        quality_direction_valid = quality_direction_valid and bool(organic and paid_social and organic[2] > paid_social[2])
    if not quality_direction_valid:
        raise RuntimeError("Acquisition quality scenario validation failed")
    return {
        "mobile_safari_paid_social_before": baseline,
        "mobile_safari_paid_social_after": incident,
        "onboarding_transition_before": onboarding_before,
        "onboarding_transition_after": onboarding_after,
        "integration_team_d30": joined_rate,
        "other_d30": other_rate,
        "joined_users": joined_users,
        "smb_monthly_mrr_previous": revenue_rows.get("previous"),
        "smb_monthly_mrr_current": revenue_rows.get("current"),
        "smb_monthly_revenue_previous": previous_revenue.get("revenue"),
        "smb_monthly_revenue_current": current_revenue.get("revenue"),
        "smb_monthly_failed_renewals_previous": previous_revenue.get("failed_renewals"),
        "smb_monthly_failed_renewals_current": current_revenue.get("failed_renewals"),
        "subscription_started_events": lifecycle_started,
        "subscription_cancelled_events": lifecycle_cancelled,
        "paid_social_activation": paid_social[1] if paid_social else None,
        "organic_search_activation": organic[1] if organic else None,
        "paid_social_retention": paid_social[2] if paid_social else None,
        "organic_search_retention": organic[2] if organic else None,
        "profile": profile,
        "retention_direction_checked": profile != "smoke",
        "validated": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ProductLens synthetic analytics data")
    parser.add_argument("--profile", choices=PROFILES, default="smoke")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--load", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        validation = validate_scenarios(get_settings().database_admin_url)
        print(json.dumps({"scenario_validation": validation}, default=str, indent=2))
        return
    generator = DatasetGenerator(PROFILES[args.profile], args.seed)
    if not args.load:
        print(json.dumps({"profile": args.profile, "seed": args.seed, "requires": "--load"}))
        return
    counts = load_dataset(generator, args.profile)
    validation = validate_scenarios(get_settings().database_admin_url)
    print(json.dumps({"counts": counts, "scenario_validation": validation}, default=str, indent=2))


if __name__ == "__main__":
    main()
