import json
import os

from bson import json_util

from models.mongo import (
    get_collection
)

from models.constants import (
    DAILY_METRICS_COLLECTION,
    DIVIDEND_HISTORY_COLLECTION,
    FREE_CASH_FLOW_COLLECTION,
    DIVIDEND_ANALYSIS_COLLECTION,
    WEEKLY_SCORES_COLLECTION,
    PORTFOLIO_SCORECARD_COLLECTION
)

# ----------------------------------------

BACKUP_DIR = "C:\\Projects\\backups\\dividend_analyis"

os.makedirs(
    BACKUP_DIR,
    exist_ok=True
)

collections = [
    DAILY_METRICS_COLLECTION,
    DIVIDEND_HISTORY_COLLECTION,
    FREE_CASH_FLOW_COLLECTION,
    DIVIDEND_ANALYSIS_COLLECTION,
    WEEKLY_SCORES_COLLECTION,
    PORTFOLIO_SCORECARD_COLLECTION
]

# ----------------------------------------

for collection_name in collections:

    collection = get_collection(
        collection_name
    )

    documents = list(
        collection.find()
    )

    file_path = (
        f"{BACKUP_DIR}/"
        f"{collection_name}.json"
    )

    with open(
        file_path,
        "w"
    ) as file:

        file.write(
            json_util.dumps(
                documents,
                indent=4
            )
        )

    print(
        f"Backed up "
        f"{collection_name}"
    )

print("\nBackup complete.")