"""
Monthly price history and beta, run on the first Wednesday of each month.

Beta used to come from the OVERVIEW endpoint, which went premium on
2026-10-06. This collector replaces it by calculating beta the standard
way (the same method Yahoo and most brokers use): 5 years of monthly
returns for the stock against the S&P 500 (SPY).

    beta = covariance(stock returns, SPY returns) / variance(SPY returns)

One TIME_SERIES_MONTHLY_ADJUSTED call per ticker returns ~20 years of
month-end prices adjusted for splits and dividends, so the run costs
23 calls (22 tickers + SPY).

Writes:
    monthly_prices   one document per ticker per month ("month" = "YYYY-MM"),
                     upserted, so the current month's partial row is
                     replaced by the real month-end close next month
    beta_history     one document per ticker per run (append-only);
                     save_daily_metrics reads the newest one

The current, unfinished month is left out of the beta calculation.

Usage:

    python -m collectors.save_monthly_prices                 all tickers
    python -m collectors.save_monthly_prices KO TROW         only these (+ SPY)
    python -m collectors.save_monthly_prices --dry-run KO    print, save nothing
"""

import sys
import requests
import time
import logging
from utilities.logger import setup_logger

from models.mongo import get_collection
from models.settings import get_api_key
from models.utils import safe_float, now_local
from models.api_utils import verify_database_connection
from models.api_utils import check_api_response
from models.constants import (
    STOCK_TICKERS,
    MARKET_TICKER,
    DAILY_METRICS_COLLECTION,
    MONTHLY_PRICES_COLLECTION,
    BETA_COLLECTION,
    THROTTLE_SECONDS
)

# =========================================================
# Logging
# =========================================================

setup_logger()

# =========================================================
# Command line
# =========================================================

args = sys.argv[1:]
DRY_RUN = "--dry-run" in args
requested_tickers = [a.upper() for a in args if not a.startswith("--")]
tickers = requested_tickers or STOCK_TICKERS

# =========================================================
# Beta settings
# =========================================================

# 5 years of monthly returns
BETA_MONTHS = 60

# Too short a history makes beta meaningless (recent listings)
MIN_BETA_MONTHS = 36

# =========================================
# Check Mongo DB is up
# =========================================

if not verify_database_connection():
    sys.exit(1)

# =========================================
# API Key
# =========================================

API_KEY = get_api_key()

# =========================================================
# MONGODB CONNECTION
# =========================================================

monthly_prices = get_collection(MONTHLY_PRICES_COLLECTION)
beta_history = get_collection(BETA_COLLECTION)
daily_metrics = get_collection(DAILY_METRICS_COLLECTION)

# =========================================================
# HELPERS
# =========================================================

def get_monthly_series(ticker):
    """
    Pull TIME_SERIES_MONTHLY_ADJUSTED from Alpha Vantage.

    Returns {"YYYY-MM": {...month row...}} sorted oldest first, a
    status string ("LIMIT_REACHED" / "API_MESSAGE") if the API refused
    the call, or None if this one ticker should be skipped.
    """

    url = (
        "https://www.alphavantage.co/query"
        f"?function=TIME_SERIES_MONTHLY_ADJUSTED"
        f"&symbol={ticker}"
        f"&apikey={API_KEY}"
    )

    response = requests.get(url, timeout=30)

    if response.status_code != 200:
        logging.error(f"HTTP ERROR for {ticker}: {response.status_code}")
        return None

    data = response.json()

    # check_api_response only looks at "Note" / "Information"
    if "Error Message" in data:
        logging.error(f"API ERROR for {ticker}: {data['Error Message']}")
        return None

    status = check_api_response(data)

    if status != "OK":
        return status

    series = data.get("Monthly Adjusted Time Series") or {}

    if not series:
        logging.warning(f"No monthly prices returned for {ticker}")
        return None

    months = {}

    for price_date, row in series.items():

        adjusted_close = safe_float(row.get("5. adjusted close"), None)

        if not adjusted_close:
            continue

        months[price_date[:7]] = {
            "price_date": price_date,
            "close": safe_float(row.get("4. close"), None),
            "adjusted_close": adjusted_close,
            "dividend": safe_float(row.get("7. dividend amount"), 0.0)
        }

    return dict(sorted(months.items()))


def monthly_returns(months, current_month):
    """
    {"YYYY-MM": return} from one month-end to the next, skipping the
    unfinished current month.
    """

    keys = [m for m in months if m < current_month]

    returns = {}

    for previous, month in zip(keys, keys[1:]):

        returns[month] = (
            months[month]["adjusted_close"] /
            months[previous]["adjusted_close"]
        ) - 1

    return returns


def calc_beta(stock_returns, market_returns):
    """
    Beta over the most recent BETA_MONTHS months both series share.
    Returns (beta, months_used, last_month), or (None, months, None)
    if the shared history is shorter than MIN_BETA_MONTHS.
    """

    shared = sorted(set(stock_returns) & set(market_returns))
    shared = shared[-BETA_MONTHS:]

    if len(shared) < MIN_BETA_MONTHS:
        return None, len(shared), None

    stock = [stock_returns[m] for m in shared]
    market = [market_returns[m] for m in shared]

    stock_mean = sum(stock) / len(stock)
    market_mean = sum(market) / len(market)

    covariance = sum(
        (s - stock_mean) * (m - market_mean)
        for s, m in zip(stock, market)
    )

    variance = sum(
        (m - market_mean) ** 2
        for m in market
    )

    if variance == 0:
        return None, len(shared), None

    return round(covariance / variance, 2), len(shared), shared[-1]


def save_months(ticker, months):

    for month, row in months.items():

        monthly_prices.update_one(
            {
                "ticker": ticker,
                "month": month
            },
            {
                "$set": {
                    **row,
                    "ticker": ticker,
                    "month": month,
                    "updated_at": now_local()
                },
                "$setOnInsert": {
                    "created_at": now_local()
                }
            },
            upsert=True
        )


def last_overview_beta(ticker):
    """
    The beta carried forward in daily_metrics, for comparison.
    """

    latest = daily_metrics.find_one(
        {"ticker": ticker, "beta": {"$ne": None}},
        sort=[("date", -1)]
    )

    return latest.get("beta") if latest else None


# =========================================================
# MAIN
# =========================================================

logging.info("===================================")
logging.info("STARTING MONTHLY PRICES / BETA")
logging.info("===================================")

if DRY_RUN:
    logging.info("DRY RUN - nothing will be saved")

current_month = now_local().strftime("%Y-%m")

series_by_ticker = {}

# SPY first: without the market series no beta can be calculated
for ticker in [MARKET_TICKER] + [t for t in tickers if t != MARKET_TICKER]:

    logging.info(f"Processing {ticker}...")

    called_api = False

    try:

        called_api = True
        months = get_monthly_series(ticker)

        # Any refusal (rate limit, premium message) applies to every
        # ticker, so stop rather than burn the rest of the daily calls.
        if isinstance(months, str):
            logging.error(f"Stopping script: API returned {months}")
            called_api = False
            break

        if not months:
            logging.warning(f"Skipping {ticker}")
            continue

        series_by_ticker[ticker] = months

        logging.info(
            f"{ticker}: {len(months)} months, "
            f"{min(months)} to {max(months)}"
        )

        if not DRY_RUN:
            save_months(ticker, months)

    except Exception as e:

        logging.error(f"ERROR processing {ticker}")

        logging.error(e)

    finally:

        # -----------------------------------------------------
        # API THROTTLE PROTECTION (only after a real API call)
        # -----------------------------------------------------

        if called_api:
            time.sleep(THROTTLE_SECONDS)

# =========================================================
# BETA
# =========================================================

total_saved = 0

if MARKET_TICKER not in series_by_ticker:

    logging.error(
        f"No {MARKET_TICKER} prices - cannot calculate beta this run"
    )

else:

    market_returns = monthly_returns(
        series_by_ticker[MARKET_TICKER],
        current_month
    )

    for ticker in tickers:

        if ticker == MARKET_TICKER or ticker not in series_by_ticker:
            continue

        beta, months_used, through = calc_beta(
            monthly_returns(series_by_ticker[ticker], current_month),
            market_returns
        )

        if beta is None:
            logging.warning(
                f"{ticker}: only {months_used} months of shared "
                f"history - no beta"
            )
            continue

        logging.info(
            f"{ticker}: beta={beta} over {months_used} months "
            f"through {through} (last carried-forward beta: "
            f"{last_overview_beta(ticker)})"
        )

        if DRY_RUN:
            continue

        beta_history.insert_one({
            "ticker": ticker,
            "beta": beta,
            "months_used": months_used,
            "through_month": through,
            "market_ticker": MARKET_TICKER,
            "created_at": now_local()
        })

        total_saved += 1

logging.info("")
logging.info("===================================")
logging.info(f"Betas saved: {total_saved}")
logging.info("MONTHLY PRICES / BETA COMPLETE")
logging.info("===================================")
