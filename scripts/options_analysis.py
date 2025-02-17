import argparse
import dataclasses
import logging
import sqlite3
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

import pandas as pd


def calculate_date_difference(
    date_str1, date_str2, date_format="%Y-%m-%d", unit="days"
):
    date1 = datetime.strptime(date_str1, date_format)
    date2 = datetime.strptime(date_str2, date_format)

    # Calculate the difference as a timedelta object
    delta = date2 - date1

    # Convert the difference based on the specified unit
    if unit == "days":
        return delta.days
    elif unit == "hours":
        return delta.total_seconds() / 3600
    elif unit == "minutes":
        return delta.total_seconds() / 60
    elif unit == "seconds":
        return delta.total_seconds()
    else:
        raise ValueError(
            f"Unsupported unit: {unit}. Use 'days', 'hours', 'minutes', or 'seconds'."
        )


class ContractType(Enum):
    CALL = "Call"
    PUT = "Put"


class PositionType(Enum):
    LONG = "Long"
    SHORT = "Short"


class LegType(Enum):
    TRADE_OPEN = "TradeOpen"
    TRADE_AUDIT = "TradeAudit"
    TRADE_CLOSE = "TradeClose"


@dataclass
class Leg:
    """Represents a single leg of a trade (call or put)."""

    leg_quote_date: date
    leg_expiry_date: date
    contract_type: ContractType
    position_type: PositionType
    leg_type: LegType
    strike_price: float
    underlying_price_open: float
    premium_open: float = field(init=True)
    underlying_price_current: Optional[float] = None
    premium_current: Optional[float] = field(default=None)
    delta: Optional[float] = None
    gamma: Optional[float] = None
    vega: Optional[float] = None
    theta: Optional[float] = None
    iv: Optional[float] = None
    historyId: Optional[str] = None

    def __post_init__(self):
        # Convert premiums after initialization
        self.premium_open = (
            -abs(self.premium_open)
            if self.position_type == PositionType.LONG
            else abs(self.premium_open)
        )
        if self.premium_current is not None:
            self.premium_current = (
                -abs(self.premium_current)
                if self.position_type == PositionType.LONG
                else abs(self.premium_current)
            )

    def __str__(self):
        leg_str = [
            f"\n    {self.position_type.value} {self.contract_type.value}",
            f"\n      HistoryId: {self.historyId}",
            f"\n      Date: {self.leg_quote_date}",
            f"\n      Expiry Date: {self.leg_expiry_date}",
            f"\n      Strike: ${self.strike_price:,.2f}",
            f"\n      Underlying Open: ${self.underlying_price_open:,.2f}",
            f"\n      Premium Open: ${self.premium_open:,.2f}",
            f"\n      Leg Type: {self.leg_type.value}",
        ]

        if self.underlying_price_current is not None:
            leg_str.append(
                f"\n      Underlying Current: ${self.underlying_price_current:,.2f}"
            )

        if self.premium_current is not None:
            leg_str.append(f"\n      Premium Current: ${self.premium_current:,.2f}")

        if self.delta is not None:
            leg_str.append(f"\n      Delta: {self.delta:.4f}")

        if self.gamma is not None:
            leg_str.append(f"\n      Gamma: {self.gamma:.4f}")

        if self.vega is not None:
            leg_str.append(f"\n      Vega: {self.vega:.4f}")

        if self.theta is not None:
            leg_str.append(f"\n      Theta: {self.theta:.4f}")

        if self.iv is not None:
            leg_str.append(f"\n      IV: {self.iv:.2%}")

        return "".join(leg_str)


@dataclass
class Trade:
    """Represents a trade."""

    trade_date: date
    expire_date: date
    dte: int
    status: str
    premium_captured: float
    closing_premium: Optional[float] = None
    closed_trade_at: Optional[str] = None
    close_reason: Optional[str] = None
    legs: List[Leg] = field(default_factory=list)
    id: Optional[str] = None

    def breakeven(self) -> Tuple[float, float]:
        breakeven_points = []
        open_legs = [leg for leg in self.legs if leg.leg_type == LegType.TRADE_OPEN]
        total_premium = sum(abs(leg.premium_open) for leg in open_legs)
        for leg in open_legs:
            if leg.contract_type == ContractType.CALL:
                breakeven_points.append(leg.strike_price + total_premium)
            elif leg.contract_type == ContractType.PUT:
                breakeven_points.append(leg.strike_price - total_premium)

        if not breakeven_points:
            return 0.0, 0.0

        return min(breakeven_points), max(breakeven_points)

    def __str__(self):
        trade_str = (
            f"Trade Details:"
            f"\n  Open Date: {self.trade_date}"
            f"\n  Expire Date: {self.expire_date}"
            f"\n  DTE: {self.dte}"
            f"\n  Status: {self.status}"
            f"\n  Premium Captured: ${self.premium_captured:,.2f}"
        )

        if self.closing_premium is not None:
            trade_str += f"\n  Closing Premium: ${self.closing_premium:,.2f}"
        if self.closed_trade_at is not None:
            trade_str += f"\n  Closed At: {self.closed_trade_at}"
        if self.close_reason is not None:
            trade_str += f"\n  Close Reason: {self.close_reason}"

        trade_str += "\n  Legs:"
        for leg in self.legs:
            trade_str += str(leg)

        return trade_str


@dataclass
class OptionsData:
    quote_unixtime: int
    quote_readtime: str
    quote_date: str
    quote_time_hours: str
    underlying_last: float
    expire_date: str
    expire_unix: int
    dte: float
    c_delta: float
    c_gamma: float
    c_vega: float
    c_theta: float
    c_rho: float
    c_iv: float
    c_volume: float
    c_last: float
    c_size: str
    c_bid: float
    c_ask: float
    strike: float
    p_bid: float
    p_ask: float
    p_size: str
    p_last: float
    p_delta: float
    p_gamma: float
    p_vega: float
    p_theta: float
    p_rho: float
    p_iv: float
    p_volume: float
    strike_distance: float
    strike_distance_pct: float


class OptionsDatabase:
    def __init__(self, db_path, strategy_name, table_name_key=None):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.table_tag = table_name_key or datetime.now().strftime("%Y%m%d%H%M%S")
        logging.info(f"Strategy Key {self.table_tag}")
        self.trades_table = f"trades_{strategy_name}_{self.table_tag}"
        self.trade_legs_table = f"trade_legs_{strategy_name}_{self.table_tag}"

    def __enter__(self) -> "OptionsDatabase":
        """Context manager entry point - connects to database"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit point - ensures database is properly closed"""
        self.disconnect()

    def connect(self):
        """Establish database connection"""
        logging.info(f"Connecting to database: {self.db_path}")
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()

    def disconnect(self):
        """Close database connection"""
        if self.conn:
            logging.info("Closing database connection")
            self.conn.close()

    def build_leg_from_row(self, leg_row):
        return Leg(
            leg_quote_date=leg_row["Date"],
            leg_expiry_date=leg_row["ExpiryDate"],
            leg_type=LegType(leg_row["LegType"]),
            contract_type=ContractType(leg_row["ContractType"]),
            position_type=PositionType(leg_row["PositionType"]),
            strike_price=leg_row["StrikePrice"],
            underlying_price_open=leg_row["UnderlyingPriceOpen"],
            premium_open=leg_row["PremiumOpen"],
            underlying_price_current=leg_row["UnderlyingPriceCurrent"],
            premium_current=leg_row["PremiumCurrent"],
            delta=leg_row["Delta"],
            gamma=leg_row["Gamma"],
            vega=leg_row["Vega"],
            theta=leg_row["Theta"],
            iv=leg_row["Iv"],
            historyId=leg_row["HistoryId"],
        )

    def build_trade_from(self, trade_row, trade_legs):
        return Trade(
            id=trade_row["TradeId"],
            trade_date=trade_row["Date"],
            expire_date=trade_row["ExpireDate"],
            dte=trade_row["DTE"],
            status=trade_row["Status"],
            premium_captured=trade_row["PremiumCaptured"],
            closing_premium=trade_row["ClosingPremium"],
            closed_trade_at=trade_row["ClosedTradeAt"],
            close_reason=trade_row["CloseReason"],
            legs=trade_legs,
        )

    def setup_trades_table(self):
        """Drop and recreate trades and trade_history tables with DTE suffix"""
        drop_tables_sql = [
            f"DROP TABLE IF EXISTS {self.trade_legs_table}",
            f"DROP TABLE IF EXISTS {self.trades_table}",
        ]

        for drop_sql in drop_tables_sql:
            self.cursor.execute(drop_sql)

        # Create trades table
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {self.trades_table} (
            TradeId INTEGER PRIMARY KEY,
            Date DATE,
            ExpireDate DATE,
            DTE REAL,
            Status TEXT,
            PremiumCaptured REAL,
            ClosingPremium REAL,
            ClosedTradeAt DATE,
            CloseReason TEXT
        )
        """
        # Create trade legs table
        create_trade_legs_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {self.trade_legs_table} (
            HistoryId INTEGER PRIMARY KEY,
            TradeId INTEGER,
            Date DATE,
            ExpiryDate DATE,
            StrikePrice REAL,
            ContractType TEXT,
            PositionType TEXT,
            LegType TEXT,
            PremiumOpen REAL,
            PremiumCurrent REAL,
            UnderlyingPriceOpen REAL,
            UnderlyingPriceCurrent REAL,
            Delta REAL,
            Gamma REAL,
            Vega REAL,
            Theta REAL,
            Iv REAL,
            FOREIGN KEY(TradeId) REFERENCES {self.trades_table}(TradeId)
        )
        """
        self.cursor.execute(create_table_sql)
        self.cursor.execute(create_trade_legs_table_sql)
        logging.info("Tables dropped and recreated successfully")

        # Add indexes for options_data table
        index_sql = [
            "CREATE INDEX IF NOT EXISTS idx_options_quote_date ON options_data(QUOTE_DATE)",
            "CREATE INDEX IF NOT EXISTS idx_options_expire_date ON options_data(EXPIRE_DATE)",
            "CREATE INDEX IF NOT EXISTS idx_options_combined ON options_data(QUOTE_DATE, EXPIRE_DATE)",
        ]

        for sql in index_sql:
            self.cursor.execute(sql)

        logging.info("Added indexes successfully")

        # Create the backtest_runs table
        create_backtest_runs_table_sql = """
        CREATE TABLE IF NOT EXISTS backtest_runs (
            RunId INTEGER PRIMARY KEY,
            DateTime TEXT NOT NULL,
            Strategy TEXT NOT NULL,
            RawParams TEXT,
            TableNameKey TEXT,
            TradeTableName TEXT,
            TradeLegsTableName TEXT
        );
        """
        self.cursor.execute(create_backtest_runs_table_sql)
        self.conn.commit()

    def record_backtest_run(self, strategy_name: str, test_args: argparse.Namespace):
        backtest_run_sql = f"""
        INSERT INTO backtest_runs (
            DateTime, Strategy, RawParams, TableNameKey, TradeTableName, TradeLegsTableName
        ) VALUES (?, ?, ?, ?, ?, ?)
        """

        raw_params = ",".join(
            f"{key}={value}" for key, value in vars(test_args).items()
        )

        params = (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            strategy_name,
            raw_params,
            self.table_tag,
            self.trades_table,
            self.trade_legs_table,
        )

        self.cursor.execute(backtest_run_sql, params)
        self.conn.commit()

    def update_trade_leg(self, existing_trade_id, updated_leg: Leg):
        update_leg_sql = f"""
        INSERT INTO {self.trade_legs_table} (
            TradeId, Date, ExpiryDate, StrikePrice, ContractType, PositionType, LegType,
            PremiumOpen, PremiumCurrent, UnderlyingPriceOpen, UnderlyingPriceCurrent,
            Delta, Gamma, Vega, Theta, Iv
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            existing_trade_id,
            updated_leg.leg_quote_date,
            updated_leg.leg_expiry_date,
            updated_leg.strike_price,
            updated_leg.contract_type.value,
            updated_leg.position_type.value,
            updated_leg.leg_type.value,
            updated_leg.premium_open,
            updated_leg.premium_current,
            updated_leg.underlying_price_open,
            updated_leg.underlying_price_current,
            updated_leg.delta,
            updated_leg.gamma,
            updated_leg.vega,
            updated_leg.theta,
            updated_leg.iv,
        )

        logging.debug(f"update_trade_leg query:\n{update_leg_sql} ({params})")

        self.cursor.execute(update_leg_sql, params)
        self.conn.commit()

    def update_trade_with_multiple_legs(self, existing_trade: Trade):
        update_trade_sql = f"""
        UPDATE {self.trades_table}
        SET Date = ?,
            ExpireDate = ?,
            DTE = ?,
            Status = ?,
            PremiumCaptured = ?,
            ClosingPremium = ?,
            ClosedTradeAt = ?,
            CloseReason = ?
        WHERE TradeId = ?
        """

        trade_params = (
            existing_trade.trade_date,
            existing_trade.expire_date,
            existing_trade.dte,
            existing_trade.status,
            existing_trade.premium_captured,
            existing_trade.closing_premium,
            existing_trade.closed_trade_at,
            existing_trade.close_reason,
            existing_trade.id,
        )

        self.cursor.execute(update_trade_sql, trade_params)
        self.conn.commit()

        for leg in existing_trade.legs:
            self.update_trade_leg(existing_trade.id, leg)

    def create_trade_with_multiple_legs(self, trade):
        trade_sql = f"""
        INSERT INTO {self.trades_table} (
            Date, ExpireDate, DTE, Status, PremiumCaptured,
            ClosingPremium, ClosedTradeAt, CloseReason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        trade_params = (
            trade.trade_date,
            trade.expire_date,
            trade.dte,
            trade.status,
            trade.premium_captured,
            trade.closing_premium,
            trade.closed_trade_at,
            trade.close_reason,
        )

        self.cursor.execute(trade_sql, trade_params)
        trade_id = self.cursor.lastrowid

        leg_sql = f"""
        INSERT INTO {self.trade_legs_table} (
            TradeId, Date, ExpiryDate, StrikePrice, ContractType, PositionType, LegType,
            PremiumOpen, PremiumCurrent, UnderlyingPriceOpen, UnderlyingPriceCurrent,
            Delta, Gamma, Vega, Theta, Iv
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        for leg in trade.legs:
            leg_params = (
                trade_id,
                leg.leg_quote_date,
                leg.leg_expiry_date,
                leg.strike_price,
                leg.contract_type.value,
                leg.position_type.value,
                leg.leg_type.value,
                leg.premium_open,
                leg.premium_current,
                leg.underlying_price_open,
                leg.underlying_price_current,
                leg.delta,
                leg.gamma,
                leg.vega,
                leg.theta,
                leg.iv,
            )
            self.cursor.execute(leg_sql, leg_params)

        self.conn.commit()
        return trade_id

    def load_trade_with_multiple_legs(
        self, trade_id: int, leg_type: Optional[LegType] = None
    ) -> Trade:
        # First get the trade
        trade_sql = f"""
        SELECT TradeId, Date, ExpireDate, DTE, Status, PremiumCaptured,
               ClosingPremium, ClosedTradeAt, CloseReason
        FROM {self.trades_table} WHERE TradeId = ?
        """
        self.cursor.execute(trade_sql, (trade_id,))
        columns = [description[0] for description in self.cursor.description]
        trade_row = dict(zip(columns, self.cursor.fetchone()))

        if not trade_row:
            raise ValueError(f"Trade with id {trade_id} not found")

        trade_legs = self.trade_legs_from_db(trade_id, leg_type)
        return self.build_trade_from(trade_row, trade_legs)

    def update_trade_legs(
        self, existing_trade_legs, quote_date
    ) -> List[Dict[str, Leg]]:
        updated_legs = []
        for leg in existing_trade_legs:
            updates = {}
            od: OptionsData = self.get_current_options_data(
                quote_date, leg.strike_price, leg.leg_expiry_date
            )

            error_message, bad_data_found = bad_options_data(quote_date, od)
            if bad_data_found:
                logging.warning(error_message)
                continue

            updated_leg = Leg(
                historyId=leg.historyId,
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
                leg_type=leg.leg_type,
                delta=od.p_delta
                if leg.contract_type is ContractType.PUT
                else od.c_delta,
                gamma=od.p_gamma
                if leg.contract_type is ContractType.PUT
                else od.c_gamma,
                vega=od.p_vega if leg.contract_type is ContractType.PUT else od.c_vega,
                theta=od.p_theta
                if leg.contract_type is ContractType.PUT
                else od.c_theta,
                iv=od.p_iv if leg.contract_type is ContractType.PUT else od.c_iv,
            )
            logging.debug(
                f"Updating leg {leg.position_type.value} {leg.contract_type.value} -> {updated_leg.premium_current}"
            )
            updates["current"] = leg
            updates["updated"] = updated_leg

            updated_legs.append(updates)

        return updated_legs

    def leg_rows_from_db(self, trade_id, leg_type=None):
        # Then get legs for this trade
        if leg_type is None:
            legs_sql = f"""
            SELECT HistoryId, Date, ExpiryDate, StrikePrice, ContractType, PositionType, PremiumOpen,
                   PremiumCurrent, UnderlyingPriceOpen, UnderlyingPriceCurrent, LegType,
                   Delta, Gamma, Vega, Theta, Iv
            FROM {self.trade_legs_table} WHERE TradeId = ?
            """
            params = (trade_id,)
        else:
            legs_sql = f"""
            SELECT HistoryId, Date, ExpiryDate, StrikePrice, ContractType, PositionType, PremiumOpen,
                   PremiumCurrent, UnderlyingPriceOpen, UnderlyingPriceCurrent, LegType,
                   Delta, Gamma, Vega, Theta, Iv
            FROM {self.trade_legs_table} WHERE TradeId = ? AND LegType = ?
            """
            params = (trade_id, leg_type.value)
        self.cursor.execute(legs_sql, params)
        columns = [description[0] for description in self.cursor.description]
        leg_rows = [dict(zip(columns, row)) for row in self.cursor.fetchall()]
        return leg_rows

    def load_all_trades(self) -> List[Trade]:
        """Load all trades from the database"""
        # First get all trades
        trades_sql = f"""
        SELECT TradeId, Date, ExpireDate, DTE, Status, PremiumCaptured,
               ClosingPremium, ClosedTradeAt, CloseReason
        FROM {self.trades_table}
        ORDER BY Date
        """
        self.cursor.execute(trades_sql)
        columns = [description[0] for description in self.cursor.description]
        trade_rows = [dict(zip(columns, row)) for row in self.cursor.fetchall()]

        trades = []
        for trade_row in trade_rows:
            trade_id = trade_row["TradeId"]
            trade_legs = self.trade_legs_from_db(trade_id)
            trade = self.build_trade_from(trade_row, trade_legs)
            trades.append(trade)

        return trades

    def close_trade(self, existing_trade_id, existing_trade: Trade):
        # Update the trade record
        update_trade_sql = f"""
        UPDATE {self.trades_table}
        SET Status = ?,
            ClosingPremium = ?,
            ClosedTradeAt = ?,
            CloseReason = ?
        WHERE TradeId = ?
        """

        trade_params = (
            "CLOSED",
            existing_trade.closing_premium,
            existing_trade.closed_trade_at,
            existing_trade.close_reason,
            existing_trade_id,
        )

        self.cursor.execute(update_trade_sql, trade_params)
        self.conn.commit()

    def get_open_trades(self):
        """Get all open trades"""
        query = f"""
            SELECT *
            FROM {self.trades_table}
            WHERE Status = 'OPEN'
            """
        return pd.read_sql_query(query, self.conn)

    def get_last_open_trade(self):
        query = f"""
            SELECT *
            FROM {self.trades_table}
            WHERE Status = 'OPEN'
            ORDER BY DATE DESC LIMIT 1;
        """
        return pd.read_sql_query(query, self.conn)

    def get_current_options_data(
        self, quote_date: str, strike_price: float, expire_date: str
    ) -> Optional[OptionsData]:
        """Get current prices for a specific strike and expiration"""
        query = """
            SELECT *
            FROM options_data
            WHERE QUOTE_DATE = ?
            AND STRIKE = ?
            AND EXPIRE_DATE = ?
            """
        self.cursor.execute(query, (quote_date, strike_price, expire_date))
        result = self.cursor.fetchone()
        logging.debug(
            f"get_current_prices query:\n{query} ({quote_date}, {strike_price}, {expire_date}) => {result}"
        )

        if result is None:
            return None

        return OptionsData(*result)

    def get_quote_dates(self, start_date=None, end_date=None):
        """Get all unique quote dates"""
        if start_date is None or end_date is None:
            query = "SELECT DISTINCT QUOTE_DATE FROM options_data ORDER BY QUOTE_DATE"
        else:
            query = f"SELECT DISTINCT QUOTE_DATE FROM options_data WHERE QUOTE_DATE BETWEEN '{start_date}' AND '{end_date}' ORDER BY QUOTE_DATE"
        self.cursor.execute(query)
        dates = [row[0] for row in self.cursor.fetchall()]
        logging.debug(f"Found {len(dates)} unique quote dates")
        return dates

    def get_next_expiry_by_dte(self, quote_date, min_dte):
        """
        Get the next expiration date where DTE is greater than the specified number of days
        for a specific quote date
        Returns tuple of (expiry_date, actual_dte) or None if not found
        """
        query = """
        SELECT EXPIRE_DATE, DTE
        FROM options_data
        WHERE DTE >= ?
        AND QUOTE_DATE = ?
        GROUP BY EXPIRE_DATE
        ORDER BY EXPIRE_DATE ASC
        LIMIT 1
        """
        logging.debug(
            f"Executing query for next expiry with DTE > {min_dte} from {quote_date}"
        )
        self.cursor.execute(query, (min_dte, quote_date))
        result = self.cursor.fetchone()

        if result:
            logging.debug(f"Found next expiration: {result[0]} with DTE: {result[1]}")
            return result
        else:
            logging.debug(f"No expiration found with DTE > {min_dte} from {quote_date}")
            return None

    def get_options_data_closest_to_price(
        self, quote_date, expiry_date
    ) -> Optional[OptionsData]:
        query = """
        SELECT
            *
        FROM options_data
        WHERE QUOTE_DATE = ?
        AND EXPIRE_DATE = ?
        ORDER BY STRIKE_DISTANCE ASC
        LIMIT 1
        """
        self.cursor.execute(query, (quote_date, expiry_date))
        result = self.cursor.fetchone()
        logging.debug(
            f"get_current_prices query:\n{query} ({quote_date}, {expiry_date}) => {result}"
        )
        return None if not result else OptionsData(*result)

    def get_options_by_delta(
        self,
        contract_type: ContractType,
        position_type: PositionType,
        quote_date,
        expiry_date,
        required_delta,
    ):
        # Determine the delta column based on contract type
        delta_column = "C_DELTA" if contract_type == ContractType.CALL else "P_DELTA"

        # Determine the delta sign based on position type
        delta_sign = 1 if position_type == PositionType.LONG else -1

        # Query the database for options matching the criteria, sorted by delta closest to required_delta
        query = f"""
            SELECT * FROM options_data
            WHERE QUOTE_DATE = ? AND EXPIRE_DATE = ?
            ORDER BY ABS({delta_column} * ? - ?)
            LIMIT 1
        """
        params = (quote_date, expiry_date, delta_sign, required_delta)
        logging.debug(f"Executing query:\n{query} -> {params}")
        self.cursor.execute(query, params)
        result = self.cursor.fetchone()

        # Convert the result into an OptionsData object or similar structure
        if result:
            return OptionsData(*result)

        return None

    def trade_legs_from_db(self, trade_id, leg_type=None):
        leg_rows = self.leg_rows_from_db(trade_id, leg_type)
        return [self.build_leg_from_row(leg_row) for leg_row in leg_rows]


# Options Strategy Runner Framework


@dataclass
class DataForTradeManagement:
    max_open_trades: int
    trade_delay: int
    force_close_after_days: int
    profit_take: float
    stop_loss: float
    quote_date: str


def check_profit_take_stop_loss_targets(
    profit_take, stop_loss, existing_trade_premium_captured, updated_legs
):
    current_premium_value = round(sum(l.premium_current for l in updated_legs), 2)
    total_premium_received = (
        existing_trade_premium_captured + 0.001
        if existing_trade_premium_captured == 0
        else existing_trade_premium_captured
    )  # to avoid divide by zero error
    premium_diff = total_premium_received - current_premium_value
    premium_diff_pct = (premium_diff / total_premium_received) * 100
    if profit_take and premium_diff_pct >= profit_take:
        return "PROFIT_TAKE", True
    if stop_loss and premium_diff_pct <= -stop_loss:
        return "STOP_LOSS", True

    return "UNKNOWN", False


def bad_options_data(quote_date, od: OptionsData) -> Tuple[str, bool]:
    if not od:
        return f"⚠️ Unable to find options data for {quote_date=}", True

    if any(
        price is None or price == 0
        for price in (od.underlying_last, od.c_last, od.p_last)
    ):
        return (
            f"⚠️ Bad data found on {quote_date}. One of {od.underlying_last=}, {od.c_last=}, {od.p_last=} is missing",
            True,
        )
    return "", False


def within_max_open_trades(options_db, max_open_trades):
    open_trades = options_db.get_open_trades()
    if len(open_trades) >= max_open_trades:
        logging.debug(
            f"Maximum number of open trades ({max_open_trades}) reached. Skipping new trade creation."
        )
        return False

    return True


def passed_trade_delay(options_db, quote_date, trade_delay):
    """Check if enough time has passed since the last trade"""
    if trade_delay is None:
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


def add_standard_cli_arguments(parser):
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
        "--max-open-trades",
        type=int,
        default=99,
        help="Maximum number of open trades allowed at a given time",
    )
    parser.add_argument(
        "--trade-delay",
        type=int,
        help="Minimum number of days to wait between new trades",
    )
    parser.add_argument(
        "--force-close-after-days",
        type=int,
        help="Force close trade after days",
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


def check_if_passed_days(data_for_trade_management, existing_trade_trade_date):
    if not data_for_trade_management.force_close_after_days:
        return False

    trade_start_date = existing_trade_trade_date
    current_date = data_for_trade_management.quote_date
    days_passed = calculate_date_difference(trade_start_date, current_date)
    return days_passed >= data_for_trade_management.force_close_after_days


class GenericRunner:
    def __init__(self, args):
        self.args = args
        self.start_date = args.start_date
        self.end_date = args.end_date
        self.max_open_trades = args.max_open_trades
        self.trade_delay = args.trade_delay
        self.force_close_after_days = args.force_close_after_days
        self.profit_take = args.profit_take
        self.stop_loss = args.stop_loss
        self.db = OptionsDatabase(args.db_path, self.__class__.__name__.lower())

    def __enter__(self):
        self.db.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.db.disconnect()

    def run(self):
        db = self.db
        db.setup_trades_table()
        quote_dates = db.get_quote_dates(self.start_date, self.end_date)

        self.db.record_backtest_run(self.__class__.__name__, self.args)

        self.pre_run(db, quote_dates)

        for quote_date in quote_dates:
            logging.info(f"Processing {quote_date}")
            data_for_trade_management = DataForTradeManagement(
                self.max_open_trades,
                self.trade_delay,
                self.force_close_after_days,
                self.profit_take,
                self.stop_loss,
                quote_date,
            )

            # Update Open Trades
            open_trades = db.get_open_trades()

            for _, trade in open_trades.iterrows():
                try:
                    existing_trade_id = trade["TradeId"]
                    logging.info(
                        f"{data_for_trade_management.quote_date} => Updating existing trade {existing_trade_id}"
                    )

                    trade_from_db = db.load_trade_with_multiple_legs(
                        existing_trade_id, leg_type=LegType.TRADE_OPEN
                    )
                    existing_trade = (
                        self.adjust_trade(db, trade_from_db, quote_date)
                        if (
                            hasattr(self, "adjust_trade")
                            and self.adjust_trade.__func__
                            is not GenericRunner.adjust_trade
                        )
                        else trade_from_db
                    )

                    trade_legs_with_updates = db.update_trade_legs(
                        existing_trade.legs, data_for_trade_management.quote_date
                    )
                    updated_legs = [item["updated"] for item in trade_legs_with_updates]

                    close_reason, trade_can_be_closed = (
                        self.check_if_trade_can_be_closed(
                            data_for_trade_management,
                            existing_trade.premium_captured,
                            existing_trade.trade_date,
                            existing_trade.expire_date,
                            updated_legs,
                        )
                    )

                    existing_trade.legs = [
                        dataclasses.replace(
                            leg,
                            leg_type=(
                                LegType.TRADE_CLOSE
                                if trade_can_be_closed
                                else LegType.TRADE_AUDIT
                            )
                            if leg.historyId
                            else leg.leg_type,
                        )
                        for leg in updated_legs
                    ]

                    db.update_trade_with_multiple_legs(existing_trade)

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
                except Exception as e:
                    logging.error(
                        f"Failed to process open trade {trade['TradeId']} -> {e}"
                    )
                    raise e

            if not self.allowed_to_create_new_trade(db, data_for_trade_management):
                continue

            trade_to_setup = self.build_trade(db, quote_date)
            if not trade_to_setup:
                continue

            trade_id = db.create_trade_with_multiple_legs(trade_to_setup)
            logging.info(f"Trade {trade_id} created in database")

    def check_if_trade_can_be_closed(
        self,
        data_for_trade_management,
        trade_premium_captured,
        trade_start_date,
        trade_expire_date,
        updated_legs,
    ):
        close_reason, trade_can_be_closed = check_profit_take_stop_loss_targets(
            data_for_trade_management.profit_take,
            data_for_trade_management.stop_loss,
            trade_premium_captured,
            updated_legs,
        )
        if trade_can_be_closed:
            return close_reason, True

        if data_for_trade_management.quote_date >= trade_expire_date:
            return "EXPIRED", True

        if check_if_passed_days(data_for_trade_management, trade_start_date):
            return "FORCE_CLOSED_AFTER_DAYS", True

        return "", False

    def allowed_to_create_new_trade(self, options_db, data_for_trade_management):
        if not within_max_open_trades(
            options_db, data_for_trade_management.max_open_trades
        ):
            return False

        if not passed_trade_delay(
            options_db,
            data_for_trade_management.quote_date,
            data_for_trade_management.trade_delay,
        ):
            return False

        return True

    @abstractmethod
    def build_trade(self, db, quote_date) -> Optional[Trade]:
        pass

    def pre_run(self, db, quote_dates):
        pass

    def adjust_trade(self, db, existing_trade, quote_date) -> Trade:
        pass


# if __name__ == '__main__':
#     from pathlib import Path
#     db_path = Path().cwd().parent.joinpath("data/spx_eod.db")
#     db = OptionsDatabase(db_path.as_posix(), "foo_bar")
#     db.connect()
#     od = db.get_options_by_delta(
#         ContractType.PUT,
#         PositionType.SHORT,
#         "2013-07-01",
#         "2013-07-05",
#         0.5)
#     print(f"{od.p_last=} {od.p_delta=}")
