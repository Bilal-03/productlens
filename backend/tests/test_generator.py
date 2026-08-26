from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime

from app.data.generate import PROFILES, DatasetGenerator


def test_smoke_generator_emits_referential_lifecycle_and_checkout_events() -> None:
    generator = DatasetGenerator(PROFILES["smoke"])
    events = list(generator.events())
    subscriptions = generator.subscriptions()
    counts = Counter(str(row[3]) for row in events)

    assert counts["subscription_started"] == len(subscriptions)
    assert counts["subscription_cancelled"] > 0
    assert counts["payment_success"] > 0
    assert counts["payment_failed"] > 0

    by_session: dict[int, set[str]] = defaultdict(set)
    for row in events:
        by_session[int(row[2])].add(str(row[3]))
        if row[3] == "payment_failed":
            properties = json.loads(str(row[7]))
            assert properties["failure_reason"] in {"browser_payment_error", "card_declined"}
    assert all("payment_submitted" in by_session[int(row[2])] for row in events if row[3] == "payment_failed")


def test_generator_keeps_all_facts_inside_exclusive_dataset_boundary() -> None:
    generator = DatasetGenerator(PROFILES["smoke"])
    users = generator.users()
    sessions = generator.sessions()
    events = list(generator.events())
    subscriptions = generator.subscriptions()
    transactions = generator.transactions()

    assert all(row[1] < generator.data_end for row in users)
    assert all(row[2] < generator.data_end and row[3] <= generator.data_end for row in sessions)
    assert all(row[4] < generator.data_end for row in events)
    assert all(
        row[4] < generator.data_end and (row[7] is None or row[7] >= row[4])
        for row in subscriptions
    )
    assert all(row[3] < generator.data_end for row in transactions)

    # Keep this assertion explicit so a future timestamp refactor cannot
    # silently return naive datetimes that bypass UTC comparisons.
    assert all(isinstance(row[4], datetime) and row[4].tzinfo is not None for row in events)
