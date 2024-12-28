#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "plotly",
#   "pandas",
#   "dash",
# ]
# ///
"""
Options Trade Plotter

A tool to visualize options trades from a database

Usage:

"""

import os
import webbrowser
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import date, datetime
from threading import Timer
from typing import Dict, List

import dash
import plotly.graph_objects as go
from dash import Dash, dcc, html
from dash.dependencies import Input, Output
from plotly.subplots import make_subplots

from options_analysis import LegType, OptionsDatabase, Trade, calculate_date_difference


@dataclass
class TradeVisualizationData:
    """Data structure to hold processed visualization data"""

    dates: List[date]
    underlying_prices: List[float]
    leg_data: Dict[str, Dict[str, List[float]]]  # key: "Short Put", "Long Call" etc.
    total_premium_differences: List[float]
    trade_date: date
    trade_strike: float
    options_expiry: date

    def __str__(self) -> str:
        return (
            f"Trade from {self.trade_date} to {self.options_expiry}\n"
            f"Dates: {self.dates}\n"
            f"Underlying Prices: {self.underlying_prices}\n"
            f"Legs Data: {self.leg_data}\n"
            f"Total Premium Differences: {self.total_premium_differences}\n"
            f"Trade Date: {self.trade_date}\n"
            f"Trade Strike: {self.trade_strike}\n"
            f"Option Expiration: {self.options_expiry}"
        )


class TradeDataProcessor:
    """Processes trade data for visualization"""

    @staticmethod
    def process_trade_data(trade: Trade) -> TradeVisualizationData:
        """Processes trade data for visualization"""
        all_data = {}  # Dict to store data for each leg type
        dates_set = set()
        options_expiry = None

        for leg in trade.legs:
            if leg.leg_type is LegType.TRADE_OPEN:
                options_expiry = leg.leg_expiry_date

            leg_key = f"{leg.position_type.value} {leg.contract_type.value}"

            if leg_key not in all_data:
                all_data[leg_key] = {
                    "prices": [],
                    "premiums": [],
                    "premium_diffs": [],
                    "greeks": [],
                }

            current_date = leg.leg_quote_date
            dates_set.add(current_date)

            current_price = (
                leg.underlying_price_current
                if leg.underlying_price_current is not None
                else leg.underlying_price_open
            )
            current_premium = (
                leg.premium_current
                if leg.leg_type is not LegType.TRADE_OPEN
                else leg.premium_open
            )
            premium_diff = (
                leg.premium_current - leg.premium_open
                if leg.premium_current is not None
                else 0
            )

            greeks = {
                "delta": leg.delta,
                "gamma": leg.gamma,
                "theta": leg.theta,
                "vega": leg.vega,
                "iv": leg.iv,
            }

            all_data[leg_key]["prices"].append((current_date, current_price))
            all_data[leg_key]["premiums"].append((current_date, current_premium))
            all_data[leg_key]["premium_diffs"].append((current_date, premium_diff))
            all_data[leg_key]["greeks"].append((current_date, greeks))

        all_dates = sorted(dates_set)

        leg_data = {
            leg_key: {
                "premiums": [],
                "premium_diffs": [],
                "greeks": [],
            }
            for leg_key in all_data.keys()
        }

        underlying_prices = []

        for current_date in all_dates:
            price_data = next(
                (
                    price
                    for leg in all_data.values()
                    for date, price in leg["prices"]
                    if date == current_date
                ),
                None,
            )
            underlying_prices.append(price_data)

            for leg_key, leg_data_dict in all_data.items():
                premium = next(
                    (
                        prem
                        for date, prem in leg_data_dict["premiums"]
                        if date == current_date
                    ),
                    None,
                )
                leg_data[leg_key]["premiums"].append(premium)

                diff = next(
                    (
                        diff
                        for date, diff in leg_data_dict["premium_diffs"]
                        if date == current_date
                    ),
                    None,
                )
                leg_data[leg_key]["premium_diffs"].append(diff)

                greeks = next(
                    (g for date, g in leg_data_dict["greeks"] if date == current_date),
                    None,
                )
                leg_data[leg_key]["greeks"].append(greeks)

        total_premium_differences = []
        for i in range(len(all_dates)):
            total_diff = sum(
                leg_data[leg_key]["premium_diffs"][i] or 0 for leg_key in leg_data
            )
            total_premium_differences.append(-total_diff)

        return TradeVisualizationData(
            dates=all_dates,
            underlying_prices=underlying_prices,
            leg_data=leg_data,
            total_premium_differences=total_premium_differences,
            trade_date=trade.trade_date,
            trade_strike=trade.legs[0].strike_price,
            options_expiry=options_expiry,
        )


class PlotConfig:
    """Configuration for plot appearance"""

    def __init__(self):
        self.figure_height = 1000
        # Base colors
        self.underlying_color = "#2C3E50"  # Dark blue-grey
        self.short_color = "#E74C3C"  # Coral red
        self.long_color = "#2ECC71"  # Emerald green
        self.total_color = "#9B59B6"  # Amethyst purple
        self.grid_color = "#ECF0F1"  # Light grey
        self.marker_size = 5
        self.line_width = 1
        self.grid_style = "dot"
        self.currency_format = "${:,.2f}"


class DashTradeVisualizer:
    """Dash-based trade visualization"""

    FONT = "Fantasque Sans Mono"

    def __init__(self, db_path: str, strategy_name: str, table_name_key: str):
        self.db_path = db_path
        self.strategy_name = strategy_name
        self.table_name_key = table_name_key
        self.config = PlotConfig()
        self.app = Dash(__name__)
        self.trade_cache: Dict[int, Trade] = {}

        # Initialize trades at startup using a new database connection
        self.trades = {}  # Initialize empty dict first
        with self._get_db() as db:
            self.trades = {
                trade.id: f"Trade {trade.id} - {trade.trade_date} to {trade.expire_date}"
                for trade in db.load_all_trades()
            }

        self.setup_layout()
        self.setup_callbacks()

    def _get_db(self) -> OptionsDatabase:
        """Create a new database connection for the current thread"""
        return OptionsDatabase(self.db_path, self.strategy_name, self.table_name_key)

    def setup_layout(self):
        """Setup the Dash application layout"""
        self.app.layout = html.Div(
            [
                html.Div(
                    [
                        dcc.Dropdown(
                            id="trade-selector",
                            options=[
                                {"label": v, "value": k} for k, v in self.trades.items()
                            ],
                            value=list(self.trades.keys())[0] if self.trades else None,
                            style={"width": "100%", "marginBottom": "10px"},
                        ),
                        html.Div(
                            [
                                html.Button(
                                    "← Previous Trade",
                                    id="prev-trade-btn",
                                    style={
                                        "marginRight": "10px",
                                        "padding": "10px 20px",
                                        "backgroundColor": "#f0f0f0",
                                        "border": "1px solid #ddd",
                                        "borderRadius": "4px",
                                        "cursor": "pointer",
                                    },
                                ),
                                html.Button(
                                    "Next Trade →",
                                    id="next-trade-btn",
                                    style={
                                        "padding": "10px 20px",
                                        "backgroundColor": "#f0f0f0",
                                        "border": "1px solid #ddd",
                                        "borderRadius": "4px",
                                        "cursor": "pointer",
                                    },
                                ),
                            ],
                            style={
                                "display": "flex",
                                "justifyContent": "center",
                                "marginBottom": "20px",
                            },
                        ),
                    ],
                    style={"width": "80%", "margin": "auto"},
                ),
                dcc.Graph(
                    id="trade-plot",
                    style={"height": "1200px"},
                    config={"displayModeBar": False},
                ),
            ],
            style={"padding": "20px"},
        )

    def setup_callbacks(self):
        """Setup the Dash callbacks"""

        @self.app.callback(
            Output("trade-selector", "value"),
            [
                Input("prev-trade-btn", "n_clicks"),
                Input("next-trade-btn", "n_clicks"),
            ],
            [Input("trade-selector", "value")],
        )
        def update_selected_trade(prev_clicks, next_clicks, current_trade_id):
            if current_trade_id is None:
                return list(self.trades.keys())[0] if self.trades else None

            # Get list of trade IDs
            trade_ids = list(self.trades.keys())
            current_index = trade_ids.index(current_trade_id)

            # Determine which button was clicked
            ctx = dash.callback_context
            if not ctx.triggered:
                return current_trade_id

            button_id = ctx.triggered[0]["prop_id"].split(".")[0]

            if button_id == "prev-trade-btn":
                new_index = (current_index - 1) % len(trade_ids)
            elif button_id == "next-trade-btn":
                new_index = (current_index + 1) % len(trade_ids)
            else:
                return current_trade_id

            return trade_ids[new_index]

        @self.app.callback(
            Output("trade-plot", "figure"), [Input("trade-selector", "value")]
        )
        def update_graph(trade_id):
            if trade_id is None:
                return go.Figure()

            with self._get_db() as db:
                return self.create_visualization(trade_id, db)

    def create_visualization(self, trade_id: int, db: OptionsDatabase) -> go.Figure:
        trade = db.load_trade_with_multiple_legs(trade_id)
        data = TradeDataProcessor.process_trade_data(trade)

        dte = calculate_date_difference(data.options_expiry, data.trade_date)

        fig = make_subplots(
            rows=5,
            cols=2,
            subplot_titles=("", "", "", "", "", "", "", "", "", ""),
            vertical_spacing=0.05,
            horizontal_spacing=0.1,
            specs=[
                [{"type": "scatter"}, {"type": "scatter"}],
                [{"type": "scatter"}, {"type": "scatter"}],
                [{"type": "scatter"}, {"type": "scatter"}],
                [None, {"type": "scatter"}],
                [None, {"type": "scatter"}],
            ],
            column_widths=[0.5, 0.5],
            row_heights=[0.01, 0.01, 0.01, 0.01, 0.01],
        )

        colors = {
            "Short Call": "#E74C3C",
            "Short Put": "#3498DB",
            "Long Call": "#2ECC71",
            "Long Put": "#F1C40F",
        }

        fig.add_trace(
            go.Scatter(
                x=data.dates,
                y=data.underlying_prices,
                name="Price",
                line=dict(
                    color=self.config.underlying_color, width=self.config.line_width
                ),
                mode="lines+markers",
                marker=dict(size=self.config.marker_size),
                showlegend=False,
            ),
            row=1,
            col=1,
        )

        for leg_key, leg_info in data.leg_data.items():
            fig.add_trace(
                go.Scatter(
                    x=data.dates,
                    y=leg_info["premiums"],
                    name=leg_key,
                    line=dict(
                        color=colors.get(leg_key, "#000000"),
                        width=self.config.line_width,
                    ),
                    mode="lines+markers",
                    marker=dict(size=self.config.marker_size),
                    showlegend=True,
                ),
                row=2,
                col=1,
            )

        fig.add_trace(
            go.Scatter(
                x=data.dates,
                y=data.total_premium_differences,
                name="Total",
                line=dict(color=self.config.total_color, width=self.config.line_width),
                mode="lines+markers",
                marker=dict(size=self.config.marker_size),
                showlegend=False,
            ),
            row=3,
            col=1,
        )

        greek_rows = {"delta": 1, "gamma": 2, "vega": 3, "theta": 4, "iv": 5}

        for greek in ["delta", "gamma", "vega", "theta", "iv"]:
            row = greek_rows[greek]
            for leg_key, leg_info in data.leg_data.items():
                values = [g[greek] if g else None for g in leg_info["greeks"]]
                fig.add_trace(
                    go.Scatter(
                        x=data.dates,
                        y=values,
                        name=f"{leg_key} {greek}",
                        line=dict(
                            color=colors.get(leg_key, "#000000"),
                            width=self.config.line_width,
                        ),
                        mode="lines+markers",
                        marker=dict(size=self.config.marker_size),
                        showlegend=False,
                    ),
                    row=row,
                    col=2,
                )

        fig.add_hline(
            y=0,
            line_dash="dash",
            line_color="gray",
            row=3,
            col=1,
        )

        days_in_trade = (
            calculate_date_difference(trade.trade_date, trade.closed_trade_at)
            if trade.closed_trade_at is not None
            else calculate_date_difference(
                trade.trade_date, datetime.now().strftime("%Y-%m-%d")
            )
        )
        premium_gain_loss = (
            trade.premium_captured + trade.closing_premium
            if trade.closing_premium is not None
            else trade.premium_captured
        )
        if premium_gain_loss >= 0:
            gain_loss_color = "green"
        else:
            gain_loss_color = "red"

        fig.update_layout(
            height=self.config.figure_height,
            title=dict(
                text=f"<b>Trade Date:</b> {data.trade_date} <b>Strike</b> {data.trade_strike} <b>Expiry:</b> {data.options_expiry} ({dte}) <b>In Trade:</b>{days_in_trade} days <b>Gain/Loss:</b> <span style='color:{gain_loss_color};'>${premium_gain_loss:.2f} ({trade.close_reason})</span></span> ",
                font=dict(family=self.FONT, size=16, color="#2C3E50"),
                x=0.5,
            ),
            showlegend=False,
            hovermode="x unified",
            plot_bgcolor="white",
            paper_bgcolor="white",
            font=dict(family=self.FONT),
        )

        col1_labels = {
            1: "Price ($)",
            2: "Premium ($)",
            3: "Total Premium ($)",
        }

        col2_labels = {
            1: "Delta",
            2: "Gamma",
            3: "Vega",
            4: "Theta",
            5: "IV (%)",
        }

        for row, label in col1_labels.items():
            fig.update_yaxes(
                title_text=label,
                row=row,
                col=1,
                showgrid=False,
                zeroline=False,
                showline=True,
                linewidth=1,
                linecolor="lightgrey",
            )

        for row, label in col2_labels.items():
            fig.update_yaxes(
                title_text=label,
                row=row,
                col=2,
                showgrid=False,
                zeroline=False,
                showline=True,
                linewidth=1,
                linecolor="lightgrey",
            )

        for col in [1, 2]:
            max_row = 3 if col == 1 else 5
            for row in range(1, max_row + 1):
                fig.update_xaxes(
                    title_text="Date"
                    if (col == 1 and row == 3) or (col == 2 and row == 5)
                    else "",
                    showgrid=False,
                    zeroline=False,
                    showline=True,
                    linewidth=1,
                    linecolor="lightgrey",
                    row=row,
                    col=col,
                )

        return fig

    def run(self, debug=False, port=8050):
        """Run the Dash application"""

        def open_browser(port=8050):
            if not os.environ.get("WERKZEUG_RUN_MAIN"):
                webbrowser.open_new(f"http://localhost:{port}")

        Timer(1, open_browser).start()
        self.app.run_server(debug=debug, port=port)


def main():
    args = parse_args()
    visualizer = DashTradeVisualizer(
        args.db_path, args.strategy_name, args.table_name_key
    )
    visualizer.run(debug=True)


def parse_args():
    parser = ArgumentParser(description=__doc__)
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


if __name__ == "__main__":
    main()
