#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "pandas"
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
from datetime import datetime

import pandas as pd

from logger import setup_logging
from options_analysis import (
    ContractType,
    Leg,
    LegType,
    OptionsData,
    OptionsDatabase,
    PositionType,
    Trade,
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
    return parser.parse_args()


def main(args):
    dte = args.dte
    db = OptionsDatabase(args.db_path, dte)
    db.connect()

    try:
        db.setup_trades_table()
        quote_dates = db.get_quote_dates(args.start_date, args.end_date)

        for quote_date in quote_dates:
            logging.info(f"Processing {quote_date}")

            update_open_trades(db, quote_date)

            # Check if maximum number of open trades has been reached
            open_trades = db.get_open_trades()
            if len(open_trades) >= args.max_open_trades:
                logging.debug(
                    f"Maximum number of open trades ({args.max_open_trades}) reached. Skipping new trade creation."
                )
                continue

            expiry_dte, dte_found = db.get_next_expiry_by_dte(quote_date, dte)
            if not expiry_dte:
                logging.warning(f"⚠️ Unable to find {dte} expiry. {expiry_dte=}")
                continue

            logging.debug(
                f"Quote date: {quote_date} -> {expiry_dte=} ({dte_found=:.1f}), "
            )
            call_df, put_df = db.get_options_by_delta(quote_date, expiry_dte)

            # Only look at PUTs For now. We are only looking at Calendar PUT Spread
            logging.debug("Option")
            logging.debug(f"=> PUT OPTION: \n {put_df.to_string(index=False)}")

            if put_df.empty:
                logging.warning(
                    "⚠️ One or more options are not valid. Re-run with debug to see options found for selected DTEs"
                )
                continue

            underlying_price = call_df["UNDERLYING_LAST"].iloc[0]
            strike_price = call_df["CALL_STRIKE"].iloc[0]
            call_price = call_df["CALL_C_LAST"].iloc[0]
            put_price = put_df["PUT_P_LAST"].iloc[0]

            # Extract Put Option Greeks
            put_delta = put_df["PUT_P_DELTA"].iloc[0]
            put_gamma = put_df["PUT_P_GAMMA"].iloc[0]
            put_vega = put_df["PUT_P_VEGA"].iloc[0]
            put_theta = put_df["PUT_P_THETA"].iloc[0]
            put_iv = put_df["PUT_P_IV"].iloc[0]

            if call_price is None or put_price is None:
                logging.warning(
                    f"⚠️ Bad data found on {quote_date}. One of {call_price}, {put_price} is not valid."
                )
                continue

            logging.debug(
                f"Contract (Expiry {expiry_dte}): Underlying Price={underlying_price:.2f}, Strike Price={strike_price:.2f}, Call Price={call_price:.2f}, Put Price={put_price:.2f}"
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
            ]
            premium_captured_calculated = round(
                sum(leg.premium_open for leg in trade_legs), 2
            )
            trade = Trade(
                trade_date=quote_date,
                expire_date=expiry_dte,
                dte=dte,
                status="OPEN",
                premium_captured=premium_captured_calculated,
                legs=trade_legs,
            )
            trade_id = db.create_trade_with_multiple_legs(trade)
            logging.info(f"Trade {trade_id} created in database")

    finally:
        db.disconnect()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
