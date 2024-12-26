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
./src/options-short-put-simple.py --db-path data/spx_eod.db --dte 30 --max-open-trades 5 --profit-take 10 --stop-loss 75
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
./src/options-trade-plotter.py --db-path data/spx_eod.db --table-tag short_put_dte_30
```

View Report

```shell
./src/options-strategy-report.py --db-path data/spx_eod.db --table-tag short_put
```

### Long Put Calendar

```shell
./src/options-trade-plotter.py --db-path data/spx_eod.db --table-tag put_calendar_dte_30_60
```

```shell
./src/options-strategy-report.py --db-path data/spx_eod.db --table-tag put_calendar
```

### Short Straddle

Longer Run (Single DTE)

```shell
./src/options-short-straddle-simple.py --db-path data/spx_eod.db --dte 45 --profit-take 10 --stop-loss 50 --max-open-trades 2 -v
```

```shell
for hvcw in {1..2}; do
  echo "Running for High Vol Check Window: $hvcw"
  ./src/options-short-straddle-simple.py --db-path data/spx_eod.db --high-vol-check --high-vol-check-window $hvcw --dte 45 --profit-take 10 --stop-loss 75 --max-open-trades 2 -v
done
```

```shell
for dte in {7..60}; do
    echo "Running for DTE: $dte"
    ./src/options-short-straddle-simple.py --db-path data/spx_eod.db --dte $dte --profit-take 10 --stop-loss 75 --max-open-trades 5 -v
done
```

```shell
./src/options-trade-plotter.py --db-path data/spx_eod.db --table-tag short_straddle_dte_45
```

```shell
./src/options-strategy-report.py --db-path data/spx_eod.db --table-tag short_straddle
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
./src/options-short-put-simple.py --db-path data/spx_eod.db --dte 30 --start-date 2020-01-01 --end-date 2020-03-30 --max-open-trades 1 --profit-take 10 --stop-loss 75 -v
echo "Should see 24 trades"
```

## Drop all Trade and Trade Legs

```shell
sqlite3 data/spx_eod.db "SELECT 'DROP TABLE IF EXISTS ' || name || ';' FROM sqlite_master WHERE type = 'table' AND (name LIKE 'trades_%' OR name LIKE 'trade_legs_%');" | sqlite3 data/spx_eod.db
```
