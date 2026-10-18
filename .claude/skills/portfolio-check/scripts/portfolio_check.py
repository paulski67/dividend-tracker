"""
portfolio_check.py  -  read-only status report for the dividend tracker.

Run from the project root (where config/config.ini lives):

    .venv\\Scripts\\python.exe .claude\\skills\\portfolio-check\\scripts\\portfolio_check.py

Options:
    --days N        how many days of log files to scan (default 7)
    --pretty        indent the JSON output

Prints one JSON document to stdout with three sections:
    pipeline   - did each collector/analyzer write fresh data for every ticker?
    portfolio  - latest safety scores, score changes, warnings, upcoming payouts
    logs       - ERROR and API-message lines from recent pipeline logs

It never writes to MongoDB, never calls Alpha Vantage, and uses no API key.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

# Make the project's own packages (models/...) importable when this file
# is run by path from the project root.
sys.path.insert(0, os.getcwd())

try:
    from models.mongo import get_collection, get_mongo_client
    from models.utils import now_local
    from models.constants import (
        STOCK_TICKERS,
        DAILY_METRICS_COLLECTION,
        DIVIDEND_HISTORY_COLLECTION,
        INCOME_STATEMENTS_COLLECTION,
        FREE_CASH_FLOW_COLLECTION,
        WEEKLY_SCORES_COLLECTION,
        PORTFOLIO_SCORECARD_COLLECTION,
    )
except Exception as exc:  # wrong folder, missing config, etc.
    print(json.dumps({
        "overall": "FAIL",
        "error": f"Could not load project modules: {exc!r}. "
                 "Run this from the dividend-tracker project root "
                 "with the project's .venv python."
    }))
    sys.exit(2)


# ---------------------------------------------------------------------
# What each collection is, who writes it, and how stale is too stale.
# max_age_days = schedule gap + 1 day of grace.
# ---------------------------------------------------------------------

PIPELINE = [
    {
        "collection": INCOME_STATEMENTS_COLLECTION,
        "writer": "collectors.save_income_statements",
        "schedule": "Monday",
        "time_field": "last_updated",
        "max_age_days": 8,
    },
    {
        "collection": DAILY_METRICS_COLLECTION,
        "writer": "collectors.save_daily_metrics",
        "schedule": "Tue/Wed/Thu",
        "time_field": "created_at",
        "max_age_days": 5,
    },
    {
        "collection": DIVIDEND_HISTORY_COLLECTION,
        "writer": "collectors.save_dividend_history",
        "schedule": "Friday",
        "time_field": "updated_at",
        "max_age_days": 8,
    },
    {
        "collection": FREE_CASH_FLOW_COLLECTION,
        "writer": "collectors.save_free_cash_flow",
        "schedule": "Saturday",
        "time_field": "updated_at",
        "max_age_days": 8,
    },
    {
        "collection": WEEKLY_SCORES_COLLECTION,
        "writer": "analyzers.dividend_safety_analyzer",
        "schedule": "Sunday",
        "time_field": "run_date",
        "max_age_days": 8,
    },
    {
        "collection": PORTFOLIO_SCORECARD_COLLECTION,
        "writer": "analyzers.portfolio_scorecard",
        "schedule": "Sunday",
        "time_field": "created_at",
        "max_age_days": 8,
    },
]

UPCOMING_PAYOUT_DAYS = 45


def iso(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M ET")
    return value


def days_old(when, now):
    if not isinstance(when, datetime):
        return None
    return round((now - when).total_seconds() / 86400, 1)


# ---------------------------------------------------------------------
# Pipeline freshness
# ---------------------------------------------------------------------

def check_collection(spec, now):
    coll = get_collection(spec["collection"])
    field = spec["time_field"]

    # Newest write per ticker. Fall back to created_at when the
    # preferred field is missing on older documents.
    rows = coll.aggregate([
        {"$group": {
            "_id": "$ticker",
            "newest": {"$max": {"$ifNull": [f"${field}", "$created_at"]}},
            "docs": {"$sum": 1},
        }}
    ])
    per_ticker = {r["_id"]: r for r in rows}

    missing = [t for t in STOCK_TICKERS if t not in per_ticker]
    stale = []
    newest_overall = None

    for t in STOCK_TICKERS:
        row = per_ticker.get(t)
        if not row:
            continue
        newest = row["newest"]
        if isinstance(newest, datetime):
            if newest_overall is None or newest > newest_overall:
                newest_overall = newest
            age = days_old(newest, now)
            if age is not None and age > spec["max_age_days"]:
                stale.append({"ticker": t, "last_write": iso(newest), "days_old": age})

    extra = sorted(t for t in per_ticker if t not in STOCK_TICKERS and t is not None)
    age = days_old(newest_overall, now)

    behind = len(missing) + len(stale)

    if newest_overall is None or age > spec["max_age_days"] or behind > len(STOCK_TICKERS) / 2:
        status = "FAIL"
    elif missing or stale:
        status = "WARN"
    else:
        status = "OK"

    return {
        "collection": spec["collection"],
        "writer": spec["writer"],
        "schedule": spec["schedule"],
        "status": status,
        "last_write": iso(newest_overall),
        "days_since_last_write": age,
        "max_age_days": spec["max_age_days"],
        "tickers_expected": len(STOCK_TICKERS),
        "tickers_missing": missing,
        "tickers_stale": stale,
        "tickers_not_in_watchlist": extra,
        "total_docs": coll.estimated_document_count(),
    }


def daily_metrics_details(now):
    """Latest date bucket: how many tickers made it, how old the
    carried-forward fundamentals are (OVERVIEW went premium)."""
    coll = get_collection(DAILY_METRICS_COLLECTION)
    latest = coll.find_one({}, sort=[("date", -1)])
    if not latest:
        return {}
    bucket = latest["date"]
    docs = list(coll.find({"date": bucket}))
    got = {d["ticker"] for d in docs}

    oldest_fundamentals = None
    for d in docs:
        f = d.get("fundamentals_as_of")
        if isinstance(f, datetime) and (oldest_fundamentals is None or f < oldest_fundamentals):
            oldest_fundamentals = f

    return {
        "latest_date_bucket": iso(bucket),
        "tickers_in_latest_bucket": len(got),
        "tickers_missing_from_latest_bucket": [t for t in STOCK_TICKERS if t not in got],
        "methods_in_latest_bucket": dict(Counter(d.get("method", "overview") for d in docs)),
        "oldest_fundamentals_as_of": iso(oldest_fundamentals),
        "fundamentals_days_old": days_old(oldest_fundamentals, now),
        "null_payout_ratio": sorted(d["ticker"] for d in docs if d.get("payout_ratio") is None),
        "null_eps": sorted(d["ticker"] for d in docs if d.get("eps") is None),
    }


def dividend_history_details():
    coll = get_collection(DIVIDEND_HISTORY_COLLECTION)
    counts = Counter()
    for row in coll.aggregate([{"$group": {"_id": "$validation_status", "n": {"$sum": 1}}}]):
        counts[str(row["_id"])] = row["n"]
    return {"validation_status_counts": dict(counts)}


# ---------------------------------------------------------------------
# Portfolio view
# ---------------------------------------------------------------------

def portfolio_section(now):
    scores = get_collection(WEEKLY_SCORES_COLLECTION)
    holdings = []
    data_quality = []

    for t in STOCK_TICKERS:
        last_two = list(scores.find({"ticker": t}).sort("run_date", -1).limit(2))
        if not last_two:
            holdings.append({"ticker": t, "status": "NO_SCORE"})
            continue
        cur = last_two[0]
        prev = last_two[1] if len(last_two) > 1 else None

        beta = cur.get("beta")
        if beta is not None and not isinstance(beta, (int, float)):
            data_quality.append(f"{t}: weekly_scores.beta is not a number ({beta!r})")

        holdings.append({
            "ticker": t,
            "score": cur.get("score"),
            "previous_score": prev.get("score") if prev else None,
            "score_change": (cur.get("score") - prev.get("score"))
                            if prev and isinstance(cur.get("score"), (int, float))
                            and isinstance(prev.get("score"), (int, float)) else None,
            "status": cur.get("status"),
            "previous_status": prev.get("status") if prev else None,
            "warnings": cur.get("warnings", []),
            "new_warnings": sorted(set(cur.get("warnings", [])) - set(prev.get("warnings", [])))
                            if prev else [],
            "payout_ratio": cur.get("payout_ratio"),
            "payout_ratio_method": cur.get("payout_ratio_method"),
            "dividend_yield": cur.get("dividend_yield"),
            "scored_at": iso(cur.get("run_date")),
        })

    holdings.sort(key=lambda h: (h.get("score") is None, h.get("score") or 0))

    cuts = [h["ticker"] for h in holdings if "Dividend cut detected" in h.get("warnings", [])]
    by_status = Counter(h.get("status") for h in holdings)

    # Declared payouts coming up (payment_date in the future)
    divs = get_collection(DIVIDEND_HISTORY_COLLECTION)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    upcoming = [
        {
            "ticker": d["ticker"],
            "amount": d.get("amount"),
            "ex_dividend_date": iso(d.get("ex_dividend_date"))[:10] if d.get("ex_dividend_date") else None,
            "payment_date": iso(d.get("payment_date"))[:10],
        }
        for d in divs.find({
            "ticker": {"$in": STOCK_TICKERS},
            "payment_date": {"$gte": today, "$lte": today + timedelta(days=UPCOMING_PAYOUT_DAYS)},
        }).sort("payment_date", 1)
    ]

    return {
        "dividend_cuts": cuts,
        "status_counts": dict(by_status),
        "holdings_worst_first": holdings,
        "upcoming_payouts": upcoming,
        "upcoming_window_days": UPCOMING_PAYOUT_DAYS,
        "data_quality": data_quality,
    }


# ---------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------

LOG_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}) [\d:,]+ (\w+) (.*)$")
INTERESTING = ("API MESSAGE", "API LIMIT", "Stopping script", "Health checks failed",
               "Tickers inserted: 0", "connection failed")


TICKER_RE = re.compile(r"\b(" + "|".join(map(re.escape, STOCK_TICKERS)) + r")\b")


def logs_section(days):
    log_dir = Path("logs")
    if not log_dir.is_dir():
        return {"scanned": False, "reason": "no logs/ folder in the current directory"}

    cutoff = datetime.now() - timedelta(days=days)
    files = [p for p in log_dir.iterdir()
             if p.is_file() and (p.name.startswith("pipeline.log") or p.name.startswith("run_pipeline_"))
             and datetime.fromtimestamp(p.stat().st_mtime) >= cutoff]

    hits = Counter()
    first_seen = {}
    for p in sorted(files):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = LOG_LINE.match(line.strip())
            day, level, msg = (m.group(1), m.group(2), m.group(3)) if m else (None, "", line.strip())
            if day and day < cutoff.strftime("%Y-%m-%d"):
                continue
            if level == "ERROR" or any(k in line for k in INTERESTING):
                # Swap watchlist tickers for <T> so identical problems group together
                key = TICKER_RE.sub("<T>", msg)[:200]
                hits[key] += 1
                first_seen.setdefault(key, day)

    return {
        "scanned": True,
        "days": days,
        "files_scanned": len(files),
        "problems": [
            {"message": k, "count": n, "first_seen": first_seen[k]}
            for k, n in hits.most_common(15)
        ],
    }


# ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    try:
        get_mongo_client().admin.command("ping")
    except Exception as exc:
        print(json.dumps({"overall": "FAIL", "error": f"MongoDB not reachable: {exc}"}))
        sys.exit(1)

    now = now_local()  # stored timestamps are naive Eastern time
    pipeline = [check_collection(spec, now) for spec in PIPELINE]
    for p in pipeline:
        if p["collection"] == DAILY_METRICS_COLLECTION:
            p["details"] = daily_metrics_details(now)
        elif p["collection"] == DIVIDEND_HISTORY_COLLECTION:
            p["details"] = dividend_history_details()

    statuses = {p["status"] for p in pipeline}
    overall = "FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses else "OK"

    report = {
        "generated_at": iso(now),
        "overall": overall,
        "watchlist_size": len(STOCK_TICKERS),
        "pipeline": pipeline,
        "portfolio": portfolio_section(now),
        "logs": logs_section(args.days),
    }
    if report["portfolio"]["dividend_cuts"] and overall == "OK":
        report["overall"] = "WARN"

    print(json.dumps(report, indent=2 if args.pretty else None, default=str))


if __name__ == "__main__":
    main()
