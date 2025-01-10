# Options Analysis Toolkit

![Intro](assets/trade-plotter.png)

## Parameters

Generic parameters

```text
  --db-path DB_PATH     Path to the SQLite database file
  --max-open-trades MAX_OPEN_TRADES
                        Maximum number of open trades allowed at a given time
  --trade-delay TRADE_DELAY
                        Minimum number of days to wait between new trades
  --force-close-after-days FORCE_CLOSE_AFTER_DAYS
                        Force close trade after days
  -sd START_DATE, --start-date START_DATE
                        Start date for backtesting
  -ed END_DATE, --end-date END_DATE
                        End date for backtesting
  --profit-take PROFIT_TAKE
                        Close position when profit reaches this percentage of premium received
  --stop-loss STOP_LOSS
                        Close position when loss reaches this percentage of premium received
  --high-vol-check      Enable high volatility check
  --high-vol-check-window HIGH_VOL_CHECK_WINDOW
                        Window size for high volatility check
```

Each strategy may have its own set of parameter.

## Reports

* [short-put-1-max-close-expiry.html](https://namuan.github.io/options-toolkit/short-put/short-put-1-max-close-expiry.html)

## Import Data

Extract all contents from compressed files into a designated folder.
The following script can read nested folders, allowing them to be accessed without being placed at the root level.

```shell
./scripts/optionsdx-data-importer.py --input $(pwd)/data/spx_eod --output data/spx_eod.db -v
```

Check for any missing data

```shell
./scripts/options-data-check-date-gaps.py --db-file data/spx_eod.db --days 5
```

## Strategies

### Naked Short Put

Trade every day
Filter: 30 DTE, PT 10%, SL 75%, Max 5 Trades.

```shell
./scripts/options-short-put-simple.py --db-path data/spx_eod.db --dte 30 --max-open-trades 1 --profit-take 10 --stop-loss 75
```

Filter: 30 DTE
Trade every day, Close at Expiry

```shell
./scripts/options-short-put-simple.py --db-path data/spx_eod.db --dte 30 -v
```

Filter 7-60 DTE
Trade every day, Max 5 positions, Close at Expiry

```shell
for dte in {7..60}; do
    echo "Running for DTE: $dte"
    ./scripts/options-short-put-simple.py --db-path data/spx_eod.db --dte $dte --max-open-trades 1 --profit-take 10 --stop-loss 75
done
```

**RSI Filter**

```shell
./scripts/options-short-put-simple.py --db-path data/spx_eod.db --short-put-delta 0.2 --dte 45 --max-open-trades 5 --rsi 4 --rsi-low-threshold 15 --force-close-after-days 20 --profit-take 50 --stop-loss 75 -vv
```


```shell
STRATEGY=ShortPutStrategy;./scripts/options-trade-plotter.py --db-path data/spx_eod.db --strategy-name ${STRATEGY} --table-name-key `sqlite3 data/spx_eod.db "SELECT RawParams, TableNameKey from backtest_runs where Strategy = '"${STRATEGY}"'" | sed 's/verbose=1,db_path=data\/spx_eod.db,//; s/,start_date=None,end_date=None//' | fzf | awk -F\| '{print $2}'`
```

View Report

```shell
STRATEGY=ShortPutStrategy; ./scripts/options-strategy-report.py --db-path data/spx_eod.db --strategy-name ${STRATEGY}
```

### RSI Filter Short Put/Call

```shell
./scripts/options-short-put-call-simple.py --db-path data/spx_eod.db --short-put-delta 0.2 --short-call-delta -0.15 --dte 45 --max-open-trades 5 --rsi 4 --rsi-low-threshold 15 --rsi-high-threshold 80 --force-close-after-days 20 --profit-take 50 --stop-loss 75 -vv
```

```shell
STRATEGY=ShortPutCallStrategy;./scripts/options-trade-plotter.py --db-path data/spx_eod.db --strategy-name ${STRATEGY} --table-name-key `sqlite3 data/spx_eod.db "SELECT RawParams, TableNameKey from backtest_runs where Strategy = '"${STRATEGY}"'" | fzf | awk -F\| '{print $2}'`
```

```shell
STRATEGY=ShortPutCallStrategy; ./scripts/options-strategy-report.py --db-path data/spx_eod.db --strategy-name ${STRATEGY}
```

### Long Put Calendar

```shell
./scripts/options-calendar-simple.py --db-path data/spx_eod.db --front-dte 30 --back-dte 60 --max-open-trades 1 -v
```

```shell
STRATEGY=LongPutCalendarStrategy;./scripts/options-trade-plotter.py --db-path data/spx_eod.db --strategy-name ${STRATEGY} --table-name-key `sqlite3 data/spx_eod.db "SELECT RawParams, TableNameKey from backtest_runs where Strategy = '"${STRATEGY}"'" | fzf | awk -F\| '{print $2}'`
```

```shell
STRATEGY=LongPutCalendarStrategy; ./scripts/options-strategy-report.py --db-path data/spx_eod.db --strategy-name ${STRATEGY}
```

### Short Straddle

Longer Run

```shell
./scripts/options-short-straddle-simple.py --db-path data/spx_eod.db --force-close-after-days 10 --dte 45 --profit-take 10 --stop-loss 75 --max-open-trades 5 -v
```

```shell
./scripts/options-short-straddle-simple.py --db-path data/spx_eod.db --number-of-contracts 5 --ladder-additional-contracts --max-open-trades 1 --force-close-after-days 10 --dte 45 --profit-take 10 --stop-loss 75 -v
```

```shell
./scripts/options-short-straddle-simple.py --db-path data/spx_eod.db --number-of-contracts 5 --max-open-trades 1 --force-close-after-days 10 --dte 45 --profit-take 10 --stop-loss 75 -v
```

```shell
for hvcw in {1..2}; do
  echo "Running for High Vol Check Window: $hvcw"
  ./scripts/options-short-straddle-simple.py --db-path data/spx_eod.db --high-vol-check --high-vol-check-window $hvcw --dte 45 --profit-take 10 --stop-loss 75 --max-open-trades 1 -v
done
```

```shell
for fcd in {1..20}; do
  echo "Running for Force Close after: $fcd days"
  ./scripts/options-short-straddle-simple.py --db-path data/spx_eod.db --force-close-after-days $fcd --dte 45 --profit-take 10 --stop-loss 75 --max-open-trades 1 -v
done
```

```shell
for dte in {44..46}; do
    echo "Running for DTE: $dte"
    ./scripts/options-short-straddle-simple.py --db-path data/spx_eod.db --dte $dte --profit-take 10 --stop-loss 75 --max-open-trades 1 -v
done
```

```shell
STRATEGY=ShortStraddleStaggeredEntryStrategy;./scripts/options-trade-plotter.py --db-path data/spx_eod.db --strategy-name ${STRATEGY} --table-name-key `sqlite3 data/spx_eod.db "SELECT RawParams, TableNameKey from backtest_runs where Strategy = '"${STRATEGY}"'" | fzf | awk -F\| '{print $2}'`
```

```shell
STRATEGY=ShortStraddleStaggeredEntryStrategy; ./scripts/options-strategy-report.py --db-path data/spx_eod.db --strategy-name ${STRATEGY}
```

## Testing

```shell
./scripts/options-short-straddle-simple.py --db-path data/spx_eod.db --dte 45 --start-date 2020-01-01 --end-date 2020-03-30 --max-open-trades 1 -v
echo "Should see 2 trades"
```

```shell
./scripts/options-calendar-simple.py --db-path data/spx_eod.db --front-dte 30 --back-dte 60 --start-date 2020-01-01 --end-date 2020-03-30 --max-open-trades 1 -v
echo "Should see 3 trades"
```

```shell
./scripts/options-short-put-simple.py --db-path data/spx_eod.db --short-put-delta 0.5 --dte 45 --start-date 2020-01-01 --end-date 2020-03-30 --max-open-trades 1 --profit-take 10 --stop-loss 75 -v
echo "Should see 22 trades"
```

```shell
STRATEGY=ShortStraddleStaggeredEntryStrategy;./scripts/options-trade-plotter.py --db-path data/spx_eod.db --strategy-name ${STRATEGY} --table-name-key `sqlite3 data/spx_eod.db "SELECT RawParams, TableNameKey from backtest_runs where Strategy = '"${STRATEGY}"'" | fzf | awk -F\| '{print $2}'`
```

```shell
STRATEGY=ShortStraddleStaggeredEntryStrategy; ./scripts/options-strategy-report.py --db-path data/spx_eod.db --strategy-name ${STRATEGY}
```

```shell
STRATEGY=ShortStraddleStrategy;./scripts/short_straddle_trade_adjustments.py --db-path data/spx_eod.db --strategy-name ${STRATEGY} --table-name-key `sqlite3 data/spx_eod.db "SELECT RawParams, TableNameKey from backtest_runs where Strategy = '"${STRATEGY}"'" | fzf | awk -F\| '{print $2}'`
```

## Bulk testing across different parameters

```shell
# Define single values for each parameter for quick testing
rsi_values=(4)           # Only RSI 4
rsi_low_thresholds=(20)  # Only RSI Low Threshold 20
dte_values=(30)          # Only DTE 30
stop_loss_values=(75)    # Only Stop Loss 75

# Loop through each combination of parameters
for rsi in "${rsi_values[@]}"; do
    for rsi_low in "${rsi_low_thresholds[@]}"; do
        for dte in "${dte_values[@]}"; do
            for stop_loss in "${stop_loss_values[@]}"; do
                # Run the options short put script with the current parameters
                ./scripts/options-short-put-simple.py --db-path data/spx_eod.db --rsi "$rsi" --rsi-low-threshold "$rsi_low" --short-delta 0.5 --dte "$dte" --stop-loss "$stop_loss" --max-open-trades 1 -v
            done
        done
    done
done

STRATEGY=ShortPutStrategy; ./scripts/options-strategy-report.py --db-path data/spx_eod.db --strategy-name ${STRATEGY}
```

With different RSI values

```shell
rsi_values=(3 5 7 9 11 13)
rsi_low_values=(0 30)
rsi_high_values=(100)

for rsi in "${rsi_values[@]}"; do
  for rsi_low in "${rsi_low_values[@]}"; do
    for rsi_high in "${rsi_high_values[@]}"; do
        echo "Running with RSI: $rsi: RSI Low: $rsi_low RSI High: $rsi_high"
        ./scripts/options-short-straddle-simple.py --db-path data/spx_eod.db --force-close-after-days 10 --dte 45 --profit-take 10 --stop-loss 75 --max-open-trades 5 --rsi $rsi --rsi-low-threshold $rsi_low --rsi-high-threshold $rsi_high -v
    done
  done
done
```

## Drop all transaction tables

```shell
sqlite3 data/spx_eod.db "DROP TABLE backtest_runs";
sqlite3 data/spx_eod.db "SELECT 'DROP TABLE IF EXISTS ' || name || ';' FROM sqlite_master WHERE type = 'table' AND (name LIKE 'trades_%' OR name LIKE 'trade_legs_%');" | sqlite3 data/spx_eod.db
```

