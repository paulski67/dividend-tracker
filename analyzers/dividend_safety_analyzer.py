import logging
from datetime import datetime
import sys
from utilities.logger import setup_logger
from utilities.dividend_helper import (
    is_reit,
    get_recent_dividends,
    dividend_cut_detected,
    get_annual_dividends_paid,
    get_latest_ttm_free_cash_flow,
    calc_standard_payout_ratio,
    calc_reit_payout_ratio,
    dividend_growth_positive
)
from models.mongo import get_collection
from models.utils import safe_float
from models.api_utils import verify_database_connection
from models.settings import (
    get_max_payout_ratio,
    get_max_beta
)
from models.constants import (
    DAILY_METRICS_COLLECTION,
    DIVIDEND_HISTORY_COLLECTION,
    FREE_CASH_FLOW_COLLECTION,
    WEEKLY_SCORES_COLLECTION,
    STOCK_TICKERS
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
# Mongo Collections
# =========================================

daily_metrics = get_collection(
    DAILY_METRICS_COLLECTION
)

dividend_history = get_collection(
    DIVIDEND_HISTORY_COLLECTION
)

free_cash_flow = get_collection(
    FREE_CASH_FLOW_COLLECTION
)

weekly_scores_collection = get_collection(
    WEEKLY_SCORES_COLLECTION
)
# =========================================
# Scoring Constants
# =========================================

MAX_SCORE = 100

CAUTION_PAYOUT_RATIO = (get_max_payout_ratio())

DANGER_PAYOUT_RATIO = (CAUTION_PAYOUT_RATIO + 0.20)

MAX_BETA = (get_max_beta())

# =========================================
# Helper Functions
# =========================================

def get_latest_daily_metrics(ticker):

    return daily_metrics.find_one(
        {
            "ticker": ticker
        },
        sort=[("date", -1)]
    )

# -----------------------------------------

def get_latest_fcf(ticker):

    return free_cash_flow.find_one(
        {
            "ticker": ticker
        },
        sort=[("fiscal_date", -1)]
    )

# =========================================
# Main Scoring Function
# =========================================

def calculate_score(ticker):

    score = 100

    warnings = []

    # -------------------------------------
    # Daily Metrics
    # -------------------------------------

    metrics = get_latest_daily_metrics(
        ticker
    )

    if not metrics:

        return {
            "ticker": ticker,
            "score": 0,
            "status": "ERROR",
            "warnings": [
                "No daily metrics found"
            ]
        }

    # -------------------------------------
    # REIT Detection and Payout ratio
    # -------------------------------------    
    payout_ratio = None
    payout_ratio_method = None
    
    if is_reit(metrics):

        annual_dividends_paid = (
            get_annual_dividends_paid(ticker)
        )

        ttm_fcf = (
            get_latest_ttm_free_cash_flow(ticker)
        )

        payout_ratio = (
            calc_reit_payout_ratio(
                annual_dividends_paid,
                ttm_fcf
            )
        )
        
        payout_ratio_method = "REIT_FCF"

        logging.info(
            f"{ticker}: REIT detected | "
            f"TTM FCF="
            f"{ttm_fcf}"
        )

    else:

        dividend_per_share = safe_float(
            metrics.get(
                "dividend_per_share",
                0
            )
        )

        eps = safe_float(
            metrics.get(
                "eps",
                0
            )
        )
        
        # this is temporary
        logging.info(
            f"{ticker}: "
            f"DPS={dividend_per_share} "
            f"EPS={eps}"
        )
        payout_ratio = (
            calc_standard_payout_ratio(
                dividend_per_share,
                eps
            )
        ) 
        
        payout_ratio_method = "EPS"
        
    logging.info(
        f"{ticker}: "
        f"payout_ratio="
        f"{payout_ratio} | "
        f"payout_ratio_method="
        f"{payout_ratio_method}"
    )

    if payout_ratio is None:
        warnings.append(
            "Missing payout ratio"
        )

        score -= 5

    elif payout_ratio > DANGER_PAYOUT_RATIO:

        score -= 25

        warnings.append(
            "High payout ratio"
        )

    elif payout_ratio > CAUTION_PAYOUT_RATIO:

        score -= 10

        warnings.append(
            "Moderate payout ratio"
        )

    # -------------------------------------
    # Beta
    # -------------------------------------

    beta = metrics.get(
        "beta",
        0
    )

    if beta > (MAX_BETA + 0.5):

        score -= 15

        warnings.append(
            "Extremely high beta"
        )

    elif beta > MAX_BETA:

        score -= 10

        warnings.append(
            "High beta"
        )

    # -------------------------------------
    # Dividend Yield
    # -------------------------------------
    dividend_yield = safe_float(
        metrics.get("DividendYield", 0)
    )

    # Some valid equities have no dividend.
    # Treat missing dividend yield as zero.
    if dividend_yield is None:
        dividend_yield = 0.0

    # -------------------------------------
    # Free Cash Flow
    # -------------------------------------

    latest_fcf = get_latest_fcf(
        ticker
    )

    if latest_fcf:

        fcf = latest_fcf.get(
            "free_cash_flow",
            0
        )

        if fcf <= 0:

            score -= 25

            warnings.append(
                "Negative free cash flow"
            )

    else:

        score -= 10

        warnings.append(
            "No free cash flow data"
        )

    # -------------------------------------
    # Dividend History
    # -------------------------------------

    dividends = get_recent_dividends(
        ticker
    )

    if not dividends:

        score -= 25

        warnings.append(
            "No dividend history"
        )

    else:

        # ---------------------------------
        # Dividend Cut
        # ---------------------------------

        if dividend_cut_detected(
            dividends
        ):

            score -= 40

            warnings.append(
                "Dividend cut detected"
            )

        # ---------------------------------
        # Dividend Growth
        # ---------------------------------

        if not dividend_growth_positive(
            dividends
        ):

            score -= 15

            warnings.append(
                "Dividend growth weak"
            )

    # -------------------------------------
    # Floor Score
    # -------------------------------------

    if score < 0:
        score = 0

    # -------------------------------------
    # Status
    # -------------------------------------

    if score >= 85:

        status = "HEALTHY"

    elif score >= 70:

        status = "CAUTION"

    else:

        status = "WARNING"

    # =========================================
    # temporary debug
    # =========================================
    logging.info(
        f"{ticker} | "
        f"Payout: {payout_ratio} | "
        f"Beta: {beta} | "
        f"Score: {score}"
    )

    return {
        "ticker": ticker,
        "dividend_yield": dividend_yield,
        "payout_ratio": payout_ratio,
        "payout_ratio_method": payout_ratio_method,
        "beta": beta,
        "score": score,
        "status": status,
        "warnings": warnings
    }

# =========================================
# Main Analyzer
# =========================================

logging.info("===================================")
logging.info("DIVIDEND SAFETY ANALYZER")
logging.info("===================================")

results = []

for ticker in STOCK_TICKERS:

    result = calculate_score(
        ticker
    )

    results.append(result)

    # =========================================
    # Sort By Score
    # =========================================

    results = sorted(
        results,
        key=lambda x: x["score"],
        reverse=True
    )

    # =========================================
    # Save Weekly Scores
    # =========================================
    score_document = {
        "ticker": ticker,
        "score": result["score"],
        "status": result["status"],
        "warnings": result["warnings"],
        "dividend_yield": result["dividend_yield"],
        "payout_ratio": result["payout_ratio"],
        "payout_ratio_method": result["payout_ratio_method"],
        "beta": result["beta"],
        "run_date": datetime.utcnow()
    }

    insert_result = weekly_scores_collection.insert_one(
        score_document
    )

    logging.info(
        f"Saved weekly score for {ticker}"
    )

# =========================================
# Print Results
# =========================================

for result in results:

    logging.info(
        f"-----[{result['ticker']}]-----"
    )

    logging.info(
        f"Score: {result['score']}"
    )

    logging.info(
        f"Status: {result['status']}"
    )

    if result["warnings"]:

        logging.info("Warnings:")

        for warning in result["warnings"]:

            logging.warning(f"- {warning}")

    else:

        logging.info(
            "No warnings detected"
        )
logging.info("")
logging.info("===================================")
logging.info("ANALYSIS COMPLETE")
logging.info("===================================")