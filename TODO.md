# dividend-tracker TODO

## Open
- [ ] Bucket daily_metrics "date" by local time, not UTC (DST boundary risk at 7pm EST)
- [ ] Add dividend yield threshold warning (flag high yield vs. historical avg or absolute >6-7%)
- [ ] Weight negative EPS as its own warning, not just "missing payout ratio" (ties into income statement work)

## Done
- [x] Fixed dividend_amount/amount field mismatch
- [x] Fixed REIT payout ratio unit mismatch (shares_outstanding)
- [x] ...