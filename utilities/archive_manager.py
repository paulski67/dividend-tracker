import argparse
import os
import sys

from bson import json_util

from models.mongo import get_collection

from models.constants import (
    DAILY_METRICS_COLLECTION,
    DIVIDEND_HISTORY_COLLECTION,
    FREE_CASH_FLOW_COLLECTION,
    DIVIDEND_ANALYSIS_COLLECTION,
    WEEKLY_SCORES_COLLECTION,
    PORTFOLIO_SCORECARD_COLLECTION,
)

# --------------------------------------------------------------------

COLLECTIONS = {
    DAILY_METRICS_COLLECTION: "daily_metrics.json",
    DIVIDEND_HISTORY_COLLECTION: "dividend_history.json",
    FREE_CASH_FLOW_COLLECTION: "free_cash_flow_metrics.json",
    DIVIDEND_ANALYSIS_COLLECTION: "dividend_analysis.json",
    WEEKLY_SCORES_COLLECTION: "weekly_scores.json",
    PORTFOLIO_SCORECARD_COLLECTION: "portfolio_scorecards.json",
}

# --------------------------------------------------------------------


def backup(backup_dir):

    os.makedirs(backup_dir, exist_ok=True)

    print()
    print(f"Backing up MongoDB to:")
    print(f"    {backup_dir}")
    print()

    for collection_name, filename in COLLECTIONS.items():

        collection = get_collection(collection_name)

        documents = list(collection.find())

        file_path = os.path.join(backup_dir, filename)

        with open(file_path, "w", encoding="utf-8") as file:
            file.write(
                json_util.dumps(
                    documents,
                    indent=4
                )
            )

        print(
            f"Backed up "
            f"{collection_name:<25}"
            f"{len(documents):>8} documents"
        )

    print()
    print("Backup complete.")

# --------------------------------------------------------------------


def restore(backup_dir):

    if not os.path.isdir(backup_dir):
        print(f"\nERROR: Backup directory not found:")
        print(f"    {backup_dir}")
        sys.exit(1)

    print()
    print("=======================================================")
    print("                     WARNING")
    print("=======================================================")
    print()
    print("This operation will DELETE the contents of the")
    print("'dividend_tracker' MongoDB database and replace")
    print("them with the backup located at:")
    print()
    print(f"    {backup_dir}")
    print()
    print("Collections to be restored:")
    print()

    for collection_name in COLLECTIONS:
        print(f"   • {collection_name}")

    print()
    print("Type RESTORE to continue.")
    print("Any other response will cancel the operation.")
    print()

    answer = input("> ").strip().upper()

    if answer != "RESTORE":
        print()
        print("Restore cancelled.")
        return

    print()

    for collection_name, filename in COLLECTIONS.items():

        file_path = os.path.join(backup_dir, filename)

        if not os.path.exists(file_path):
            print(
                f"Skipping "
                f"{collection_name:<25}"
                f"(backup file not found)"
            )
            continue

        with open(file_path, "r", encoding="utf-8") as file:
            documents = json_util.loads(file.read())

        collection = get_collection(collection_name)

        collection.delete_many({})

        if documents:
            collection.insert_many(documents)

        print(
            f"Restored "
            f"{collection_name:<25}"
            f"{len(documents):>8} documents"
        )

    print()
    print("Restore complete.")

# --------------------------------------------------------------------


def main():

    parser = argparse.ArgumentParser(
        description="Dividend Tracker archive manager"
    )

    parser.add_argument(
        "action",
        choices=["backup", "restore"],
        help="Action to perform."
    )

    parser.add_argument(
        "directory",
        help="Backup directory."
    )

    args = parser.parse_args()

    if args.action == "backup":
        backup(args.directory)

    elif args.action == "restore":
        restore(args.directory)

    else:
        parser.print_help()
        sys.exit(1)

# --------------------------------------------------------------------


if __name__ == "__main__":
    main()