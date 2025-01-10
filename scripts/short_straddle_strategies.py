import logging
from typing import Optional

import pandas as pd
from market_data import load_market_data
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
)
from pandas import DataFrame


def calculate_legs_for_straddle(
    options_db, quote_date, expiry_dte, quantity=1
) -> tuple[list[Leg], Optional[float]]:
    od: OptionsData = options_db.get_options_data_closest_to_price(
        quote_date, expiry_dte
    )
    if not od or od.p_last in [None, 0] or od.c_last in [None, 0]:
        logging.warning(
            "⚠️ Bad data found: "
            + (
                "One or more options are not valid"
                if not od
                else f"On {quote_date=} for {expiry_dte=}, one of {od.c_last=}, {od.p_last=} is not valid"
            )
        )
        return [], None

    base_legs = [
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

    trade_legs = base_legs * quantity
    premium_captured_calculated = round(sum(leg.premium_open for leg in trade_legs), 2)
    return trade_legs, premium_captured_calculated


def populate_volatility_data(quote_dates, window) -> DataFrame:
    symbols = ["^VIX9D", "^VIX"]
    market_data = load_market_data(quote_dates, symbols)

    df = pd.DataFrame()
    df["Short_Term_VIX"] = market_data["^VIX9D"]["close"]
    df["Long_Term_VIX"] = market_data["^VIX"]["close"]
    df["IVTS"] = df["Short_Term_VIX"] / df["Long_Term_VIX"]
    df[f"IVTS_Med_{window}"] = df["IVTS"].rolling(window=window).median()
    df["High_Vol_Signal"] = (df[f"IVTS_Med_{window}"] < 1).astype(int) * 2 - 1
    return df


class ShortStraddleStrategy(GenericRunner):
    def __init__(self, args):
        super().__init__(args)
        self.dte = args.dte

        # Volatility check parameters
        self.high_vol_check_window = getattr(args, "high_vol_check_window", None)
        self.high_vol_check_required = getattr(args, "high_vol_check", False)

        # RSI parameters
        self.rsi_check_required = (
            getattr(args, "rsi", False)
            and getattr(args, "rsi_low_threshold", None)
            and getattr(args, "rsi_high_threshold", None)
        )
        self.rsi_indicator = f"rsi_{getattr(args, 'rsi', '')}"
        self.rsi_low_threshold = getattr(args, "rsi_low_threshold", None)
        self.rsi_high_threshold = getattr(args, "rsi_high_threshold", None)

        # Staggered entry parameters
        self.total_contracts = getattr(args, "number_of_contracts", 1)
        self.ladder_additional_contracts = getattr(
            args, "ladder_additional_contracts", False
        )

        # DataFrames for external data
        self.volatility_df = None
        self.rsi_df = None

    def pre_run(self, options_db: OptionsDatabase, quote_dates):
        if self.high_vol_check_required:
            self.volatility_df = populate_volatility_data(
                quote_dates, self.high_vol_check_window
            )

        if self.rsi_check_required:
            underlying = "SPY"
            market_data = load_market_data(quote_dates, [underlying])
            self.rsi_df = market_data[underlying]
            _ = self.rsi_df[self.rsi_indicator]

    def in_high_vol_regime(self, quote_date) -> bool:
        if not self.high_vol_check_required:
            return True

        try:
            signal_value = self.volatility_df.loc[quote_date, "High_Vol_Signal"]
            if signal_value == 1:
                return False
            logging.debug(
                f"High Vol environment. The Signal value for {quote_date} is {signal_value}"
            )
            return True
        except KeyError:
            logging.debug(f"Date {quote_date} not found in DataFrame.")
            return False

    def check_rsi_conditions(self, quote_date) -> bool:
        if not self.rsi_check_required:
            return True

        if quote_date in self.rsi_df.index:
            rsi_value = self.rsi_df.loc[quote_date, self.rsi_indicator]
            return self.rsi_low_threshold < rsi_value < self.rsi_high_threshold
        return False

    def allowed_to_create_new_trade(
        self, options_db, data_for_trade_management: DataForTradeManagement
    ):
        allowed_based_on_default_checks = super().allowed_to_create_new_trade(
            options_db, data_for_trade_management
        )
        if not allowed_based_on_default_checks:
            return False

        # Check both volatility and RSI conditions
        return self.in_high_vol_regime(
            data_for_trade_management.quote_date
        ) and self.check_rsi_conditions(data_for_trade_management.quote_date)

    def build_trade(self, options_db, quote_date) -> Optional[Trade]:
        expiry_dte, dte_found = options_db.get_next_expiry_by_dte(quote_date, self.dte)
        if not expiry_dte:
            logging.warning(f"⚠️ Unable to find {self.dte} expiry. {expiry_dte=}")
            return None

        logging.debug(f"Quote date: {quote_date} -> {expiry_dte=} ({dte_found=:.1f}), ")

        quantity = 1 if self.ladder_additional_contracts else self.total_contracts
        trade_legs, premium = calculate_legs_for_straddle(
            options_db, quote_date, expiry_dte, quantity
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
        if not self.ladder_additional_contracts or len(existing_trade.legs) >= (
            self.total_contracts * 2
        ):
            return existing_trade

        new_legs, premium = calculate_legs_for_straddle(db, quote_date, existing_expiry)
        if not new_legs:
            return existing_trade

        for nl in new_legs:
            existing_trade.legs.append(nl)
        existing_trade.premium_captured = existing_trade.premium_captured + premium
        return existing_trade
