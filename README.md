# Options Analysis Toolkit

![Intro](assets/trade-plotter.png)

## Reports

* [short-put-1-max-close-expiry.html](https://namuan.github.io/options-toolkit/short-put/short-put-1-max-close-expiry.html)

## Import Data

Extract all contents from compressed files into a designated folder.
The following script can read nested folders, allowing them to be accessed without being placed at the root level.

```shell
./src/optionsdx-data-importer.py --input $(pwd)/data/spx_eod --output data/spx_eod.db -v
```

Check for any missing data

```shell
./src/options-data-check-date-gaps.py --db-file data/spx_eod.db --days 5
```

## Strategies

### Naked Short Put

Trade every day
Filter: 30 DTE, PT 10%, SL 75%, Max 5 Trades.

```shell
./src/options-short-put-simple.py --db-path data/spx_eod.db --dte 30 --max-open-trades 1 --profit-take 10 --stop-loss 75
```

Filter: 30 DTE
Trade every day, Close at Expiry

```shell
./src/options-short-put-simple.py --db-path data/spx_eod.db --dte 30 -v
```

Filter 7-60 DTE
Trade every day, Max 5 positions, Close at Expiry

```shell
for dte in {7..60}; do
    echo "Running for DTE: $dte"
    ./src/options-short-put-simple.py --db-path data/spx_eod.db --dte $dte --max-open-trades 1 --profit-take 10 --stop-loss 75
done
```

```shell
STRATEGY=ShortPutStrategy;./src/options-trade-plotter.py --db-path data/spx_eod.db --strategy-name ${STRATEGY} --table-name-key `sqlite3 data/spx_eod.db "SELECT RawParams, TableNameKey from backtest_runs where Strategy = '"${STRATEGY}"'" | sed 's/verbose=1,db_path=data\/spx_eod.db,//; s/,start_date=None,end_date=None//' | fzf | awk -F\| '{print $2}'`
```

View Report

```shell
STRATEGY=ShortPutStrategy; ./src/options-strategy-report.py --db-path data/spx_eod.db --strategy-name ${STRATEGY}
```

### Long Put Calendar

```shell
STRATEGY=LongPutCalendarStrategy;./src/options-trade-plotter.py --db-path data/spx_eod.db --strategy-name ${STRATEGY} --table-name-key `sqlite3 data/spx_eod.db "SELECT RawParams, TableNameKey from backtest_runs where Strategy = '"${STRATEGY}"'" | fzf | awk -F\| '{print $2}'`
```

```shell
STRATEGY=LongPutCalendarStrategy; ./src/options-strategy-report.py --db-path data/spx_eod.db --strategy-name ${STRATEGY}
```

### Short Straddle

Longer Run (Single DTE)

```shell
./src/options-short-straddle-simple.py --db-path data/spx_eod.db --force-close-after-days 10 --dte 45 --profit-take 10 --stop-loss 75 --max-open-trades 1 -v
```

```shell
for hvcw in {1..2}; do
  echo "Running for High Vol Check Window: $hvcw"
  ./src/options-short-straddle-simple.py --db-path data/spx_eod.db --high-vol-check --high-vol-check-window $hvcw --dte 45 --profit-take 10 --stop-loss 75 --max-open-trades 1 -v
done
```

```shell
for fcd in {1..20}; do
  echo "Running for Force Close after: $fcd days"
  ./src/options-short-straddle-simple.py --db-path data/spx_eod.db --force-close-after-days $fcd --dte 45 --profit-take 10 --stop-loss 75 --max-open-trades 1 -v
done
```

```shell
for dte in {44..46}; do
    echo "Running for DTE: $dte"
    ./src/options-short-straddle-simple.py --db-path data/spx_eod.db --dte $dte --profit-take 10 --stop-loss 75 --max-open-trades 1 -v
done
```

```shell
STRATEGY=ShortStraddleStrategy;./src/options-trade-plotter.py --db-path data/spx_eod.db --strategy-name ${STRATEGY} --table-name-key `sqlite3 data/spx_eod.db "SELECT RawParams, TableNameKey from backtest_runs where Strategy = '"${STRATEGY}"'" | fzf | awk -F\| '{print $2}'`
```

```shell
STRATEGY=ShortStraddleStrategy; ./src/options-strategy-report.py --db-path data/spx_eod.db --strategy-name ${STRATEGY}
```

## Testing

```shell
./src/options-short-straddle-simple.py --db-path data/spx_eod.db --dte 45 --start-date 2020-01-01 --end-date 2020-03-30 --max-open-trades 1 -v
echo "Should see 2 trades"
```

```shell
./src/options-calendar-simple.py --db-path data/spx_eod.db --front-dte 30 --back-dte 60 --start-date 2020-01-01 --end-date 2020-03-30 --max-open-trades 1 -v
echo "Should see 3 trades"
```

```shell
./src/options-short-put-simple.py --db-path data/spx_eod.db --short-delta 0.5 --dte 45 --start-date 2020-01-01 --end-date 2020-03-30 --max-open-trades 1 --profit-take 10 --stop-loss 75 -v
echo "Should see 22 trades"
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
                ./src/options-short-put-simple.py --db-path data/spx_eod.db --rsi "$rsi" --rsi-low-threshold "$rsi_low" --short-delta 0.5 --dte "$dte" --stop-loss "$stop_loss" --max-open-trades 1 -v
            done
        done
    done
done

STRATEGY=ShortPutStrategy; ./src/options-strategy-report.py --db-path data/spx_eod.db --strategy-name ${STRATEGY}
```

## Drop all transaction tables

```shell
sqlite3 data/spx_eod.db "DROP TABLE backtest_runs";
sqlite3 data/spx_eod.db "SELECT 'DROP TABLE IF EXISTS ' || name || ';' FROM sqlite_master WHERE type = 'table' AND (name LIKE 'trades_%' OR name LIKE 'trade_legs_%');" | sqlite3 data/spx_eod.db
```
