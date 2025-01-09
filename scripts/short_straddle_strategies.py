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
    options_db, quote_date, expiry_dte
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
        self.high_vol_check_window = args.high_vol_check_window
        self.high_vol_check_required = args.high_vol_check
        self.external_df = None

    def pre_run(self, options_db: OptionsDatabase, quote_dates):
        if self.high_vol_check_required:
            self.external_df = populate_volatility_data(
                quote_dates, self.high_vol_check_window
            )

    def in_high_vol_regime(self, quote_date) -> bool:
        high_vol_regime_flag = False
        try:
            signal_value = self.external_df.loc[quote_date, "High_Vol_Signal"]
            if signal_value == 1:
                high_vol_regime_flag = False
            else:
                logging.debug(
                    f"High Vol environment. The Signal value for {quote_date} is {signal_value}"
                )
                high_vol_regime_flag = True
        except KeyError:
            logging.debug(f"Date {quote_date} not found in DataFrame.")

        return high_vol_regime_flag

    def allowed_to_create_new_trade(
        self, options_db, data_for_trade_management: DataForTradeManagement
    ):
        allowed_based_on_default_checks = super().allowed_to_create_new_trade(
            options_db, data_for_trade_management
        )
        if not allowed_based_on_default_checks:
            return False

        if not self.high_vol_check_required:
            return True

        return self.in_high_vol_regime(data_for_trade_management.quote_date)

    def build_trade(self, options_db, quote_date) -> Optional[Trade]:
        expiry_dte, dte_found = options_db.get_next_expiry_by_dte(quote_date, self.dte)
        if not expiry_dte:
            logging.warning(f"⚠️ Unable to find {self.dte} expiry. {expiry_dte=}")
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
            dte=self.dte,
            status="OPEN",
            premium_captured=premium_captured_calculated,
            legs=trade_legs,
        )


class ShortStraddleRsiFilterStrategy(GenericRunner):
    def __init__(self, args):
        super().__init__(args)
        self.dte = args.dte
        self.rsi_check_required = (
            args.rsi and args.rsi_low_threshold and args.rsi_high_threshold
        )
        self.rsi_indicator = f"rsi_{args.rsi}"
        self.rsi_low_threshold = args.rsi_low_threshold
        self.rsi_high_threshold = args.rsi_high_threshold
        self.external_df = None

    def pre_run(self, options_db: OptionsDatabase, quote_dates):
        if self.rsi_check_required:
            underlying = "SPY"
            market_data = load_market_data(quote_dates, [underlying])
            self.external_df = market_data[underlying]
            _ = self.external_df[self.rsi_indicator]

    def allowed_to_create_new_trade(
        self, options_db, data_for_trade_management: DataForTradeManagement
    ):
        allowed_based_on_default_checks = super().allowed_to_create_new_trade(
            options_db, data_for_trade_management
        )
        if not allowed_based_on_default_checks:
            return False

        if not self.rsi_check_required:
            return True

        # RSI Check
        if data_for_trade_management.quote_date in self.external_df.index:
            rsi_value = self.external_df.loc[
                data_for_trade_management.quote_date, self.rsi_indicator
            ]
            return self.rsi_low_threshold < rsi_value < self.rsi_high_threshold
        else:
            return False

    def build_trade(self, options_db, quote_date) -> Optional[Trade]:
        expiry_dte, dte_found = options_db.get_next_expiry_by_dte(quote_date, self.dte)
        if not expiry_dte:
            logging.warning(f"⚠️ Unable to find {self.dte} expiry. {expiry_dte=}")
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
            dte=self.dte,
            status="OPEN",
            premium_captured=premium_captured_calculated,
            legs=trade_legs,
        )


class ShortStraddleStaggeredEntryStrategy(GenericRunner):
    def __init__(self, args):
        super().__init__(args)
        self.dte = args.dte
        self.total_contracts = args.number_of_contracts

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
