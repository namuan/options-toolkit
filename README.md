# Options Analysis Toolkit

![Intro](assets/trade-plotter.png)

## Reports

* [short-put-1-max-close-expiry.html](docs/short-put/short-put-1-max-close-expiry.html)

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

### Short Straddle

**Vol check, Profit Take 15%, Stop Loss 100% of Credit**

```shell
for dte in {7..60}; do
    echo "Running for DTE: $dte"
    ./src/options-straddle-low-vol-trades.py --db-path data/spx_eod.db --dte $dte --profit-take 15 --stop-loss 100 --max-open-trades 5 -v
done
```

```shell
./src/options-straddle-low-vol-trades.py --db-path data/spx_eod.db --dte 60 --profit-take 10 --stop-loss 100 --max-open-trades 5 -v
```

```shell
cp data/spx_eod.db data/spx_eod_vol_filter.db
```

```shell
./src/options-straddle-simple-report.py --database data/spx_eod_vol_filter.db --weeks 4 --dte 60
```

```shell
./src/options-strategy-report.py --db-path data/spx_eod_vol_filter.db
```

**What if we keep all trades with given profit take and stop loss**

```shell
for dte in {7..60}; do
    echo "Running for DTE: $dte"
    ./src/options-straddle-profit-take-stop-loss-adjustment.py --db-path data/spx_eod.db --dte $dte --profit-take 10 --stop-loss 75 --max-open-trades 5 -v
done
```

```shell
./src/options-straddle-profit-take-stop-loss-adjustment.py --db-path data/spx_eod.db --dte 60 --profit-take 10 --stop-loss 75 --max-open-trades 5 -v
```

```shell
./src/options-straddle-profit-take-stop-loss-adjustment.py --db-path data/spx_eod.db --dte 60 --profit-take 10 --stop-loss 75 --max-open-trades 5 --trade-delay 5 -v
```

```shell
cp data/spx_eod.db data/spx_eod_profit_loss_adjustment.db
```

```shell
./src/options-straddle-simple-report.py --database data/spx_eod_profit_loss_adjustment.db --weeks 4 --dte 60
```

```shell
./src/options-strategy-report.py --db-path data/spx_eod_profit_loss_adjustment.db
```

**What if we keep all trades all the time**

```shell
for dte in {7..60}; do
    echo "Running for DTE: $dte"
    ./src/options-straddle-simple.py --db-path data/spx_eod.db --dte $dte
done
```

```shell
./src/options-straddle-simple.py --db-path data/spx_eod.db --dte 60 --max-open-trades 99 -v
```

```shell
cp data/spx_eod.db data/spx_eod_simple.db
```

```shell
./src/options-straddle-simple-report.py --database data/spx_eod_simple.db --weeks 4 --dte 60
```

```shell
./src/options-strategy-report.py --db-path data/spx_eod_simple.db
```

### Naked Short Put

Filter: Between dates. 30 DTE
Trade every day, Close at Expiry

```shell
./src/options-short-put-simple.py --db-path data/spx_eod.db --dte 30 --start-date 2020-01-01 --end-date 2023-12-30 --max-open-trades 1 -v
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
    ./src/options-short-put-simple.py --db-path data/spx_eod.db --dte $dte --max-open-trades 1
done
```

```shell
./src/options-strategy-report.py --db-path data/spx_eod.db
```
