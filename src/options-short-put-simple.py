#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "pandas",
#   "yfinance",
#   "persistent-cache@git+https://github.com/namuan/persistent-cache",
#   "stockstats",
# ]
# ///
"""
Options Straddle Analysis Script

Usage:
./options-short-put-simple.py -h
./options-short-put-simple.py -v # To log INFO messages
./options-short-put-simple.py -vv # To log DEBUG messages
./options-short-put-simple.py --db-path path/to/database.db # Specify database path
./options-short-put-simple.py --dte 30 # Find next expiration with DTE > 30 for each quote date
./options-short-put-simple.py --trade-delay 7 # Wait 7 days between new trades
"""

import logging
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from typing import Optional

from stockstats import wrap

from logger import setup_logging
from market_data import download_ticker_data
from options_analysis import (
    ContractType,
    GenericRunner,
    Leg,
    LegType,
    OptionsData,
    OptionsDatabase,
    PositionType,
    Trade,
    add_standard_cli_arguments,
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
        "--short-delta",
        type=float,
        default=0.5,
        help="Short delta value",
    )
    parser.add_argument(
        "--rsi",
        type=int,
        help="RSI",
    )
    parser.add_argument(
        "--rsi-low-threshold",
        type=int,
        help="RSI Lower Threshold",
    )
    return parser.parse_args()


class ShortPutStrategy(GenericRunner):
    def __init__(self, args):
        super().__init__(args)
        self.dte = args.dte
        self.short_delta = args.short_delta
        self.rsi_check_required = args.rsi and args.rsi_low_threshold
        self.rsi_indicator = f"rsi_{args.rsi}"
        self.rsi_low_threshold = args.rsi_low_threshold
        self.external_df = None

    def pre_run(self, options_db, quote_dates):
        if self.rsi_check_required:
            self.external_df = wrap(
                download_ticker_data("SPY", start=quote_dates[0], end=quote_dates[-1])
            )
            _ = self.external_df[self.rsi_indicator]

    def allowed_to_create_new_trade(self, options_db, data_for_trade_management):
        allowed_based_on_default_checks = super().allowed_to_create_new_trade(
            options_db, data_for_trade_management
        )
        if not allowed_based_on_default_checks:
            return False

        if not self.rsi_check_required:
            return True

        # RSI Check
        if data_for_trade_management.quote_date in self.external_df.index:
            rsi_value = self.external_df.loc[
                data_for_trade_management.quote_date, self.rsi_indicator
            ]
            return rsi_value <= self.rsi_low_threshold
        else:
            return False

    def build_trade(self, options_db: OptionsDatabase, quote_date) -> Optional[Trade]:
        expiry_dte, dte_found = options_db.get_next_expiry_by_dte(quote_date, self.dte)
        if not expiry_dte:
            logging.warning(f"⚠️ Unable to find {self.dte} expiry. {expiry_dte=}")
            return None

        logging.debug(f"Quote date: {quote_date} -> {expiry_dte=} ({dte_found=:.1f}), ")
        od: OptionsData = options_db.get_options_by_delta(
            ContractType.PUT,
            PositionType.SHORT,
            quote_date,
            expiry_dte,
            self.short_delta,
        )
        if not od or od.p_last in [None, 0]:
            logging.warning(
                "⚠️ Bad data found: "
                + (
                    "One or more options are not valid"
                    if not od
                    else f"On {quote_date=} {od.p_last=} is not valid"
                )
            )
            return None

        logging.debug(
            f"Contract ({expiry_dte=}): { od.underlying_last=:.2f}, { od.strike=:.2f}, { od.c_last=:.2f}, { od.p_last=:.2f}"
        )

        trade_legs = [
            Leg(
                leg_quote_date=quote_date,
                leg_expiry_date=expiry_dte,
                leg_type=LegType.TRADE_OPEN,
                position_type=PositionType.SHORT,
                contract_type=ContractType.PUT,
                strike_price=od.strike,
                underlying_price_open=od.underlying_last,
                premium_open=od.p_last,
                premium_current=0,
                delta=od.p_delta,
                gamma=od.p_gamma,
                vega=od.p_vega,
                theta=od.p_theta,
                iv=od.p_iv,
            ),
        ]

        premium_captured_calculated = round(
            sum(leg.premium_open for leg in trade_legs), 2
        )

        return Trade(
            trade_date=quote_date,
            expire_date=expiry_dte,
            dte=self.dte,
            status="OPEN",
            premium_captured=premium_captured_calculated,
            legs=trade_legs,
        )


def main(args):
    with ShortPutStrategy(args) as runner:
        runner.run()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
