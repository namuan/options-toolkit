#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "pandas"
# ]
# ///
import logging
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from typing import Optional

from logger import setup_logging
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
        "--front-dte",
        type=int,
        default=30,
        help="Front Option DTE",
    )
    parser.add_argument(
        "--back-dte",
        type=int,
        default=60,
        help="Back Option DTE",
    )
    return parser.parse_args()


class LongPutCalendarStrategy(GenericRunner):
    def __init__(self, args):
        super().__init__(args)
        self.front_dte = args.front_dte
        self.back_dte = args.back_dte

    def build_trade(self, options_db: OptionsDatabase, quote_date) -> Optional[Trade]:
        expiry_front_dte, front_dte_found = options_db.get_next_expiry_by_dte(
            quote_date, self.front_dte
        )

        expiry_back_dte, back_dte_found = options_db.get_next_expiry_by_dte(
            quote_date, self.back_dte
        )

        if not expiry_front_dte or not expiry_back_dte:
            logging.warning(
                f"⚠️ Unable to find front {self.front_dte} or back {self.back_dte} expiry. {expiry_front_dte=}, {expiry_back_dte=} "
            )
            return None

        logging.debug(
            f"Quote date: {quote_date} -> {expiry_front_dte=} ({front_dte_found=:.1f}), "
            f"{expiry_back_dte=} ({back_dte_found=:.1f})"
        )

        front_od: OptionsData = options_db.get_options_data_closest_to_price(
            quote_date, expiry_front_dte
        )
        back_od: OptionsData = options_db.get_options_data_closest_to_price(
            quote_date, expiry_back_dte
        )

        if not front_od or not back_od:
            logging.warning(
                "⚠️ One or more options are not valid. Re-run with debug to see options found for selected DTEs"
            )
            return None

        if front_od.p_last is None or back_od.p_last is None:
            logging.warning(
                f"⚠️ Bad data found on {quote_date}. One of {front_od.p_last=}, {back_od.p_last=} is not valid."
            )
            return None

        trade_legs = [
            Leg(
                leg_quote_date=quote_date,
                leg_expiry_date=expiry_front_dte,
                leg_type=LegType.TRADE_OPEN,
                position_type=PositionType.SHORT,
                contract_type=ContractType.PUT,
                strike_price=front_od.strike,
                underlying_price_open=front_od.underlying_last,
                premium_open=front_od.p_last,
                premium_current=0,
                delta=front_od.p_delta,
                gamma=front_od.p_gamma,
                vega=front_od.p_vega,
                theta=front_od.p_theta,
                iv=front_od.p_iv,
            ),
            Leg(
                leg_quote_date=quote_date,
                leg_expiry_date=expiry_back_dte,
                leg_type=LegType.TRADE_OPEN,
                position_type=PositionType.LONG,
                contract_type=ContractType.PUT,
                strike_price=back_od.strike,
                underlying_price_open=back_od.underlying_last,
                premium_open=back_od.p_last,
                premium_current=0,
                delta=back_od.p_delta,
                gamma=back_od.p_gamma,
                vega=back_od.p_vega,
                theta=back_od.p_theta,
                iv=back_od.p_iv,
            ),
        ]
        premium_captured_calculated = round(
            sum(leg.premium_open for leg in trade_legs), 2
        )
        return Trade(
            trade_date=quote_date,
            expire_date=expiry_front_dte,
            dte=self.front_dte,
            status="OPEN",
            premium_captured=premium_captured_calculated,
            legs=trade_legs,
        )


def main(args):
    with LongPutCalendarStrategy(args) as strategy:
        strategy.run()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
