#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "pandas"
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

from logger import setup_logging
from options_analysis import (
    ContractType,
    GenericRunner,
    Leg,
    LegType,
    PositionType,
    Trade,
)


def parse_args():
    parser = ArgumentParser(
        description=__doc__, formatter_class=RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        dest="verbose",
        help="Increase verbosity of logging output",
    )
    parser.add_argument(
        "--db-path",
        required=True,
        help="Path to the SQLite database file",
    )
    parser.add_argument(
        "--dte",
        type=int,
        default=30,
        help="Option DTE",
    )
    parser.add_argument(
        "--max-open-trades",
        type=int,
        default=99,
        help="Maximum number of open trades allowed at a given time",
    )
    parser.add_argument(
        "--trade-delay",
        type=int,
        default=-1,
        help="Minimum number of days to wait between new trades",
    )
    parser.add_argument(
        "-sd",
        "--start-date",
        type=str,
        help="Start date for backtesting",
    )
    parser.add_argument(
        "-ed",
        "--end-date",
        type=str,
        help="End date for backtesting",
    )
    parser.add_argument(
        "--profit-take",
        type=float,
        help="Close position when profit reaches this percentage of premium received",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        help="Close position when loss reaches this percentage of premium received",
    )
    return parser.parse_args()


class ShortStraddleStrategy(GenericRunner):
    def build_trade(self, options_db, quote_date, dte):
        expiry_dte, dte_found = options_db.get_next_expiry_by_dte(quote_date, dte)
        if not expiry_dte:
            logging.warning(f"⚠️ Unable to find {dte} expiry. {expiry_dte=}")
            return None

        logging.debug(f"Quote date: {quote_date} -> {expiry_dte=} ({dte_found=:.1f}), ")
        call_df, put_df = options_db.get_options_by_delta(quote_date, expiry_dte)
        logging.debug(f"CALL OPTION: \n {call_df.to_string(index=False)}")
        logging.debug(f"PUT OPTION: \n {put_df.to_string(index=False)}")

        if call_df.empty or put_df.empty:
            logging.warning(
                "⚠️ One or more options are not valid. Re-run with debug to see options found for selected DTEs"
            )
            return None

        underlying_price = call_df["UNDERLYING_LAST"].iloc[0]
        strike_price = call_df["CALL_STRIKE"].iloc[0]
        call_price = call_df["CALL_C_LAST"].iloc[0]
        put_price = put_df["PUT_P_LAST"].iloc[0]

        # Extract Put Option Greeks
        call_delta = call_df["CALL_C_DELTA"].iloc[0]
        call_gamma = call_df["CALL_C_GAMMA"].iloc[0]
        call_vega = call_df["CALL_C_VEGA"].iloc[0]
        call_theta = call_df["CALL_C_THETA"].iloc[0]
        call_iv = call_df["CALL_C_IV"].iloc[0]

        # Extract Put Option Greeks
        put_delta = put_df["PUT_P_DELTA"].iloc[0]
        put_gamma = put_df["PUT_P_GAMMA"].iloc[0]
        put_vega = put_df["PUT_P_VEGA"].iloc[0]
        put_theta = put_df["PUT_P_THETA"].iloc[0]
        put_iv = put_df["PUT_P_IV"].iloc[0]

        if put_price in [None, 0] or call_price in [None, 0]:
            logging.warning(
                f"⚠️ Bad data found on {quote_date=}. One of {call_price=}, {put_price=} is not valid."
            )
            return None

        logging.debug(
            f"Contract ({expiry_dte=}): {underlying_price=:.2f}, {strike_price=:.2f}, {call_price=:.2f}, {put_price=:.2f}"
        )

        # create a multi leg trade in database
        trade_legs = [
            Leg(
                leg_quote_date=quote_date,
                leg_expiry_date=expiry_dte,
                leg_type=LegType.TRADE_OPEN,
                position_type=PositionType.SHORT,
                contract_type=ContractType.PUT,
                strike_price=strike_price,
                underlying_price_open=underlying_price,
                premium_open=put_price,
                premium_current=0,
                delta=put_delta,
                gamma=put_gamma,
                vega=put_vega,
                theta=put_theta,
                iv=put_iv,
            ),
            Leg(
                leg_quote_date=quote_date,
                leg_expiry_date=expiry_dte,
                leg_type=LegType.TRADE_OPEN,
                position_type=PositionType.SHORT,
                contract_type=ContractType.CALL,
                strike_price=strike_price,
                underlying_price_open=underlying_price,
                premium_open=call_price,
                premium_current=0,
                delta=call_delta,
                gamma=call_gamma,
                vega=call_vega,
                theta=call_theta,
                iv=call_iv,
            ),
        ]

        premium_captured_calculated = round(
            sum(leg.premium_open for leg in trade_legs), 2
        )

        return Trade(
            trade_date=quote_date,
            expire_date=expiry_dte,
            dte=dte,
            status="OPEN",
            premium_captured=premium_captured_calculated,
            legs=trade_legs,
        )


def main(args):
    with ShortStraddleStrategy(args) as runner:
        runner.run()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
