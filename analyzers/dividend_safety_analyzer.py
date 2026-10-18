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
    get_dividend_growth_1y,
    is_bank,
    get_ttm_cash_flow
)
from models.mongo import get_collection
from models.utils import safe_float, now_local
from models.api_utils import verify_database_connection
from models.settings import (
    get_max_payout_ratio,
    get_max_beta,
    get_min_dividend_growth
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

# --dry-run scores and logs every ticker but saves nothing
DRY_RUN = "--dry-run" in sys.argv[1:]


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

MIN_DIVIDEND_GROWTH = (get_min_dividend_growth())

# Dividends paid / free cash flow, both trailing four quarters
MAX_FCF_PAYOUT_RATIO = 1.0

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
    # Free Cash Flow (trailing twelve months)
    # -------------------------------------
    # Computed once here, ahead of the REIT/non-REIT branch below,
    # so both the REIT payout ratio calc and the general negative-
    # FCF warning use the SAME trailing-4-quarter number - a single
    # lumpy quarter (common for REITs and utilities) shouldn't
    # flag "negative free cash flow" if the trailing year is
    # actually healthy.
    ttm_fcf = (
        get_latest_ttm_free_cash_flow(ticker)
    )

    # -------------------------------------
    # REIT Detection and Payout ratio
    # -------------------------------------    
    payout_ratio = None
    payout_ratio_method = None
    
    if is_reit(metrics):

        annual_dividends_paid = (
            get_annual_dividends_paid(ticker)
        )

        payout_ratio = (
            calc_reit_payout_ratio(
                annual_dividends_paid,
                ttm_fcf,
                metrics.get("shares_outstanding")
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
        metrics.get("dividend_yield", 0)
    )

    # Some valid equities have no dividend.
    # Treat missing dividend yield as zero.
    if dividend_yield is None:
        dividend_yield = 0.0

    # -------------------------------------
    # Free Cash Flow
    # -------------------------------------

    # -------------------------------------
    # Free Cash Flow warning
    # -------------------------------------
    # Uses the same ttm_fcf computed above (trailing 4 quarters),
    # not a single quarter - a company can have one lumpy negative
    # quarter (large capex, real estate purchase, etc) while its
    # trailing-year cash generation is perfectly healthy.
    #
    # Banks skip these checks - see is_bank().

    cash_flow = get_ttm_cash_flow(ticker)

    fcf_payout_ratio = None
    capex_to_ocf = None

    if cash_flow and cash_flow["operating_cash_flow"] > 0:

        capex_to_ocf = (
            cash_flow["capital_expenditures"] /
            cash_flow["operating_cash_flow"]
        )

    if is_bank(metrics):

        pass

    elif ttm_fcf is not None:

        if ttm_fcf <= 0:

            # Capex bigger than (positive) operating cash flow is a
            # building program - utilities, industrial gas - usually
            # debt-funded. Softer than operations burning cash.
            # Not for REITs: they pay out most of their cash by
            # design, so a REIT building past its cash flow is
            # borrowing to fund the dividend.
            if (
                not is_reit(metrics)
                and capex_to_ocf is not None
                and capex_to_ocf > 1
            ):

                score -= 10

                warnings.append(
                    "Negative free cash flow (capex-driven)"
                )

            else:

                score -= 25

                warnings.append(
                    "Negative free cash flow"
                )

        elif cash_flow:

            fcf_payout_ratio = (
                cash_flow["dividend_payout"] /
                ttm_fcf
            )

            # REITs already score their payout ratio on FCF above
            if (
                not is_reit(metrics)
                and fcf_payout_ratio > MAX_FCF_PAYOUT_RATIO
            ):

                score -= 15

                warnings.append(
                    "Dividends exceed free cash flow"
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

    dividend_growth_1y = get_dividend_growth_1y(
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

        cut = dividend_cut_detected(
            dividends
        )

        if cut:

            score -= 40

            warnings.append(
                "Dividend cut detected"
            )

        # ---------------------------------
        # Dividend Growth
        # ---------------------------------
        # Latest payment vs. the one a year earlier. Skipped after
        # a cut - the cut warning already covers it.

        if not cut and dividend_growth_1y is not None:

            if dividend_growth_1y <= 0:

                score -= 15

                warnings.append(
                    "Dividend frozen"
                )

            elif dividend_growth_1y < MIN_DIVIDEND_GROWTH:

                score -= 10

                warnings.append(
                    "Slow dividend growth"
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
        "dividend_growth_1y": dividend_growth_1y,
        "fcf_payout_ratio": fcf_payout_ratio,
        "capex_to_ocf": capex_to_ocf,
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
        "dividend_growth_1y": result.get("dividend_growth_1y"),
        "fcf_payout_ratio": result.get("fcf_payout_ratio"),
        "capex_to_ocf": result.get("capex_to_ocf"),
        "run_date": now_local()
    }

    if DRY_RUN:

        logging.info(
            f"DRY RUN - not saving weekly score for {ticker}"
        )

        continue

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