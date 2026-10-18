"""
Nightly metric collection WITHOUT the Alpha Vantage OVERVIEW endpoint.

Replaced the OVERVIEW-based version of this collector after OVERVIEW began
returning a "premium endpoint" message on free API keys (2026-10-06).

Where each field now comes from:

    price, price_date      GLOBAL_QUOTE (one API call per ticker)
    dividend_per_share     sum of the last year's payments in dividend_history
    dividend_yield         dividend_per_share / price
    eps                    last four quarters of netIncome in income_statements
                           (loaded by the Monday collector) divided by
                           shares_outstanding; falls back to the last stored
                           eps if that can't be computed ("eps_source" says
                           which was used)
    pe_ratio               price / eps
    payout_ratio           calc_standard_payout_ratio(dividend_per_share, eps)
    beta,                  carried forward from the ticker's most recent
    shares_outstanding,    daily metrics document; "fundamentals_as_of"
    sector, industry       records the date those values were last real

Note: eps here is net income / shares outstanding. OVERVIEW reported diluted
EPS, which uses a slightly larger share count, so this figure runs a little
higher (about 2% for ADP) than the OVERVIEW values in older documents.

Usage:

    python -m collectors.save_daily_metrics                 all tickers
    python -m collectors.save_daily_metrics ADP KO          only these
    python -m collectors.save_daily_metrics --dry-run ADP   print, no insert
"""

from datetime import datetime
from statistics import median
import sys
import requests
import time
import logging
from utilities.logger import setup_logger

from models.mongo import get_collection
from models.settings import get_api_key
from models.utils import safe_float, now_local, today_local
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

# =========================================================
# Command line
# =========================================================

args = sys.argv[1:]
DRY_RUN = "--dry-run" in args
requested_tickers = [a.upper() for a in args if not a.startswith("--")]
tickers = requested_tickers or STOCK_TICKERS

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

collection = get_collection(DAILY_METRICS_COLLECTION)
dividend_history = get_collection("dividend_history")
income_statements = get_collection("income_statements")

# =========================================================
# HELPERS
# =========================================================

def get_quote(ticker):
    """
    Pull GLOBAL_QUOTE from Alpha Vantage.

    Returns a dict with price and price_date, a status string
    ("LIMIT_REACHED" / "API_MESSAGE") if the API refused the call,
    or None if this one ticker should be skipped.
    """

    url = (
        "https://www.alphavantage.co/query"
        f"?function=GLOBAL_QUOTE"
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

    quote = data.get("Global Quote") or {}
    price = safe_float(quote.get("05. price"))

    if not price:
        logging.warning(f"No price returned for {ticker}")
        return None

    return {
        "price": price,
        "price_date": quote.get("07. latest trading day")
    }


def get_annual_dividend(ticker):
    """
    Trailing one-year dividend per share from dividend_history.

    Works out how many payments the ticker makes per year from the
    typical gap between its recent ex-dividend dates, then adds up
    that many of the most recent payments. Counting payments (rather
    than using a fixed 365-day window) avoids picking up 3 or 5
    quarterly payments when an ex-date shifts by a few days.
    """

    payments = list(
        dividend_history.find({
            "ticker": ticker,
            "amount": {"$gt": 0},
            "validation_status": {"$in": ["valid", None]}
        })
        .sort("ex_dividend_date", -1)
        .limit(15)
    )

    if len(payments) < 2:
        logging.warning(f"{ticker}: not enough dividend history")
        return None

    dates = [p["ex_dividend_date"] for p in payments]
    gaps = [(dates[i] - dates[i + 1]).days for i in range(len(dates) - 1)]
    typical_gap = median(gaps)

    if typical_gap < 45:
        per_year = 12
    elif typical_gap < 135:
        per_year = 4
    elif typical_gap < 270:
        per_year = 2
    else:
        per_year = 1

    if len(payments) < per_year:
        logging.warning(f"{ticker}: fewer than {per_year} payments on file")
        return None

    days_since_last = (now_local() - dates[0]).days

    if days_since_last > typical_gap * 2:
        logging.warning(
            f"{ticker}: last ex-dividend date was {days_since_last} days "
            f"ago (typical gap {typical_gap}) - dividend_history may be "
            f"stale or the dividend may have been suspended"
        )

    return round(sum(p["amount"] for p in payments[:per_year]), 4)


def get_ttm_eps(ticker, shares_outstanding):
    """
    Trailing-twelve-month EPS from the income_statements collection.

    Adds up netIncome for the four most recent quarters and divides by
    shares outstanding. Returns (eps, last_fiscal_date), or (None, None)
    if the data isn't there or the four quarters don't form one
    continuous year.
    """

    if not shares_outstanding:
        return None, None

    statement = income_statements.find_one({"ticker": ticker})

    if not statement:
        logging.warning(f"{ticker}: no income statement on file")
        return None, None

    quarters = [
        q for q in (statement.get("quarterly_reports") or [])
        if q.get("fiscalDateEnding") is not None
        and q.get("netIncome") is not None
    ]

    quarters.sort(key=lambda q: q["fiscalDateEnding"], reverse=True)
    latest_four = quarters[:4]

    if len(latest_four) < 4:
        logging.warning(f"{ticker}: fewer than 4 quarters of net income")
        return None, None

    newest = latest_four[0]["fiscalDateEnding"]
    oldest = latest_four[3]["fiscalDateEnding"]
    span_days = (newest - oldest).days

    # four consecutive quarters span roughly nine months end to end
    if not 240 <= span_days <= 310:
        logging.warning(
            f"{ticker}: latest 4 quarters span {span_days} days - "
            f"a quarter looks missing, not computing EPS"
        )
        return None, None

    age_days = (now_local() - newest).days

    if age_days > 200:
        logging.warning(
            f"{ticker}: newest quarter on file ended {age_days} days ago"
        )

    ttm_net_income = sum(q["netIncome"] for q in latest_four)

    return round(ttm_net_income / shares_outstanding, 2), newest


def get_last_fundamentals(ticker):
    """
    Most recent daily metrics document that has an EPS value.
    """

    return collection.find_one(
        {"ticker": ticker, "eps": {"$ne": None}},
        sort=[("date", -1)]
    )


# =========================================================
# MAIN
# =========================================================

logging.info("===================================")
logging.info("STARTING NIGHTLY METRIC COLLECTION")
logging.info("===================================")

if DRY_RUN:
    logging.info("DRY RUN - nothing will be inserted")

today = today_local()

logging.info(f"Local today bucket: {today}")

total_inserted = 0

for ticker in tickers:

    logging.info(f"Processing {ticker}...")

    called_api = False

    try:
        # -----------------------------------------------------
        # Prevent duplicate inserts
        # -----------------------------------------------------

        existing = collection.find_one({
            "ticker": ticker,
            "date": today
        })

        if existing and not DRY_RUN:
            logging.warning(f"{ticker} already exists for today.")
            continue

        # -----------------------------------------------------
        # API CALL
        # -----------------------------------------------------

        called_api = True
        quote = get_quote(ticker)

        # Any refusal (rate limit, premium message) applies to every
        # ticker, so stop rather than burn the rest of the daily calls.
        if isinstance(quote, str):
            logging.error(f"Stopping script: API returned {quote}")
            called_api = False
            break

        if not quote:
            logging.warning(f"Skipping {ticker}")
            continue

        price = quote["price"]

        # -----------------------------------------------------
        # DIVIDENDS (from our own history)
        # -----------------------------------------------------

        dividend_per_share = get_annual_dividend(ticker)

        dividend_yield = None

        if dividend_per_share is not None:
            dividend_yield = round(dividend_per_share / price, 4)

        # -----------------------------------------------------
        # FUNDAMENTALS (carried forward)
        # -----------------------------------------------------

        previous = get_last_fundamentals(ticker) or {}

        if not previous:
            logging.warning(f"{ticker}: no earlier metrics to carry forward")

        shares_outstanding = previous.get("shares_outstanding")

        fundamentals_as_of = (
            previous.get("fundamentals_as_of") or previous.get("date")
        )

        # -----------------------------------------------------
        # EPS (from stored income statements, else carried forward)
        # -----------------------------------------------------

        eps, eps_through = get_ttm_eps(ticker, shares_outstanding)
        eps_source = "income_statements"

        if eps is None:
            eps = previous.get("eps")
            eps_through = previous.get("eps_through")
            eps_source = "carried_forward"

        pe_ratio = None

        if eps and eps > 0:
            pe_ratio = round(price / eps, 2)

        payout_ratio = None

        if dividend_per_share is not None and eps is not None:
            payout_ratio = calc_standard_payout_ratio(
                dividend_per_share,
                eps
            )

        logging.info(
            f"\tPrice={price}\n"
            f"\t\t\t\tDividendPerShare={dividend_per_share}\n"
            f"\t\t\t\tEPS={eps} ({eps_source}, through {eps_through})\n"
            f"\t\t\t\tPayoutRatio={payout_ratio}"
        )

        # -----------------------------------------------------
        # BUILD DOCUMENT
        # -----------------------------------------------------

        document = {

            # identity
            "ticker": ticker,
            "date": today,

            # price (new - OVERVIEW never supplied this)
            "price": price,
            "price_date": quote["price_date"],

            # dividend metrics
            "dividend_per_share": dividend_per_share,
            "dividend_yield": dividend_yield,
            "payout_ratio": payout_ratio,

            # risk metrics
            "beta": previous.get("beta"),

            # earnings
            "eps": eps,
            "eps_source": eps_source,
            "eps_through": eps_through,

            # valuation
            "pe_ratio": pe_ratio,

            # shares outstanding
            "shares_outstanding": shares_outstanding,

            # metadata
            "sector": previous.get("sector"),
            "industry": previous.get("industry"),

            # bookkeeping
            "source": "alphavantage",
            "method": "quote_plus_carry_forward",
            "fundamentals_as_of": fundamentals_as_of,
            "created_at": now_local()
        }

        # -----------------------------------------------------
        # INSERT
        # -----------------------------------------------------

        if DRY_RUN:
            logging.info(f"DRY RUN document for {ticker}:\n{document}")
        else:
            collection.insert_one(document)
            total_inserted += 1

    except Exception as e:

        logging.error(f"ERROR processing {ticker}")

        logging.error(e)

    finally:

        # -----------------------------------------------------
        # API THROTTLE PROTECTION (only after a real API call)
        # -----------------------------------------------------

        if called_api:
            time.sleep(THROTTLE_SECONDS)

logging.info("")
logging.info("===================================")
logging.info(f"Tickers inserted: {total_inserted}")
logging.info("NIGHTLY COLLECTION COMPLETE")
logging.info("===================================")
