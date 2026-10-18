# dividend-tracker TODO

## Open
- [ ] Add dividend yield threshold warning (flag high yield vs. historical avg or absolute >6-7%)
- [ ] Weight negative EPS as its own warning, not just "missing payout ratio" (ties into income statement work)

## Done
- [x] Store all timestamps and daily_metrics "date" buckets in Eastern time, not UTC
- [x] Fixed dividend_amount/amount field mismatch
- [x] Fixed REIT payout ratio unit mismatch (shares_outstanding)
- [x] ...