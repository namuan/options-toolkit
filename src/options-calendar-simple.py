#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "pandas"
# ]
# ///
"""
Options Straddle Analysis Script

Usage:
./options-straddle-simple.py -h

./options-straddle-simple.py -v # To log INFO messages
./options-straddle-simple.py -vv # To log DEBUG messages
./options-straddle-simple.py --db-path path/to/database.db # Specify database path
./options-straddle-simple.py --dte 30 # Find next expiration with DTE > 30 for each quote date
./options-straddle-simple.py --trade-delay 7 # Wait 7 days between new trades
"""

import logging
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from datetime import datetime
from typing import Optional

import pandas as pd

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

pd.set_option("display.float_format", lambda x: "%.4f" % x)


def update_open_trades(db, quote_date):
    """Update all open trades with current prices"""
    open_trades = db.get_open_trades()

    for _, trade in open_trades.iterrows():
        existing_trade_id = trade["TradeId"]
        existing_trade = db.load_trade_with_multiple_legs(
            existing_trade_id, leg_type=LegType.TRADE_OPEN
        )

        trade_can_be_closed = False

        if quote_date >= trade["ExpireDate"]:
            trade_can_be_closed = True

        updated_legs = []

        for leg in existing_trade.legs:
            od: OptionsData = db.get_current_options_data(
                quote_date, leg.strike_price, leg.leg_expiry_date
            )

            if not od:
                logging.warning(
                    f"⚠️ Unable to find options data for {quote_date=}, {leg.strike_price=}, {leg.leg_expiry_date=}"
                )
                continue

            if any(
                price is None for price in (od.underlying_last, od.c_last, od.p_last)
            ):
                logging.warning(
                    f"⚠️ Bad data found on {quote_date}. One of {od.underlying_last=}, {od.c_last=}, {od.p_last=} is missing"
                )
                continue

            updated_leg = Leg(
                leg_quote_date=quote_date,
                leg_expiry_date=leg.leg_expiry_date,
                contract_type=leg.contract_type,
                position_type=leg.position_type,
                strike_price=leg.strike_price,
                underlying_price_open=leg.underlying_price_open,
                premium_open=leg.premium_open,
                underlying_price_current=od.underlying_last,
                premium_current=od.p_last,
                leg_type=LegType.TRADE_CLOSE
                if trade_can_be_closed
                else LegType.TRADE_AUDIT,
                delta=od.p_delta,
                gamma=od.p_gamma,
                vega=od.p_vega,
                theta=od.p_theta,
                iv=od.p_iv,
            )
            updated_legs.append(updated_leg)
            db.update_trade_leg(existing_trade_id, updated_leg)

        # If trade has reached expiry date, close it
        if trade_can_be_closed:
            logging.debug(
                f"Trying to close trade {trade['TradeId']} at expiry {quote_date}"
            )
            # Multiply by -1 because we reverse the positions (Buying back Short option and Selling Long option)
            existing_trade.closing_premium = round(
                -1 * sum(l.premium_current for l in updated_legs), 2
            )
            existing_trade.closed_trade_at = quote_date
            existing_trade.close_reason = "EXPIRED"
            db.close_trade(existing_trade_id, existing_trade)
            logging.info(
                f"Closed trade {trade['TradeId']} with {existing_trade.closing_premium} at expiry"
            )
        else:
            logging.debug(
                f"Trade {trade['TradeId']} still open as {quote_date} < {trade['ExpireDate']}"
            )


def can_create_new_trade(db, quote_date, trade_delay_days):
    """Check if enough time has passed since the last trade"""
    if trade_delay_days < 0:
        return True

    last_open_trade = db.get_last_open_trade()

    if last_open_trade.empty:
        logging.debug("No open trades found. Can create new trade.")
        return True

    last_trade_date = last_open_trade["Date"].iloc[0]

    last_trade_date = datetime.strptime(last_trade_date, "%Y-%m-%d").date()
    quote_date = datetime.strptime(quote_date, "%Y-%m-%d").date()

    days_since_last_trade = (quote_date - last_trade_date).days

    if days_since_last_trade >= trade_delay_days:
        logging.info(
            f"Days since last trade: {days_since_last_trade}. Can create new trade."
        )
        return True
    else:
        logging.debug(
            f"Only {days_since_last_trade} days since last trade. Waiting for {trade_delay_days} days."
        )
        return False


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
