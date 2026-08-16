"""
cleanup_dividend_history.py

ONE-OFF maintenance script.

Fixes the fallout from the July 10, 2026 bug in save_dividend_history.py
(commit f3af7e9) where a shadowed loop variable caused every dividend
record saved after that date to have NULL payment_date / record_date /
declaration_date / frequency, and (since there was no unique index) each
pipeline rerun added another duplicate document instead of correcting
the old one.

What this script does, per (ticker, ex_dividend_date) group:
  1. If any document in the group has a non-null payment_date, keep the
     OLDEST such "good" document (the one saved before the bug existed)
     and delete the rest.
  2. If every document in the group is null (i.e. the good record was
     never saved, or has since aged out), keep the single oldest
     document (by created_at) and delete the rest, so at least the
     ex_dividend_date/amount survive without duplicates.
  3. After cleanup, create a unique index on {ticker, ex_dividend_date}
     so this class of duplicate can't reoccur, and so the upsert logic
     in the fixed save_dividend_history.py has something to key off.

Run this ONCE, after replacing save_dividend_history.py with the fixed
version, and BEFORE the next scheduled run of the pipeline.

Usage:
    python cleanup_dividend_history.py            # dry run (default)
    python cleanup_dividend_history.py --apply     # actually delete/index

Run from the project root (same place you'd run the collectors) so
config/config.ini resolves correctly.
"""

import argparse
import logging
from collections import defaultdict

from pymongo.errors import DuplicateKeyError

from models.mongo import get_collection
from models.api_utils import verify_database_connection
from models.constants import DIVIDEND_HISTORY_COLLECTION
from utilities.logger import setup_logger


def pick_keeper(docs):
    """
    Given all documents for one (ticker, ex_dividend_date) group,
    return the single document to keep.
    """

    good_docs = [d for d in docs if d.get("payment_date") is not None]

    if good_docs:
        # Prefer the earliest "good" record - it's the one saved
        # before the bug was introduced, so its data is trustworthy.
        good_docs.sort(key=lambda d: d.get("created_at") or d["_id"].generation_time)
        return good_docs[0]

    # No good record exists for this group at all. Keep the oldest
    # of whatever we have so ex_dividend_date/amount aren't lost,
    # even though the null fields will stay null until the next
    # successful collector run refreshes it.
    docs.sort(key=lambda d: d.get("created_at") or d["_id"].generation_time)
    return docs[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete duplicates and create the index. "
             "Without this flag, the script only reports what it would do.",
    )
    args = parser.parse_args()

    setup_logger()

    logging.info("===================================")
    logging.info("DIVIDEND HISTORY CLEANUP")
    logging.info(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    logging.info("===================================")

    if not verify_database_connection():
        logging.error("Could not connect to MongoDB. Aborting.")
        return

    collection = get_collection(DIVIDEND_HISTORY_COLLECTION)

    all_docs = list(collection.find({}))
    logging.info(f"Loaded {len(all_docs)} total documents.")

    groups = defaultdict(list)
    for doc in all_docs:
        key = (doc["ticker"], doc["ex_dividend_date"])
        groups[key].append(doc)

    duplicate_groups = {k: v for k, v in groups.items() if len(v) > 1}
    logging.info(
        f"{len(groups)} unique (ticker, ex_dividend_date) combinations, "
        f"{len(duplicate_groups)} of which have duplicates."
    )

    total_deleted = 0
    total_kept_null = 0

    for (ticker, ex_date), docs in duplicate_groups.items():

        keeper = pick_keeper(docs)
        to_delete = [d["_id"] for d in docs if d["_id"] != keeper["_id"]]

        if keeper.get("payment_date") is None:
            total_kept_null += 1
            logging.warning(
                f"{ticker} {ex_date:%Y-%m-%d}: no clean record found in "
                f"{len(docs)} duplicates - keeping one with null dates. "
                f"Will self-heal next successful collector run."
            )

        logging.info(
            f"{ticker} {ex_date:%Y-%m-%d}: {len(docs)} docs -> "
            f"keeping 1, deleting {len(to_delete)}"
        )

        if args.apply and to_delete:
            collection.delete_many({"_id": {"$in": to_delete}})

        total_deleted += len(to_delete)

    logging.info("-----------------------------------")
    logging.info(f"Duplicate documents {'deleted' if args.apply else 'that would be deleted'}: {total_deleted}")
    logging.info(f"Groups kept with null dates (need a future refresh): {total_kept_null}")
    logging.info("-----------------------------------")

    if not args.apply:
        logging.info(
            "Dry run complete. Re-run with --apply to actually delete "
            "duplicates and create the unique index."
        )
        return

    # -------------------------------------------------------------
    # Create the unique index so this can't happen again, and so
    # the fixed collector's upsert logic has a key to match on.
    # -------------------------------------------------------------
    try:
        collection.create_index(
            [("ticker", 1), ("ex_dividend_date", 1)],
            unique=True,
            name="uniq_ticker_ex_dividend_date",
        )
        logging.info("Created unique index on {ticker, ex_dividend_date}.")

    except DuplicateKeyError:
        logging.error(
            "Index creation failed - duplicates still exist. "
            "Re-run this script to confirm cleanup finished, then retry."
        )
        return

    logging.info("===================================")
    logging.info("CLEANUP COMPLETE")
    logging.info("===================================")


if __name__ == "__main__":
    main()
