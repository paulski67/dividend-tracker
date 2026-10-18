"""
One-time migration: convert stored UTC timestamps to Eastern time.

Before 2026-10 every collector wrote datetime.utcnow(). The code now writes
Eastern wall-clock time (models.utils.now_local), so this rewrites the
existing documents to match:

    timestamps (created_at, updated_at, ...)   UTC -> America/New_York
    daily_metrics "date" bucket                Eastern calendar day of the
                                               document's created_at
    daily_metrics "fundamentals_as_of"         follows its source document's
                                               re-bucketed date

Calendar dates from Alpha Vantage (ex_dividend_date, payment_date,
eps_through, fiscal dates) are not times and are left alone.

A marker document in the "migrations" collection stops it running twice,
which would shift everything a second time.

Usage (from the project root, after a backup):

    python -m utilities.archive_manager backup backups\\pre_local_time
    python -m utilities.migrate_to_local_time            preview only
    python -m utilities.migrate_to_local_time --apply    write changes
"""

import argparse
import logging
import sys
from collections import Counter
from datetime import timezone

from utilities.logger import setup_logger
from models.mongo import get_collection
from models.utils import LOCAL_TZ, now_local
from models.api_utils import verify_database_connection
from models.constants import (
    DAILY_METRICS_COLLECTION,
    DIVIDEND_HISTORY_COLLECTION,
    FREE_CASH_FLOW_COLLECTION,
    INCOME_STATEMENTS_COLLECTION,
    WEEKLY_SCORES_COLLECTION,
    PORTFOLIO_SCORECARD_COLLECTION,
)

MIGRATION_ID = "timestamps_utc_to_eastern"

TIMESTAMP_FIELDS = {
    DAILY_METRICS_COLLECTION: ["created_at"],
    DIVIDEND_HISTORY_COLLECTION: ["created_at", "updated_at", "override_date"],
    FREE_CASH_FLOW_COLLECTION: ["created_at", "updated_at"],
    INCOME_STATEMENTS_COLLECTION: ["created_at", "last_updated"],
    WEEKLY_SCORES_COLLECTION: ["run_date"],
    PORTFOLIO_SCORECARD_COLLECTION: ["created_at"],
}

setup_logger()


def to_local(value):
    """
    Naive UTC datetime (as Mongo returns it) -> naive Eastern datetime.
    """

    return (
        value.replace(tzinfo=timezone.utc)
        .astimezone(LOCAL_TZ)
        .replace(tzinfo=None)
    )


def bucket(value):

    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def plan_collection(name):
    """
    Return [(_id, {field: new_value})] for one collection.
    """

    fields = TIMESTAMP_FIELDS[name]
    updates = []

    for doc in get_collection(name).find():

        changes = {
            field: to_local(doc[field])
            for field in fields
            if doc.get(field) is not None
        }

        if changes:
            updates.append((doc["_id"], changes))

    return updates


def plan_daily_metrics_buckets(updates):
    """
    Re-bucket daily_metrics "date" by the Eastern day of created_at.
    Adds to the created_at changes already in updates.
    """

    collection = get_collection(DAILY_METRICS_COLLECTION)
    by_id = dict(updates)

    # (ticker, old date) -> new date, for remapping fundamentals_as_of
    date_map = {}
    moved = Counter()

    for doc in collection.find():

        local_created = by_id.get(doc["_id"], {}).get("created_at")

        if local_created is None:
            continue

        new_date = bucket(local_created)
        date_map[(doc["ticker"], doc["date"])] = new_date

        if new_date != doc["date"]:
            by_id[doc["_id"]]["date"] = new_date
            moved[(doc["date"].date(), new_date.date())] += 1

    for doc in collection.find({"fundamentals_as_of": {"$ne": None}}):

        new_value = date_map.get(
            (doc["ticker"], doc["fundamentals_as_of"])
        )

        if new_value and new_value != doc["fundamentals_as_of"]:
            by_id.setdefault(doc["_id"], {})["fundamentals_as_of"] = new_value

    # Two documents for one ticker landing in the same bucket would break
    # the collector's one-per-day duplicate check.
    final = Counter()

    for doc in collection.find({}, {"ticker": 1, "date": 1}):
        new_date = by_id.get(doc["_id"], {}).get("date", doc["date"])
        final[(doc["ticker"], new_date)] += 1

    collisions = {k: n for k, n in final.items() if n > 1}

    return list(by_id.items()), moved, collisions


def main():

    parser = argparse.ArgumentParser(
        description="Convert stored UTC timestamps to Eastern time"
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the changes (default is a preview)."
    )

    args = parser.parse_args()

    if not verify_database_connection():
        sys.exit(1)

    migrations = get_collection("migrations")

    if migrations.find_one({"_id": MIGRATION_ID}):
        logging.error(
            f"Migration {MIGRATION_ID} already applied - refusing to "
            f"shift timestamps a second time."
        )
        sys.exit(1)

    plans = {name: plan_collection(name) for name in TIMESTAMP_FIELDS}

    plans[DAILY_METRICS_COLLECTION], moved, collisions = (
        plan_daily_metrics_buckets(plans[DAILY_METRICS_COLLECTION])
    )

    for name, updates in plans.items():
        logging.info(f"{name}: {len(updates)} documents to update")

    logging.info(
        f"daily_metrics buckets moving: {sum(moved.values())} documents"
    )

    for (old, new), count in sorted(moved.items()):
        logging.info(f"    {old} -> {new}: {count}")

    if collisions:

        for (ticker, day), count in sorted(collisions.items()):
            logging.error(
                f"Collision: {ticker} would have {count} documents "
                f"on {day.date()}"
            )

        logging.error("Resolve the collisions above before applying.")
        sys.exit(1)

    if not args.apply:
        logging.info("Preview only - rerun with --apply to write.")
        return

    for name, updates in plans.items():

        collection = get_collection(name)

        for _id, changes in updates:
            collection.update_one({"_id": _id}, {"$set": changes})

        logging.info(f"{name}: updated {len(updates)} documents")

    migrations.insert_one({
        "_id": MIGRATION_ID,
        "applied_at": now_local(),
    })

    logging.info("Migration complete")


if __name__ == "__main__":
    main()
