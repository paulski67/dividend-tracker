import requests
import time
import logging
from utilities.logger import setup_logger

from datetime import datetime
from pymongo.errors import DuplicateKeyError

from models.mongo import get_collection
from models.settings import get_api_key
from models.utils import safe_int
from models.api_utils import check_api_response
from models.api_utils import verify_database_connection
from models.constants import (
    STOCK_TICKERS,
    FREE_CASH_FLOW_COLLECTION,
    THROTTLE_SECONDS
)

# =========================================================
# Logging
# =========================================================

setup_logger()


# =========================================
# Check Mongo DB is up
# =========================================

if not verify_database_connection():
    sys.exit(1)

# =========================================
# Mongo Collection
# =========================================

collection = get_collection(
    FREE_CASH_FLOW_COLLECTION
)

# =========================================
# API Key
# =========================================

API_KEY = get_api_key()

# =========================================
# Get Cash Flow Data
# =========================================

def get_cash_flow(ticker):

    url = (
        f"https://www.alphavantage.co/query?"
        f"function=CASH_FLOW"
        f"&symbol={ticker}"
        f"&apikey={API_KEY}"
    )

    response = requests.get(url)

    data = response.json()

    status = check_api_response(data)

    if status != "OK":
        return status

    # bad ticker or empty response
    if len(data) == 0:
        logging.warning(f"No data returned for {ticker}")
        return None

    return data

# =========================================
# Save Cash Flow Data
# =========================================

def save_cash_flow_data(ticker, data):

    inserted_count = 0
    duplicate_count = 0

    quarterly_reports = data.get("quarterlyReports", [])

    for report in quarterly_reports:

        try:

            operating_cash_flow = safe_int(
                report.get("operatingCashflow")
            )

            capital_expenditures = safe_int(
                report.get("capitalExpenditures")
            )

            if (operating_cash_flow  in [None, "None"] or
                capital_expenditures in [None, "None"] ):

                logging.warning(
                    f"Skipping invalid Free Cash FLOW record for {ticker}"
                )

                continue
            
            free_cash_flow = (
                operating_cash_flow -
                capital_expenditures
            )           
            
            document = {

                "ticker": ticker,

                "fiscal_date": report.get(
                    "fiscalDateEnding"
                ),

                "operating_cash_flow":
                    operating_cash_flow,

                "capital_expenditures":
                    capital_expenditures,

                "free_cash_flow":
                    free_cash_flow,

                "created_at":
                    datetime.utcnow()
            }

            collection.insert_one(document)

            inserted_count += 1

        except DuplicateKeyError:

            duplicate_count += 1

        except Exception as e:

            logging.error(f"\nERROR SAVING {ticker}")
            logging.error(e)

    return inserted_count, duplicate_count

# =========================================
# Main Processing Loop
# =========================================

logging.info("===================================")
logging.info("STARTING FREE CASH FLOW LOAD")
logging.info("===================================")

total_inserted = 0
total_duplicates = 0

for ticker in STOCK_TICKERS:

    logging.info(f"Processing {ticker}...")

    should_sleep = True

    try:

        data = get_cash_flow(ticker)

        # ---------------------------------
        # API limit reached
        # ---------------------------------

        if data == "LIMIT_REACHED":

            logging.error("Stopping script due to API limit.")

            should_sleep = False

            break

        if not data:

            logging.warning(f"Skipping {ticker}")

            continue

        inserted, duplicates = save_cash_flow_data(
            ticker,
            data
        )

        total_inserted += inserted
        total_duplicates += duplicates

        logging.info(
            f"{ticker}: "
            f"{duplicates} duplicates, "
            f"{inserted} inserted"
        )

    except Exception as e:

        logging.error(f"\nERROR processing {ticker}")

        logging.error(e)

    finally:

        if should_sleep:

            logging.info(
                f"Sleeping {THROTTLE_SECONDS} seconds..."             
            )

            time.sleep(THROTTLE_SECONDS)

# =========================================
# Final Summary
# =========================================
logging.info("")
logging.info("===================================")
logging.info("FREE CASH FLOW LOAD COMPLETE")
logging.info("===================================")

logging.info(f"Inserted: {total_inserted}")
logging.info(f"Duplicates Skipped: {total_duplicates}")