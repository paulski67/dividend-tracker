from datetime import datetime
from pymongo import MongoClient
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
    DAILY_METRICS_COLLECTION,
    THROTTLE_SECONDS
)
from utilities.dividend_helper import (
    calc_standard_payout_ratio
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
total_inserted = 0

# =========================================================
# MONGODB CONNECTION
# =========================================================

collection = get_collection(DAILY_METRICS_COLLECTION)

# =========================================================
# HELPERS
# =========================================================

def get_overview(ticker):
    """
    Pull OVERVIEW endpoint from Alpha Vantage.
    """

    url = (
        "https://www.alphavantage.co/query"
        f"?function=OVERVIEW"
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
    
    # bad ticker or empty response
    if len(data) == 0:
        logging.warning(f"No data returned for {ticker}")
        return None

    return data


# =========================================================
# MAIN
# =========================================================

logging.info("===================================")
logging.info("STARTING NIGHTLY METRIC COLLECTION")
logging.info("===================================")

today = datetime.utcnow().replace(
    hour=0,
    minute=0,
    second=0,
    microsecond=0
)

logging.info(f"UTC today bucket: {today}")

for ticker in STOCK_TICKERS:

    logging.info(f"Processing {ticker}...")

    try:
        # -----------------------------------------------------
        # Prevent duplicate inserts
        # -----------------------------------------------------
        
        existing = collection.find_one({
            "ticker": ticker,
            "date": today
        })

        if existing:
            logging.warning(f"{ticker} already exists for today.")
            continue

        # -----------------------------------------------------
        # API CALL
        # -----------------------------------------------------

        data = get_overview(ticker)


        if data == "LIMIT_REACHED":
            logging.error("Stopping script due to API limit.")
            should_sleep = False
            break
            
        if not data:
            logging.warning(f"Skipping {ticker}")
            logging.warning(json.dumps(data, indent=2))
            continue

        # -----------------------------------------------------
        # PREPARE PAYOUT RATIO
        # -----------------------------------------------------

        dividend_per_share = safe_float(
            data.get("DividendPerShare")
        )

        eps = safe_float(
            data.get("EPS")
        )

        payout_ratio = calc_standard_payout_ratio(
            dividend_per_share,
            eps
        )


        logging.info(
            f"\n\t\tDividendPerShare={dividend_per_share}\n"
            f"\t\tEPS={eps}\n"
            f"\t\tPayoutRatio={payout_ratio}"
        )
        # -----------------------------------------------------
        # BUILD DOCUMENT
        # -----------------------------------------------------

        document = {

            # identity
            "ticker": ticker,
            "date": today,

            # dividend metrics
            "dividend_per_share": dividend_per_share,          
            
            "dividend_yield": safe_float(
                data.get("DividendYield")
            ),

           "payout_ratio": payout_ratio,
           
            # risk metrics
            "beta": safe_float(
                data.get("Beta")
            ),

            # earnings
            "eps": eps,

            # valuation
            "pe_ratio": safe_float(
                data.get("PERatio")
            ),

            # metadata
            "sector": data.get("Sector"),
            "industry": data.get("Industry"),

            # bookkeeping
            "source": "alphavantage",
            "created_at": datetime.utcnow()
        }

        # -----------------------------------------------------
        # INSERT
        # -----------------------------------------------------

        result = collection.insert_one(document)
        total_inserted += 1
        
        
        logging.info(f"Inserted {ticker}")
        logging.info(f"Mongo ID: {result.inserted_id}")

    except Exception as e:

        logging.error(f"ERROR processing {ticker}")

        logging.error(e)

    finally:

        # -----------------------------------------------------
        # API THROTTLE PROTECTION
        # -----------------------------------------------------

        if should_sleep:
            logging.info(f"Sleeping for {THROTTLE_SECONDS} seconds...\n")
            time.sleep(THROTTLE_SECONDS)
        else:
            break

logging.info("")
logging.info("===================================")
logging.info(f"Tickers inserted: {total_inserted}")
logging.info("NIGHTLY COLLECTION COMPLETE")
logging.info("===================================")