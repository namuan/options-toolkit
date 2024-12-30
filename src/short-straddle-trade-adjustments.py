#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "pandas",
# ]
# ///
"""
The script identifies trades that require adjustments.
It uses the current price of the underlying asset to determine this.
The current price is compared to the breakeven points of the trade.
The script calculates the distance from the breakeven point.
It also calculates the percentage distance.
Finally, the results are displayed in a formatted table.

Usage:
./short_straddle_trade_adjustments.py -h

./short_straddle_trade_adjustments.py --db-path /path/to/database.db --strategy-name "StrategyA" --table-name-key "TableKey" --trade-id 123 -v # To log INFO messages
./short_straddle_trade_adjustments.py --db-path /path/to/database.db --strategy-name "StrategyA" --table-name-key "TableKey" --trade-id 123 -vv # To log DEBUG messages
"""

from argparse import ArgumentParser, RawDescriptionHelpFormatter
from dataclasses import dataclass
from datetime import date

from options_analysis import ContractType, OptionsDatabase, PositionType
from src.logger import setup_logging


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
        "--db-path", required=True, help="Path to the SQLite database file"
    )
    parser.add_argument(
        "--strategy-name",
        type=str,
        required=True,
        help="Name of the strategy to visualize",
    )
    parser.add_argument(
        "--table-name-key",
        type=str,
        required=True,
        help="Table name key to help with reporting filter",
    )
    return parser.parse_args()


@dataclass
class AdjustedTrade:
    strike_price: float
    trade_date: date
    option_type: str
    current_price: float
    breakeven_to_consider: float
    distance_from_breakeven: float
    distance_percentage: float


def _get_db(args) -> OptionsDatabase:
    return OptionsDatabase(args.db_path, args.strategy_name, args.table_name_key)


def main(args):
    trades = {}  # Initialize empty dict first
    with _get_db(args) as db:
        for trade in db.load_all_trades():
            trades[trade.id] = trade

    adjusted_trades = {}

    for trade_id, trade in trades.items():
        lower_breakeven, higher_breakeven = trade.breakeven()
        for leg in trade.legs:
            current_price = leg.underlying_price_current
            strike_price = leg.strike_price
            adjustment_required = False
            breakeven_to_consider = None
            if (
                leg.contract_type is ContractType.PUT
                and leg.position_type is PositionType.SHORT
            ):
                if (
                    lower_breakeven
                    and current_price
                    and current_price < lower_breakeven
                ):
                    adjustment_required = True
                    breakeven_to_consider = lower_breakeven

            if (
                leg.contract_type is ContractType.CALL
                and leg.position_type is PositionType.SHORT
            ):
                if (
                    higher_breakeven
                    and current_price
                    and current_price > higher_breakeven
                ):
                    adjustment_required = True
                    breakeven_to_consider = higher_breakeven

            if adjustment_required:
                distance_from_breakeven = abs(current_price - breakeven_to_consider)
                distance_from_breakeven_percent = (
                    distance_from_breakeven / current_price * 100
                )
                existing_adjusted_trade = adjusted_trades.get(trade_id, None)

                if (
                    existing_adjusted_trade is None
                    or distance_from_breakeven
                    > existing_adjusted_trade.distance_from_breakeven
                ):
                    adjusted_trades[trade_id] = AdjustedTrade(
                        strike_price=strike_price,
                        trade_date=trade.trade_date,
                        option_type=f"{leg.position_type.value} {leg.contract_type.value}",
                        current_price=current_price,
                        breakeven_to_consider=breakeven_to_consider,
                        distance_from_breakeven=distance_from_breakeven,
                        distance_percentage=distance_from_breakeven_percent,
                    )

    print(
        "| Adjusted Trade ID | Strike Price | Trade Date | Option Type | Current Price | Breakeven | Distance from Breakeven | Distance Percentage |"
    )
    print(
        "|-------------------|--------------|------------|-------------|---------------|-----------|-------------------------|---------------------|"
    )

    for adjusted_trade_id, trade in adjusted_trades.items():
        print(
            f"| {adjusted_trade_id} | {trade.strike_price} | {trade.trade_date} | {trade.option_type} | "
            f"{trade.current_price} | {trade.breakeven_to_consider:.2f} | {trade.distance_from_breakeven:.2f} | "
            f"{trade.distance_percentage:.2f}% |"
        )


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
