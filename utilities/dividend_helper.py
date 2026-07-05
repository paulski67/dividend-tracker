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

def get_recent_dividends(ticker, limit=8):

    dividends = dividend_history.find(
        {"ticker": ticker}
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
                "dividend_amount",
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
            "dividend_amount",
            0
        )
    )

    oldest = float(
        dividends[-1].get(
            "dividend_amount",
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
    ttm_free_cash_flow
):

    if (
        annual_dividends_paid is None
        or ttm_free_cash_flow is None
    ):
        return None

    if ttm_free_cash_flow <= 0:
        return None

    return (
        annual_dividends_paid /
        ttm_free_cash_flow
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
                    
# Get the last 4 quarters of dividends
# input is the ticker   
def get_annual_dividends_paid(
    ticker,
    limit=4
):

    dividends = (
        get_recent_dividends(
            ticker,
            limit
        )
    )

    if not dividends:

        return None

    total = sum(

        dividend.get(
            "dividend_amount",
            0
        )

        for dividend in dividends
    )

    return round(
        total,
        4
    )    