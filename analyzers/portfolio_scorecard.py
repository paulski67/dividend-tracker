"""
portfolio_scorecard.py

Build a simple portfolio scorecard from the latest
weekly dividend safety scores.
"""
import logging
from datetime import datetime

from utilities.logger import setup_logger
from utilities.dividend_helper import (
    get_latest_ex_dividend_date
)

from models.mongo import get_collection
from models.api_utils import verify_database_connection
from models.utils import get_timestamped_file
from models.constants import (
    STOCK_TICKERS,
    WEEKLY_SCORES_COLLECTION,
    PORTFOLIO_SCORECARD_COLLECTION
)

setup_logger()

logging.info("===================================")
logging.info("PORTFOLIO SCORECARD")
logging.info("===================================")

# =========================================
# Check Mongo DB is up
# =========================================
if not verify_database_connection():
    sys.exit(1)

# -----------------------------------------------------
# COLLECTIONS
# -----------------------------------------------------

weekly_scores = get_collection(
    WEEKLY_SCORES_COLLECTION
)

scorecards = get_collection(
    PORTFOLIO_SCORECARD_COLLECTION
)

scorecard_results = []

# -----------------------------------------------------
# PROCESS
# -----------------------------------------------------

for ticker in STOCK_TICKERS:

    latest_score = weekly_scores.find_one(
        {"ticker": ticker},
        sort=[("created_at", -1)]
    )

    if not latest_score:

        logging.warning(
            f"No weekly score found for {ticker}"
        )

        continue

    score = latest_score.get("score", 0)

    if score >= 90:
        grade = "A"

    elif score >= 80:
        grade = "B"

    elif score >= 70:
        grade = "C"

    elif score >= 60:
        grade = "D"

    else:
        grade = "F"

    document = {

        "ticker": ticker,

        "score": score,

        "grade": grade,

        "status": latest_score.get("status"),

        "warnings": latest_score.get(
            "warnings",
            []
        ),

        "created_at": datetime.utcnow()
    }

    scorecards.replace_one(
        {"ticker": ticker},
        document,
        upsert=True
    )

    logging.info(
        f"{ticker} | "
        f"Score={score} | "
        f"Grade={grade}"
    )
    
    # save this ticker
    scorecard_results.append(
        {
            "ticker": ticker,
            "score": score,
            "grade": grade
        }
    )

# -----------------------------------------------------
# WRITE THE REPORT
# -----------------------------------------------------
report_file = get_timestamped_file(
"reports",
"portfolio_scorecard"
)

with open(report_file, "w") as report:

    report.write("===================================\n")
    report.write("PORTFOLIO SCORECARD\n")
    report.write("===================================\n")

    for result in scorecard_results:

        last_ex_date = get_latest_ex_dividend_date(
            ticker
        )

        report.write(
            f"{result['ticker']} | "
            f"Score={result['score']} | "
            f"Grade={result['grade']} | "
            f"Last Ex-Date={last_ex_date}\n"
        )

logging.info(f"Report written to {report_file}")
    



        
logging.info("")
logging.info("===================================")
logging.info("SCORECARD COMPLETE")
logging.info("===================================")