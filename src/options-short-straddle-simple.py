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
    OptionsData,
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
    return parser.parse_args()


class ShortStraddleStrategy(GenericRunner):
    def build_trade(self, options_db, quote_date, dte):
        expiry_dte, dte_found = options_db.get_next_expiry_by_dte(quote_date, dte)
        if not expiry_dte:
            logging.warning(f"⚠️ Unable to find {dte} expiry. {expiry_dte=}")
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
            dte=dte,
            status="OPEN",
            premium_captured=premium_captured_calculated,
            legs=trade_legs,
        )


def main(args):
    table_tag = f"short_straddle_dte_{args.dte}"
    with ShortStraddleStrategy(args, table_tag) as runner:
        runner.run()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
