from datetime import datetime, timedelta

from models.mongo import get_collection
#from models.database import (
#    get_collection
#)

from models.constants import (
    DIVIDEND_HISTORY_COLLECTION,
    FREE_CASH_FLOW_COLLECTION
)

dividend_history = get_collection(
    DIVIDEND_HISTORY_COLLECTION
)

free_cash_flow_metrics = get_collection(
    FREE_CASH_FLOW_COLLECTION
)

def get_recent_dividends(ticker, limit=8, valid_only=True):
    """
    valid_only=True (default) excludes records tagged "suspect"
    (magnitude jump that looks wrong) or "distribution" (spinoff /
    special distribution masquerading as a dividend) by
    save_dividend_history.py. Cut detection, growth detection, and
    annual-dividends-paid should all be computed from real cash
    dividends only - a spinoff payout showing up as a "cut" or a
    "raise" would be a false signal either way.
    """

    query = {"ticker": ticker}

    if valid_only:
        query["validation_status"] = "valid"

    dividends = dividend_history.find(
        query
    ).sort(
        "ex_dividend_date",
        -1
    ).limit(limit)

    return list(dividends)
    
def get_latest_dividend(ticker):

    dividends = get_recent_dividends(
        ticker,
        limit=1
    )

    if not dividends:
        return None

    return dividends[0]
        
# =========================================
# Dividend Cut Detection
# =========================================

def dividend_cut_detected(dividends):

    if len(dividends) < 2:
        return False

    previous = None

    for dividend in reversed(dividends):

        amount = float(
            dividend.get(
                "amount",
                0
            )
        )

        if previous is not None:

            if amount < previous:
                return True

        previous = amount

    return False

# =========================================
# Dividend Growth Detection
# =========================================

def dividend_growth_positive(dividends):

    if len(dividends) < 4:
        return False

    newest = float(
        dividends[0].get(
            "amount",
            0
        )
    )

    oldest = float(
        dividends[-1].get(
            "amount",
            0
        )
    )

    return newest >= oldest
    
    
#---- presentation layer   
def get_latest_ex_dividend_date(ticker):

    dividends = get_recent_dividends(
        ticker,
        limit=1
    )

    if not dividends:
        return "N/A"

    ex_date = dividends[0].get(
        "ex_dividend_date"
    )

    if not ex_date:
        return "N/A"

    return ex_date.strftime(
        "%Y-%m-%d"
    )
  
# -----------------------------------------------------
# INPUT:
#   daily_metrics document
#
# PURPOSE:
#   Determine if this stock is a REIT
#
# RETURNS:
#   True  -> REIT
#   False -> not a REIT
# -----------------------------------------------------

def is_reit(daily_metrics):

    industry = (
        daily_metrics.get("industry", "")
        .upper().strip()
    )

    return "REIT" in industry
    
    
    
def get_latest_ttm_free_cash_flow(
    ticker
):

    records = list(

        free_cash_flow_metrics.find(
            {
                "ticker": ticker
            }
        ).sort(
            "fiscal_date",
            -1
        ).limit(4)
    )

    if not records:

        return None

    values = [

        r.get(
            "free_cash_flow"
        )

        for r in records

        if r.get(
            "free_cash_flow"
        ) is not None
    ]

    return (
        sum(values)
        if values
        else None
    )

def calc_reit_payout_ratio(
    annual_dividends_paid,
    ttm_free_cash_flow,
    shares_outstanding
):
    """
    annual_dividends_paid is PER SHARE (summed from dividend_history,
    where "amount" is always a per-share dollar figure).
    ttm_free_cash_flow is TOTAL company-wide dollars (summed from
    the free_cash_flow_metrics collection, which stores whole-company
    figures). Those can't be divided directly - shares_outstanding
    converts ttm_free_cash_flow into a per-share figure first so
    both sides of the ratio are in the same units.
    """

    if (
        annual_dividends_paid is None
        or ttm_free_cash_flow is None
        or shares_outstanding is None
    ):
        return None

    if ttm_free_cash_flow <= 0:
        return None

    if shares_outstanding <= 0:
        return None

    fcf_per_share = (
        ttm_free_cash_flow /
        shares_outstanding
    )

    if fcf_per_share <= 0:
        return None

    return (
        annual_dividends_paid /
        fcf_per_share
    )

def calc_standard_payout_ratio(
    dividend_per_share,
    eps
):

    if dividend_per_share is None:
        return None

    if eps is None:
        return None

    if eps <= 0:
        return None

    return (
        dividend_per_share /
        eps
    )                    
                    
# Get the trailing twelve months of dividends paid, per share.
# Uses a date window rather than a fixed record count (e.g. "last
# 4") because that assumes quarterly payments - a monthly payer
# like O (Realty Income) would only get ~4 months counted instead
# of a true annual total. A ~370 day window covers a full year
# for any payment frequency, with a small buffer for date drift.
def get_annual_dividends_paid(
    ticker
):

    cutoff = (
        datetime.utcnow() -
        timedelta(days=370)
    )

    dividends = list(
        dividend_history.find(
            {
                "ticker": ticker,
                "validation_status": "valid",
                "ex_dividend_date": {
                    "$gte": cutoff
                }
            }
        )
    )

    if not dividends:

        return None

    total = sum(

        dividend.get(
            "amount",
            0
        )

        for dividend in dividends
    )

    return round(
        total,
        4
    )    