#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "pandas",
#   "yfinance",
#   "persistent-cache@git+https://github.com/namuan/persistent-cache",
#   "stockstats",
# ]
# ///
""" """

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
        "--short-put-delta",
        type=float,
        default=0.5,
        help="Short Put delta value",
    )
    parser.add_argument(
        "--short-call-delta",
        type=float,
        default=0.5,
        help="Short Call delta value",
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
    # TODO: Add argument for rsi_high_threshold
    return parser.parse_args()


class ShortPutCallStrategy(GenericRunner):
    def __init__(self, args):
        super().__init__(args)
        self.dte = args.dte
        self.short_put_delta = args.short_put_delta
        self.short_call_delta = args.short_call_delta
        self.rsi_check_required = args.rsi and args.rsi_low_threshold
        self.rsi_indicator = f"rsi_{args.rsi}"
        self.rsi_low_threshold = args.rsi_low_threshold
        self.rsi_high_threshold = args.rsi_high_threshold
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
        # TODO: Simplify this function
        if not allowed_based_on_default_checks:
            return False

        return True

    def build_trade(self, options_db: OptionsDatabase, quote_date) -> Optional[Trade]:
        expiry_dte, dte_found = options_db.get_next_expiry_by_dte(quote_date, self.dte)
        if not expiry_dte:
            logging.warning(f"⚠️ Unable to find {self.dte} expiry. {expiry_dte=}")
            return None

        logging.debug(f"Quote date: {quote_date} -> {expiry_dte=} ({dte_found=:.1f}), ")
        put_option: OptionsData = options_db.get_options_by_delta(
            ContractType.PUT,
            PositionType.SHORT,
            quote_date,
            expiry_dte,
            self.short_put_delta,
        )
        call_option: OptionsData = options_db.get_options_by_delta(
            ContractType.CALL,
            PositionType.SHORT,
            quote_date,
            expiry_dte,
            self.short_call_delta,
        )
        if (
            not put_option
            or put_option.p_last in [None, 0]
            or not call_option
            or call_option.p_last in [None, 0]
        ):
            logging.warning(
                "⚠️ Bad data found: "
                + (
                    "One or more options are not valid"
                    if not put_option
                    else f"On {quote_date=} Either {put_option.p_last=} or {call_option.c_last} is not valid"
                )
            )
            return None

        logging.debug(
            f"Contract ({expiry_dte=}): { put_option.underlying_last=:.2f}, { put_option.strike=:.2f}, { put_option.c_last=:.2f}, { put_option.p_last=:.2f}"
        )

        # TODO: Determine what trade to do based on RSI
        # current_rsi_value = self.rsi_value_for(quote_date)
        # trade_decision is either short_put, short_call or none
        # if current_rsi_value is None then no trade
        # If current_rsi_value < low_threshold then Short Put
        # If current_rsi_value > high_threshold then Short Call

        trade_legs = [
            Leg(
                leg_quote_date=quote_date,
                leg_expiry_date=expiry_dte,
                leg_type=LegType.TRADE_OPEN,
                position_type=PositionType.SHORT,
                contract_type=ContractType.PUT,
                strike_price=put_option.strike,
                underlying_price_open=put_option.underlying_last,
                premium_open=put_option.p_last,
                premium_current=0,
                delta=put_option.p_delta,
                gamma=put_option.p_gamma,
                vega=put_option.p_vega,
                theta=put_option.p_theta,
                iv=put_option.p_iv,
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

    def rsi_value_for(self, quote_date):
        if quote_date not in self.external_df.index:
            return None
        return self.external_df.loc[quote_date, self.rsi_indicator]


def main(args):
    with ShortPutCallStrategy(args) as runner:
        runner.run()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
