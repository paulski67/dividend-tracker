---
name: portfolio-check
description: Status report for the dividend tracker - whether the nightly pipeline actually collected data, plus dividend cuts, score drops and upcoming payouts. Use when Paul asks how the portfolio is doing, whether the pipeline ran, for a health/status check, or what needs attention this week.
---

# Portfolio check

Produces a short status report on two things:

1. **Pipeline health** - did each collector and analyzer write fresh data for every ticker on its schedule? A collector can "succeed" while inserting nothing (this happened when Alpha Vantage moved OVERVIEW to premium), so this checks the data itself, not just exit codes.
2. **Portfolio** - dividend cuts (the sell signal), score drops, new warnings, and payouts coming up.

## Step 1 - run the check

From the project root (the folder containing `config/` and `models/`):

```
.venv\Scripts\python.exe .claude\skills\portfolio-check\scripts\portfolio_check.py
```

Add `--days 14` to scan more log history. The script is read-only: it never writes to MongoDB, never calls Alpha Vantage, and does not need the API key. Do not modify data or rerun collectors as part of this skill; if something needs rerunning, say which command and let Paul decide (rerunning a collector spends Alpha Vantage calls).

If the output has `"error"`, report it plainly and stop. The usual causes: not run from the project root, the venv is missing, or MongoDB isn't running.

## Step 2 - read the JSON

**`overall`**: `OK`, `WARN`, or `FAIL`.

**`pipeline[]`**: one entry per collection:
- `status`: `FAIL` = nothing fresh, or more than half the tickers are behind. `WARN` = some tickers missing or stale.
- `tickers_missing` / `tickers_stale`: which tickers didn't get written.
- `daily_metrics.details`:
  - `tickers_missing_from_latest_bucket`: who got skipped last night.
  - `fundamentals_days_old`: beta, sector and shares outstanding are carried forward since OVERVIEW went premium. Mention it if it's over 30 days, since those numbers are getting stale.
  - `null_payout_ratio`: those tickers will get "Missing payout ratio" in the next safety score.
- `dividend_history.details.validation_status_counts`: `suspect`/`distribution` records are excluded from cut detection. Mention them only if the count changed or is large.

Schedule, for explaining what *should* have run:

| Day | Job | Collection |
|---|---|---|
| Mon | save_income_statements | income_statements |
| Tue-Thu | save_daily_metrics | daily_metrics |
| Fri | save_dividend_history | dividend_history |
| Sat | save_free_cash_flow | free_cash_flow_metrics |
| Sun | dividend_safety_analyzer, portfolio_scorecard | weekly_scores, portfolio_scorecards |

All run from `utilities\run_pipeline.ps1` via Task Scheduler, around 7pm local time. All stored timestamps and date buckets are Eastern time (America/New_York), so a run lands on the calendar day it ran.

**`portfolio`**:
- `dividend_cuts`: **always lead with these.** A cut is Paul's sell signal.
- `holdings_worst_first`: score, `score_change` versus the previous weekly run, and `new_warnings` (warnings that weren't there last week).
- `upcoming_payouts`: declared payments in the next 45 days.
- `data_quality`: bad values in stored scores (for example, beta stored as a non-number).

**`logs.problems`**: ERROR and API-message lines from the last 7 days, grouped. `API MESSAGE` + `Stopping script` usually means Alpha Vantage refused the call (rate limit or premium endpoint). `<T>` stands in for a ticker.

## Step 3 - write the report

Keep it short. Use this layout and leave out empty sections:

```
## Portfolio check - <date>   <OK / WARN / FAIL>

**Action needed**
- <dividend cuts first, then pipeline FAILs, each with the one command or file to look at>

**Pipeline**
| Job | Last write | Status | Notes |
(one row per collection; Notes = missing/stale tickers or "—")

**Holdings to watch**
| Ticker | Score | Change | Status | New warnings |
(only tickers that are WARNING, dropped 10+ points, or have new warnings)

**Upcoming payouts** (next 45 days)
<ticker - amount - pay date, one per line; skip if none>

**Notes**
<at most 3 bullets: log problems, stale fundamentals, data-quality items>
```

Rules:
- If everything is OK and nothing changed, say so in one or two lines instead of the full layout.
- Don't restate healthy holdings one by one; give a count ("19 of 22 healthy").
- Explain a pipeline problem in plain terms ("Saturday's cash-flow run didn't update 21 of 22 tickers") and point to the likely log or command. Don't speculate past what the JSON and logs show.
- Dates in the JSON and the report are Eastern time (America/New_York).
