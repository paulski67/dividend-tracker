from datetime import datetime
import sys
import requests
import time
import logging

from utilities.logger import setup_logger

from models.mongo import get_collection
from models.settings import get_api_key
from models.api_utils import (
    verify_database_connection,
    check_api_response
)
from models.constants import (
    STOCK_TICKERS,
    INCOME_STATEMENTS_COLLECTION,
    THROTTLE_SECONDS
)
from models.utils import safe_int

# =========================================================
# Logging
# =========================================================

setup_logger()

# =========================================================
# Check MongoDB
# =========================================================

if not verify_database_connection():
    sys.exit(1)

# =========================================================
# API Key
# =========================================================

API_KEY = get_api_key()

# =========================================================
# Mongo
# =========================================================

collection = get_collection(
    INCOME_STATEMENTS_COLLECTION
)

should_sleep = True
total_updated = 0

# =========================================================
# Helpers
# =========================================================

def parse_date(date_string):

    if not date_string:
        return None

    try:
        return datetime.strptime(
            date_string,
            "%Y-%m-%d"
        )
    except:
        return None


def clean_report(report):

    cleaned = {}

    for key, value in report.items():

        # --------------------------
        # None values
        # --------------------------

        if value in (None, "None", ""):
            cleaned[key] = None

        # --------------------------
        # Dates
        # --------------------------

        elif key == "fiscalDateEnding":

            cleaned[key] = parse_date(value)

        # --------------------------
        # Strings
        # --------------------------

        elif key == "reportedCurrency":

            cleaned[key] = value

        # --------------------------
        # Everything else is numeric
        # --------------------------

        else:

            cleaned[key] = safe_int(value)

    return cleaned


def get_income_statement(ticker):

    url = (
        "https://www.alphavantage.co/query"
        f"?function=INCOME_STATEMENT"
        f"&symbol={ticker}"
        f"&apikey={API_KEY}"
    )

    response = requests.get(url)

    if response.status_code != 200:
        logging.error(
            f"HTTP ERROR for {ticker}: "
            f"{response.status_code}"
        )
        return None

    data = response.json()

    status = check_api_response(data)

    if status != "OK":
        return status

    if len(data) == 0:
        logging.warning(
            f"No data returned for {ticker}"
        )
        return None

    return data

# =========================================================
# Main
# =========================================================

logging.info("===================================")
logging.info("STARTING INCOME STATEMENT LOAD")
logging.info("===================================")

for ticker in STOCK_TICKERS:

    logging.info(f"Processing {ticker}...")

    try:

        data = get_income_statement(ticker)

        if data == "LIMIT_REACHED":
            logging.error(
                "Stopping due to API limit."
            )
            should_sleep = False
            break

        if not data:
            logging.warning(
                f"Skipping {ticker}"
            )
            continue

        annual_reports = [
            clean_report(report)
            for report in data.get(
                "annualReports",
                []
            )
        ]

        quarterly_reports = [
            clean_report(report)
            for report in data.get(
                "quarterlyReports",
                []
            )
        ]

        existing = collection.find_one(
            {"ticker": ticker}
        )

        document = {

            "ticker": ticker,

            "annual_reports": annual_reports,

            "quarterly_reports": quarterly_reports,

            "source": "alphavantage",

            "last_updated": datetime.utcnow(),

            "created_at":
                existing["created_at"]
                if existing and "created_at" in existing
                else datetime.utcnow()
        }

        collection.replace_one(
            {"ticker": ticker},
            document,
            upsert=True
        )

        total_updated += 1

        logging.info(
            f"{ticker} updated."
        )

    except Exception as e:

        logging.error(
            f"ERROR processing {ticker}"
        )

        logging.exception(e)

    finally:

        if should_sleep:

            logging.info(
                f"Sleeping "
                f"{THROTTLE_SECONDS} seconds..."
            )

            time.sleep(
                THROTTLE_SECONDS
            )

        else:

            break

logging.info("")
logging.info("===================================")
logging.info("INCOME STATEMENT LOAD COMPLETE")
logging.info(
    f"Tickers updated: {total_updated}"
)
logging.info("===================================")