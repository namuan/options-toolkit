import logging
import sqlite3
import unittest
from argparse import Namespace
from pathlib import Path
from typing import Optional

from options_analysis import (
    GenericRunner,
    OptionsDatabase,
    Trade,
    calculate_legs_for_straddle,
)


class ShortStraddleStaggeredEntryStrategy(GenericRunner):
    def __init__(self, args):
        super().__init__(args)
        self.dte = args.dte
        self.total_contracts = args.no_contracts

    def build_trade(self, options_db, quote_date) -> Optional[Trade]:
        expiry_dte, dte_found = options_db.get_next_expiry_by_dte(quote_date, self.dte)
        if not expiry_dte:
            logging.warning(f"⚠️ Unable to find {self.dte} expiry. {expiry_dte=}")
            return None

        logging.debug(f"Quote date: {quote_date} -> {expiry_dte=} ({dte_found=:.1f}), ")

        trade_legs, premium = calculate_legs_for_straddle(
            options_db, quote_date, expiry_dte
        )

        if not trade_legs or len(trade_legs) == 0:
            return None

        return Trade(
            trade_date=quote_date,
            expire_date=expiry_dte,
            dte=self.dte,
            status="OPEN",
            premium_captured=premium,
            legs=trade_legs,
        )

    def adjust_trade(
        self, db: OptionsDatabase, existing_trade: Trade, quote_date
    ) -> Trade:
        existing_expiry = existing_trade.expire_date
        # Make sure we only allow the specified number of contracts
        if len(existing_trade.legs) >= (self.total_contracts * 2):
            return existing_trade

        new_legs, premium = calculate_legs_for_straddle(db, quote_date, existing_expiry)
        for nl in new_legs:
            existing_trade.legs.append(nl)
        existing_trade.premium_captured = existing_trade.premium_captured + premium
        return existing_trade


class TestShortStraddleStaggeredEntryStrategy(unittest.TestCase):
    def setUp(self):
        self.no_contracts = 2
        self.dte = 30
        self.db_path = Path().cwd().parent / "data" / "test_spx_eod.db"
        self.args = Namespace(
            dte=self.dte,
            db_path=self.db_path,
            max_open_trades=1,
            trade_delay=None,
            force_close_after_days=None,
            start_date=None,
            end_date=None,
            profit_take=None,
            stop_loss=None,
            no_contracts=self.no_contracts,
        )
        assert self.db_path.exists()
        self.prepare_database()

    def prepare_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM backtest_runs")
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'trade%'"
        )
        trade_tables = cursor.fetchall()
        for table in trade_tables:
            cursor.execute(f"DROP TABLE {table[0]}")
        conn.commit()
        conn.close()

    def test_build_trade_creates_valid_trade(self):
        with ShortStraddleStaggeredEntryStrategy(self.args) as runner:
            runner.run()

        self._assert_database_state()

    def _assert_database_state(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get all rows from backtest_runs table
        cursor.execute("SELECT TradeTableName, TradeLegsTableName FROM backtest_runs")
        rows = cursor.fetchall()

        # Assert that there is exactly one row
        self.assertEqual(
            len(rows), 1, "Expected exactly one row in backtest_runs table"
        )

        # Get the table names from the row
        trade_table_name, trade_legs_table_name = rows[0]

        # Store them as instance variables for potential future use
        self.trade_table_name = trade_table_name
        self.trade_legs_table_name = trade_legs_table_name

        # Count rows in the trade table
        cursor.execute(
            f"SELECT COUNT(*) FROM {self.trade_table_name} WHERE Status='CLOSED'"
        )
        trade_count = cursor.fetchone()[0]
        self.assertEqual(
            trade_count,
            1,
            f"Expected exactly 1 CLOSED trade in {self.trade_table_name} table",
        )

        # Count trade legs for TradeId 1 on 5th day
        # Expect it to be no_contracts * 2
        legs_expected = self.no_contracts * 2
        cursor.execute(
            f"SELECT COUNT(*) FROM {self.trade_legs_table_name} WHERE Date = '2020-01-08'"
        )
        legs_count = cursor.fetchone()[0]
        self.assertEqual(legs_count, legs_expected, f"Expected {legs_expected} legs")

        # Get trade details
        cursor.execute(f"SELECT * FROM {self.trade_table_name} WHERE TradeId = 1")
        columns = [description[0] for description in cursor.description]
        row = cursor.fetchone()
        trade = dict(zip(columns, row))

        self.assertEqual(trade["TradeId"], 1)
        self.assertEqual(trade["Date"], "2020-01-02")
        self.assertEqual(trade["ExpireDate"], "2020-02-03")
        self.assertEqual(trade["DTE"], 30)
        self.assertEqual(trade["Status"], "CLOSED")
        self.assertEqual(trade["PremiumCaptured"], 158.37)
        self.assertEqual(trade["ClosingPremium"], -33.16)
        self.assertEqual(trade["ClosedTradeAt"], "2020-02-03")
        self.assertEqual(trade["CloseReason"], "EXPIRED")

        conn.close()


if __name__ == "__main__":
    unittest.main()
