from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
import sys
import requests
import time
import logging
from utilities.logger import setup_logger


from models.mongo import get_collection
from models.settings import get_api_key
from models.utils import safe_float
from models.api_utils import verify_database_connection
from models.api_utils import check_api_response
from models.constants import (
    STOCK_TICKERS,
    DIVIDEND_HISTORY_COLLECTION,
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
# API Key
# =========================================

API_KEY = get_api_key()

# =========================================
# Other variables
# =========================================
should_sleep = True

# =========================================================
# MONGODB
# =========================================================

collection = get_collection(DIVIDEND_HISTORY_COLLECTION)

# =========================================================
# HELPERS
# =========================================================



# TODO: This needs to go in a utilities
def parse_date(date_string):
    """
    Convert YYYY-MM-DD string to datetime.
    """

    try:
        return datetime.strptime(date_string, "%Y-%m-%d")

    except:
        return None

#for checking reasonable divvy 
def validate_dividend_record(
    ticker,
    amount,
    previous_amount
):

    if previous_amount is None:
        return True

    if amount > previous_amount * 2:

        logging.warning(
            f"{ticker}: suspicious dividend jump "
            f"{previous_amount} -> {amount}"
        )

        return False

    return True

def get_dividend_history(ticker):

    url = (
        "https://www.alphavantage.co/query"
        f"?function=DIVIDENDS"
        f"&symbol={ticker}"
        f"&apikey={API_KEY}"
    )

    response = requests.get(url)

    if response.status_code != 200:
        logging.error(f"HTTP ERROR for {ticker}: {response.status_code}")
        return None

    data = response.json()

    status = check_api_response(data)

    if status != "OK":
        return status

    # -------------------------------------------------
    # BAD SYMBOL
    # -------------------------------------------------

    if "Error Message" in data:
        logging.warning(f"Invalid ticker: {ticker}")
        return None

    # -------------------------------------------------
    # EMPTY DATA
    # -------------------------------------------------

    if "data" not in data:
        logging.warning(f"No dividend data returned for {ticker}")
        return None

    return data["data"]
# =========================================================
# MAIN
# =========================================================

logging.info("===================================")
logging.info("STARTING DIVIDEND HISTORY LOAD")
logging.info("===================================")

total_inserted = 0
total_duplicates = 0

for ticker in STOCK_TICKERS:

    ticker_inserted = 0
    ticker_duplicates = 0
    
    try:
        dividends = get_dividend_history(ticker)

        if dividends == "LIMIT_REACHED":
            should_sleep = False
            logging.error("Stopping script due to API limit.")
            break

        if not dividends:
            logging.warning(f"Skipping {ticker}")
            continue
        
        logging.info(f"Processing {ticker}...")
        
        for dividend in dividends:

            ex_date = parse_date(
                dividend.get("ex_dividend_date")
            )

            amount = safe_float(
                dividend.get("amount")
            )

            if not ex_date or amount is None:
                continue

            # check for bogus data  a divvy jump that isn't
            # reasonable
            previous = collection.find_one(
                {
                    "ticker": ticker
                },
                sort=[
                    (
                        "ex_dividend_date",
                        -1
                    )
                ]
            )

            for i, dividend in enumerate(dividends):

                previous_amount = None

                if i + 1 < len(dividends):
                    previous_amount = safe_float(
                        dividends[i + 1]["amount"]
                    )

            validation_status = "valid"

            if not validate_dividend_record(
                ticker,
                amount,
                previous_amount
            ):

                validation_status = "suspect"

                logging.warning(
                    f"{ticker}: "
                    f"Dividend marked suspect "
                    f"{previous_amount} -> {amount}"
                )

            document = {

                "ticker": ticker,

                "ex_dividend_date": ex_date,

                "amount": amount,

                "payment_date": parse_date(
                    dividend.get("payment_date")
                ),

                "record_date": parse_date(
                    dividend.get("record_date")
                ),

                "declaration_date": parse_date(
                    dividend.get("declaration_date")
                ),

                "frequency": dividend.get("frequency"),

                "source": "alphavantage",

                "created_at": datetime.utcnow(),
                   
                "validation_status": validation_status
            }

            try:

                collection.insert_one(document)
                #-------------------
                # increment counters
                #-------------------
                
                ticker_inserted += 1
                total_inserted += 1

            except DuplicateKeyError:
                
                #-------------------
                # increment counters
                #-------------------

                ticker_duplicates += 1
                total_duplicates += 1
        
    except Exception as e:

        logging.error(f"ERROR processing {ticker}")

        logging.error(e)

    finally:

        # -----------------------------------------------------
        # API THROTTLE PROTECTION
        # -----------------------------------------------------

        if should_sleep:
            logging.info(
                f"{ticker}:  "
                f"{ticker_duplicates} duplicates, "
                f"{ticker_inserted} inserted"
            )
            logging.info(f"Sleeping {THROTTLE_SECONDS} seconds...\n")
            time.sleep(THROTTLE_SECONDS) 
        else:
            break
   
logging.info("")
logging.info("===================================")
logging.info("DIVIDEND HISTORY LOAD COMPLETE")
logging.info(f"Inserted: {total_inserted}")
logging.info(f"Duplicates Skipped: {total_duplicates}")
logging.info("===================================")

