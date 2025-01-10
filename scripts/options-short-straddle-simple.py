#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "pandas",
#   "stockstats",
#   "yfinance",
#   "persistent-cache@git+https://github.com/namuan/persistent-cache",
# ]
# ///
from argparse import ArgumentParser, RawDescriptionHelpFormatter

from logger import setup_logging
from options_analysis import (
    add_standard_cli_arguments,
)
from short_straddle_strategies import (
    ShortStraddleRsiFilterStrategy,
    ShortStraddleStaggeredEntryStrategy,
    ShortStraddleStrategy,
)


def parse_args():
    parser = ArgumentParser(
        description=__doc__, formatter_class=RawDescriptionHelpFormatter
    )
    add_standard_cli_arguments(parser)
    parser.add_argument(
        "--dte",
        type=int,
        default=30,
        help="Option DTE",
    )
    parser.add_argument(
        "--high-vol-check",
        action="store_true",
        default=False,
        help="Enable high volatility check",
    )
    parser.add_argument(
        "--high-vol-check-window",
        type=int,
        default=1,
        help="Window size for high volatility check",
    )
    parser.add_argument(
        "--rsi",
        type=int,
        help="RSI",
    )
    parser.add_argument(
        "--number-of-contracts",
        type=int,
        default=1,
        help="Number of contract laddered over days",
    )
    parser.add_argument(
        "--ladder-additional-contracts",
        action="store_true",
        default=False,
        help="Enable laddering of additional contracts",
    )
        "--rsi-low-threshold",
        type=int,
        help="RSI Lower Threshold",
    )
    parser.add_argument(
        "--rsi-high-threshold",
        type=int,
        help="RSI Upper Threshold",
    )
    return parser.parse_args()


def main(args):
    # with ShortStraddleStrategy(args) as runner:
    #     runner.run()
    # with ShortStraddleRsiFilterStrategy(args) as runner:
    #     runner.run()
    with ShortStraddleStaggeredEntryStrategy(args) as runner:
        runner.run()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
