# dividend-tracker TODO

## Open
- [ ] Add dividend yield threshold warning (flag high yield vs. historical avg or absolute >6-7%)
- [ ] Weight negative EPS as its own warning, not just "missing payout ratio" (ties into income statement work)
- [ ] Replace frozen shares_outstanding (stuck at 2026-10-01 OVERVIEW values) - start after feature/monthly-beta merges
  - New monthly `collectors.save_balance_sheet`: BALANCE_SHEET `commonStockSharesOutstanding`, latest quarter per ticker (confirmed free 2026-11-15; sample in notes/call2BALANCE_SHEET-ABT.txt)
  - Schedule on one Tue-Thu daily_metrics night per month (no spare API night)
  - `save_daily_metrics` reads shares from it instead of carrying forward
  - Hard-code sector/industry per ticker in `models/constants.py` so new tickers (e.g. SBAC) get REIT detection

## Done
- [x] Store all timestamps and daily_metrics "date" buckets in Eastern time, not UTC
- [x] Fixed dividend_amount/amount field mismatch
- [x] Fixed REIT payout ratio unit mismatch (shares_outstanding)
- [x] ...