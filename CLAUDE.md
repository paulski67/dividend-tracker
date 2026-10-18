# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal dividend-safety tracker for a fixed watchlist of 22 dividend stocks (`STOCK_TICKERS` in `models/constants.py`). Collectors pull data from the Alpha Vantage free API into a local MongoDB (`dividend_tracker` database); analyzers score each ticker weekly and write a scorecard report. A dividend cut is the owner's sell signal.

There is no test suite, linter, or build step.

## Running things

Every script must be run **as a module from the project root**: `config/config.ini` and `logs/` are opened by relative path.

```powershell
.venv\Scripts\python.exe -m utilities.health_check                  # internet + MongoDB + memory check
.venv\Scripts\python.exe -m collectors.save_daily_metrics_quote ADP  # one ticker
.venv\Scripts\python.exe -m collectors.save_daily_metrics_quote --dry-run ADP   # print, no insert
.venv\Scripts\python.exe -m analyzers.dividend_safety_analyzer
.venv\Scripts\python.exe -m analyzers.portfolio_scorecard
.venv\Scripts\python.exe -m utilities.archive_manager backup backups\<dir>     # or: restore
```

Only `save_daily_metrics_quote` accepts ticker args / `--dry-run`; the other collectors always process the full watchlist. Scripts do their work at module level (no `main()`), so importing one runs it.

**Collectors spend Alpha Vantage calls** (free tier: daily cap, `THROTTLE_SECONDS = 15` between calls). Don't rerun them casually; ask first. Analyzers and `/portfolio-check` only read MongoDB.

## Pipeline

`utilities/run_pipeline.ps1` runs nightly ~7pm local via Task Scheduler (`utilities/dividend-tracker.xml`). It runs the health check, then one job per weekday:

| Day | Job | Writes to |
|---|---|---|
| Mon | `collectors.save_income_statements` | `income_statements` |
| Tue–Thu | `collectors.save_daily_metrics_quote` | `daily_metrics` |
| Fri | `collectors.save_dividend_history` | `dividend_history` |
| Sat | `collectors.save_free_cash_flow` | `free_cash_flow_metrics` |
| Sun | `analyzers.dividend_safety_analyzer`, then `analyzers.portfolio_scorecard` | `weekly_scores`, `portfolio_scorecards`, `reports/*.txt` |

Logs: `logs/pipeline.log` (daily rotation, via `utilities.logger.setup_logger`) and `logs/run_pipeline_<stamp>.log` transcripts.

## Architecture notes

- **`models/`**: shared plumbing. `mongo.get_collection()`, `settings` (reads `config/config.ini`: API key, thresholds), `constants` (collection names, ticker list), `utils.safe_float/safe_int/safe_date` (Alpha Vantage returns `"None"`/`"N/A"` strings), `api_utils.check_api_response()` (detects rate-limit / premium messages, which come back as HTTP 200 with a `Note`/`Information` field).
- **`utilities/dividend_helper.py`**: the domain logic shared by analyzers and collectors: cut detection, growth check, REIT detection (`"REIT"` in `industry`), standard vs. REIT payout ratio (REITs use TTM free cash flow, normalized by `shares_outstanding`).
- **OVERVIEW went premium on 2026-10-06.** `save_daily_metrics_quote.py` replaced `save_daily_metrics.py` (kept for reference, no longer scheduled). It derives price from GLOBAL_QUOTE, dividend/share from `dividend_history`, EPS from `income_statements` net income ÷ shares; **beta, sector, industry and shares_outstanding are carried forward** from the last real value (`fundamentals_as_of`). Its module docstring has the full field-source map.
- On an API refusal, collectors stop the whole run rather than burning remaining daily calls. A collector can exit 0 having inserted nothing, so check the data, not exit codes.
- `dividend_history` records carry `validation_status`; `suspect` ones (e.g. a >2× jump) are excluded from cut detection (`get_recent_dividends(valid_only=True)`).
- Safety score starts at 100 with deductions per warning (payout ratio vs. `[thresholds]` in config, beta, negative FCF, cut, etc.); `weekly_scores` is append-only history, `portfolio_scorecards` is one upserted doc per ticker.
- **All stored timestamps and date buckets are Eastern wall-clock time** (America/New_York, naive datetimes). Use `models.utils.now_local()` / `today_local()`, never `datetime.utcnow()`. Calendar dates from Alpha Vantage (ex-dividend, fiscal dates) are stored as-is.

## Repo conventions

- `config/config.ini` (holds the API key), `notes/`, `logs/`, `backups/`, `archive/`, and `reports/*.txt` are gitignored.
- Work happens on `feature/*` branches merged via PR to `main` on GitHub (`paulski67/dividend-tracker`).
- Project skill: `.claude/skills/portfolio-check`, a read-only status report of pipeline freshness and portfolio signals.
