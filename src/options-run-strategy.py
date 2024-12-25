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
from dataclasses import dataclass
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
        default=30.0,
        help="Close position when profit reaches this percentage of premium received",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=100.0,
        help="Close position when loss reaches this percentage of premium received",
    )
    return parser.parse_args()


pd.set_option("display.float_format", lambda x: "%.4f" % x)


@dataclass
class DataForTradeManagement:
    max_open_trades: int
    trade_delay: int
    profit_take: float
    stop_loss: float
    quote_date: str


def check_profit_take_stop_loss_targets(
    profit_take, stop_loss, existing_trade, updated_legs
):
    current_premium_value = round(sum(l.premium_current for l in updated_legs), 2)
    total_premium_received = existing_trade.premium_captured
    premium_diff = total_premium_received - current_premium_value
    logging.info(
        f"Premium Diff: {total_premium_received=} + {current_premium_value=} = {premium_diff=}"
    )
    # Calculate percentage gain/loss
    premium_diff_pct = (premium_diff / total_premium_received) * 100
    logging.info(
        f"Trade {existing_trade.id}: Premium Diff: {premium_diff=}/{total_premium_received=} * 100 = {premium_diff_pct=}"
    )
    # Profit take: If we've captured the specified percentage of the premium received
    if premium_diff_pct >= profit_take:
        return "PROFIT_TAKE", True
    # Stop loss: If we've lost the specified percentage of the premium received
    if premium_diff_pct <= -stop_loss:
        return "STOP_LOSS", True

    return "UNKNOWN", False


def bad_options_data(quote_date, od: OptionsData) -> bool:
    if not od:
        logging.warning(f"⚠️ Unable to find options data for {quote_date=}")
        return True

    if any(price is None for price in (od.underlying_last, od.c_last, od.p_last)):
        logging.warning(
            f"⚠️ Bad data found on {quote_date}. One of {od.underlying_last=}, {od.c_last=}, {od.p_last=} is missing"
        )
        return True
    return False


def update_legs_with_latest_data(db, existing_trade, quote_date):
    updated_legs = []
    for leg in existing_trade.legs:
        od: OptionsData = db.get_current_options_data(
            quote_date, leg.strike_price, leg.leg_expiry_date
        )

        if bad_options_data(quote_date, od):
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
            premium_current=od.p_last
            if leg.contract_type is ContractType.PUT
            else od.c_last,
            leg_type=LegType.TRADE_AUDIT,
            delta=od.p_delta if leg.contract_type is ContractType.PUT else od.c_delta,
            gamma=od.p_gamma if leg.contract_type is ContractType.PUT else od.c_gamma,
            vega=od.p_vega if leg.contract_type is ContractType.PUT else od.c_vega,
            theta=od.p_theta if leg.contract_type is ContractType.PUT else od.c_theta,
            iv=od.p_iv if leg.contract_type is ContractType.PUT else od.c_iv,
        )
        logging.debug(
            f"Updating leg {leg.position_type.value} {leg.contract_type.value} -> {updated_leg.premium_current}"
        )
        updated_legs.append(updated_leg)
    return updated_legs


# abstract
def can_create_new_trade(options_db, quote_date, trade_delay):
    """Check if enough time has passed since the last trade"""
    if trade_delay < 0:
        return True

    last_open_trade = options_db.get_last_open_trade()

    if last_open_trade.empty:
        logging.debug("No open trades found. Can create new trade.")
        return True

    last_trade_date = last_open_trade["Date"].iloc[0]

    last_trade_date = datetime.strptime(last_trade_date, "%Y-%m-%d").date()
    quote_date = datetime.strptime(quote_date, "%Y-%m-%d").date()

    days_since_last_trade = (quote_date - last_trade_date).days

    if days_since_last_trade >= trade_delay:
        logging.info(
            f"Days since last trade: {days_since_last_trade}. Can create new trade."
        )
        return True
    else:
        logging.debug(
            f"Only {days_since_last_trade} days since last trade. Waiting for {trade_delay} days."
        )
        return False


# abstract
def allowed_to_create_new_trade(options_db, data_for_trade_management):
    open_trades = options_db.get_open_trades()
    if len(open_trades) >= data_for_trade_management.max_open_trades:
        logging.debug(
            f"Maximum number of open trades ({data_for_trade_management.max_open_trades}) reached. Skipping new trade creation."
        )
        return False

    return can_create_new_trade(
        options_db,
        data_for_trade_management.quote_date,
        data_for_trade_management.trade_delay,
    )


# abstract
def build_trade(options_db, quote_date, dte):
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

    premium_captured_calculated = round(sum(leg.premium_open for leg in trade_legs), 2)

    return Trade(
        trade_date=quote_date,
        expire_date=expiry_dte,
        dte=dte,
        status="OPEN",
        premium_captured=premium_captured_calculated,
        legs=trade_legs,
    )


# abstract
def check_if_trade_can_be_closed(
    data_for_trade_management, existing_trade: Trade, updated_legs
):
    close_reason, trade_can_be_closed = check_profit_take_stop_loss_targets(
        data_for_trade_management.profit_take,
        data_for_trade_management.stop_loss,
        existing_trade,
        updated_legs,
    )
    if trade_can_be_closed:
        return close_reason, True

    if data_for_trade_management.quote_date >= existing_trade.expire_date:
        return "EXPIRED", True

    return "", False


def main(args):
    dte = args.dte
    table_tag = f"generic_dte_{dte}"
    db = OptionsDatabase(args.db_path, table_tag)
    db.connect()

    try:
        db.setup_trades_table()
        quote_dates = db.get_quote_dates(args.start_date, args.end_date)

        for quote_date in quote_dates:
            logging.info(f"Processing {quote_date}")
            data_for_trade_management = DataForTradeManagement(
                args.max_open_trades,
                args.trade_delay,
                args.profit_take,
                args.stop_loss,
                quote_date,
            )

            # Update Open Trades
            open_trades = db.get_open_trades()

            for _, trade in open_trades.iterrows():
                existing_trade_id = trade["TradeId"]
                existing_trade = db.load_trade_with_multiple_legs(
                    existing_trade_id, leg_type=LegType.TRADE_OPEN
                )
                logging.debug(f"Updating existing trade {existing_trade_id}")

                updated_legs = update_legs_with_latest_data(
                    db, existing_trade, data_for_trade_management.quote_date
                )

                close_reason, trade_can_be_closed = check_if_trade_can_be_closed(
                    data_for_trade_management, existing_trade, updated_legs
                )

                for leg in updated_legs:
                    leg.leg_type = (
                        LegType.TRADE_CLOSE
                        if trade_can_be_closed
                        else LegType.TRADE_AUDIT
                    )
                    db.update_trade_leg(existing_trade_id, leg)

                if trade_can_be_closed:
                    logging.debug(
                        f"Trying to close trade {trade['TradeId']} at expiry {data_for_trade_management.quote_date}"
                    )
                    # Multiply by -1 because we reverse the positions (Buying back Short option and Selling Long option)
                    existing_trade.closing_premium = round(
                        -1 * sum(l.premium_current for l in updated_legs), 2
                    )
                    existing_trade.closed_trade_at = (
                        data_for_trade_management.quote_date
                    )
                    existing_trade.close_reason = close_reason
                    db.close_trade(existing_trade_id, existing_trade)
                    logging.info(
                        f"Closed trade {trade['TradeId']} with {existing_trade.closing_premium} at expiry"
                    )
                else:
                    logging.debug(
                        f"Trade {trade['TradeId']} still open as {data_for_trade_management.quote_date} < {trade['ExpireDate']}"
                    )

            if not allowed_to_create_new_trade(db, data_for_trade_management):
                continue

            trade_to_setup = build_trade(db, quote_date, dte)
            if not trade_to_setup:
                continue

            trade_id = db.create_trade_with_multiple_legs(trade_to_setup)
            logging.info(f"Trade {trade_id} created in database")

    finally:
        db.disconnect()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
