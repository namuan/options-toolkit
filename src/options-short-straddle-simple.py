#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "pandas",
#   "yfinance",
#   "persistent-cache@git+https://github.com/namuan/persistent-cache",
# ]
# ///
"""
Options Straddle Analysis Script

Usage:
./options-short-straddle-simple.py -h
./options-short-straddle-simple.py -v # To log INFO messages
./options-short-straddle-simple.py -vv # To log DEBUG messages
./options-short-straddle-simple.py --db-path path/to/database.db # Specify database path
./options-short-straddle-simple.py --dte 30 # Find next expiration with DTE > 30 for each quote date
./options-short-straddle-simple.py --trade-delay 7 # Wait 7 days between new trades
"""

import logging
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from typing import Optional

import pandas as pd
from pandas import DataFrame

from logger import setup_logging
from market_data import download_ticker_data
from options_analysis import (
    ContractType,
    DataForTradeManagement,
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
    return parser.parse_args()


def pull_external_data(quote_dates, window) -> DataFrame:
    symbols = ["^VIX9D", "^VIX"]
    market_data = {
        symbol: download_ticker_data(symbol, start=quote_dates[0], end=quote_dates[-1])
        for symbol in symbols
    }

    df = pd.DataFrame()
    df["Short_Term_VIX"] = market_data["^VIX9D"]["Close"]
    df["Long_Term_VIX"] = market_data["^VIX"]["Close"]
    df["IVTS"] = df["Short_Term_VIX"] / df["Long_Term_VIX"]
    df[f"IVTS_Med_{window}"] = df["IVTS"].rolling(window=window).median()
    df["High_Vol_Signal"] = (df[f"IVTS_Med_{window}"] < 1).astype(int) * 2 - 1
    return df


class ShortStraddleStrategy(GenericRunner):
    def __init__(self, args, table_tag):
        super().__init__(args, table_tag)
        self.dte = args.dte
        self.high_vol_check_window = args.high_vol_check_window
        self.high_vol_check_required = args.high_vol_check
        self.external_df = None

    def pre_run(self, options_db: OptionsDatabase, quote_dates):
        if self.high_vol_check_required:
            self.external_df = pull_external_data(
                quote_dates, args.high_vol_check_window
            )

    def in_high_vol_regime(self, quote_date) -> bool:
        high_vol_regime_flag = False
        try:
            signal_value = self.external_df.loc[quote_date, "High_Vol_Signal"]
            if signal_value == 1:
                high_vol_regime_flag = False
            else:
                logging.debug(
                    f"High Vol environment. The Signal value for {quote_date} is {signal_value}"
                )
                high_vol_regime_flag = True
        except KeyError:
            logging.debug(f"Date {quote_date} not found in DataFrame.")

        return high_vol_regime_flag

    def allowed_to_create_new_trade(
        self, options_db, data_for_trade_management: DataForTradeManagement
    ):
        allowed_based_on_default_checks = super().allowed_to_create_new_trade(
            options_db, data_for_trade_management
        )
        if not allowed_based_on_default_checks:
            return False

        if not self.high_vol_check_required:
            return True

        return self.in_high_vol_regime(data_for_trade_management.quote_date)

    def build_trade(self, options_db, quote_date) -> Optional[Trade]:
        expiry_dte, dte_found = options_db.get_next_expiry_by_dte(quote_date, self.dte)
        if not expiry_dte:
            logging.warning(f"⚠️ Unable to find {self.dte} expiry. {expiry_dte=}")
            return None

        logging.debug(f"Quote date: {quote_date} -> {expiry_dte=} ({dte_found=:.1f}), ")

        od: OptionsData = options_db.get_options_data_closest_to_price(
            quote_date, expiry_dte
        )
        if not od or od.p_last in [None, 0] or od.c_last in [None, 0]:
            logging.warning(
                "⚠️ Bad data found: "
                + (
                    "One or more options are not valid"
                    if not od
                    else f"On {quote_date=}, one of {od.c_last=}, {od.p_last=} is not valid"
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
            Leg(
                leg_quote_date=quote_date,
                leg_expiry_date=expiry_dte,
                leg_type=LegType.TRADE_OPEN,
                position_type=PositionType.SHORT,
                contract_type=ContractType.CALL,
                strike_price=od.strike,
                underlying_price_open=od.underlying_last,
                premium_open=od.c_last,
                premium_current=0,
                delta=od.c_delta,
                gamma=od.c_gamma,
                vega=od.c_vega,
                theta=od.c_theta,
                iv=od.c_iv,
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
    if args.high_vol_check:
        table_tag = f"short_straddle_dte_{args.dte}_{args.high_vol_check_window}_{args.force_close_after_days}"
    elif args.force_close_after_days:
        table_tag = f"short_straddle_dte_{args.dte}_{args.force_close_after_days}"
    else:
        table_tag = f"short_straddle_dte_{args.dte}"

    with ShortStraddleStrategy(args, table_tag) as runner:
        runner.run()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
