#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "pandas",
#   "plotly",
# ]
# ///
"""
This script calculates and visualizes the cumulative premium kept for trades from an SQLite database.
Additionally, calculates and displays portfolio performance metrics for each DTE.

input:
    - Path to SQLite database file
    - Optional: Graph title
output:
    - Interactive equity graph showing the cumulative premium kept over time for different DTEs
    - Portfolio performance metrics table in console and HTML
"""

import argparse
import logging
import sqlite3
from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from logger import setup_logging


@dataclass
class BacktestRun:
    run_id: int
    datetime: str
    strategy: str
    raw_params: str
    table_name_key: str
    trade_table_name: str
    trade_legs_table_name: str


def create_html_output(fig):
    html_content = f"""
    <html>
    <head>
        <title>Trading Analysis</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 20px;
                background-color: #f5f5f5;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                background-color: white;
                padding: 20px;
                box-shadow: 0 0 10px rgba(0,0,0,0.1);
                border-radius: 5px;
            }}
            .graph-container {{
                margin-bottom: 30px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="graph-container">
                {fig.to_html(full_html=False, include_plotlyjs=False)}
            </div>
        </div>
    </body>
    </html>
    """
    return html_content


def fetch_data(db_path, table_name):
    conn = sqlite3.connect(db_path)

    query = f"""
    SELECT
        TradeId,
        Date,
        PremiumCaptured,
        ClosingPremium,
        (PremiumCaptured + ClosingPremium) AS PremiumKept,
        ClosedTradeAt,
        CloseReason
    FROM {table_name};
    """

    df = pd.read_sql(query, conn)
    conn.close()
    return df


def calculate_portfolio_metrics(df):
    metrics = {}

    df["PremiumKept"] = pd.to_numeric(df["PremiumKept"], errors="coerce")

    # Calculate win/loss metrics
    winners = df[df["PremiumKept"] > 0]
    losers = df[df["PremiumKept"] < 0]
    total_trades = len(df)

    # Win/Loss statistics
    num_winners = len(winners)
    num_losers = len(losers)
    win_rate = (num_winners / total_trades * 100) if total_trades > 0 else 0
    loss_rate = (num_losers / total_trades * 100) if total_trades > 0 else 0

    avg_winner = float(winners["PremiumKept"].mean()) if len(winners) > 0 else 0
    avg_loser = abs(float(losers["PremiumKept"].mean())) if len(losers) > 0 else 0

    # Maximum winner and loser
    max_winner = float(winners["PremiumKept"].max()) if len(winners) > 0 else 0
    max_loser = abs(float(losers["PremiumKept"].min())) if len(losers) > 0 else 0

    # Calculate Expectancy Ratio
    if avg_loser > 0:
        expectancy_ratio = (
            (win_rate / 100 * avg_winner) - (loss_rate / 100 * avg_loser)
        ) / avg_loser
    else:
        expectancy_ratio = 0

    # Calculate total cumulative premium
    total_premium = float(df["PremiumKept"].sum())

    # Store metrics with proper formatting
    metrics["Total Trades"] = total_trades
    metrics["Win Rate"] = f"{win_rate:.2f}%"
    metrics["Avg Winner ($)"] = f"${avg_winner:.2f}"
    metrics["Max Winner ($)"] = f"${max_winner:.2f}"
    metrics["Loss Rate"] = f"{loss_rate:.2f}%"
    metrics["Avg Loser ($)"] = f"${avg_loser:.2f}"
    metrics["Max Loser ($)"] = f"${max_loser:.2f}"
    metrics["Expectancy Ratio"] = f"{expectancy_ratio:.2f}"
    metrics["Total Cumulative ($)"] = f"${total_premium:.2f}"

    return metrics


def analyze_win_loss_trades(df):
    df["TotalPremium"] = df["PremiumCaptured"] + df["ClosingPremium"]
    df["TradeResult"] = df["TotalPremium"].apply(lambda x: "Win" if x > 0 else "Loss")
    df["Year"] = pd.to_datetime(df["Date"]).dt.year
    df["Month"] = pd.to_datetime(df["Date"]).dt.month

    yearly_analysis = {}

    for year in df["Year"].unique():
        year_data = df[df["Year"] == year]
        monthly_stats = []

        for month in range(1, 13):
            month_data = year_data[year_data["Month"] == month]
            winning_trades = month_data[month_data["TradeResult"] == "Win"]
            losing_trades = month_data[month_data["TradeResult"] == "Loss"]

            if len(month_data) > 0:
                monthly_stats.append(
                    {
                        "Month": pd.Timestamp(2024, month, 1).strftime("%B"),
                        "Winning Trade Count": len(winning_trades),
                        "Losing Trade Count": len(losing_trades),
                    }
                )

        if monthly_stats:
            yearly_analysis[year] = monthly_stats

    return yearly_analysis


def calculate_monthly_win_rates_per_dte(dfs_dict):
    monthly_win_rates_dict = {}

    for dte, df in dfs_dict.items():
        df = df.copy()
        # Convert Date to datetime if it's not already
        df["Date"] = pd.to_datetime(df["Date"])

        # Add year and month columns
        df["Year"] = df["Date"].dt.year
        df["Month"] = df["Date"].dt.month

        # Calculate premium difference
        df["PremiumDiff"] = df["PremiumCaptured"] + df["ClosingPremium"]

        # Group by year and month and calculate total premium difference
        monthly_stats = (
            df.groupby(["Year", "Month"])
            .agg(premium_diff=("PremiumDiff", lambda x: f"${x.sum():.2f}"))
            .reset_index()
        )

        # Calculate yearly totals
        yearly_totals = (
            df.groupby("Year")
            .agg(yearly_total=("PremiumDiff", lambda x: f"${x.sum():.2f}"))
            .reset_index()
        )

        # Pivot the data to create the desired table format
        stats_table = monthly_stats.pivot(
            index="Year", columns="Month", values="premium_diff"
        )

        # Create a formatted table with premium differences
        formatted_table = pd.DataFrame(index=stats_table.index)
        for month in range(1, 13):
            if month in stats_table.columns:
                formatted_table[f"{pd.Timestamp(2024, month, 1).strftime('%b')}"] = (
                    stats_table[month]
                )
            else:
                formatted_table[f"{pd.Timestamp(2024, month, 1).strftime('%b')}"] = "-"

        # Add yearly total column
        formatted_table["Total"] = yearly_totals.set_index("Year")["yearly_total"]

        monthly_win_rates_dict[dte] = formatted_table

    return monthly_win_rates_dict


def add_metrics_to_figure(fig, metrics_dict):
    metrics_df = pd.DataFrame.from_dict(metrics_dict, orient="index")
    metrics_df.index = [dte for dte in metrics_df.index]

    # Add table trace
    fig.add_trace(
        go.Table(
            header=dict(
                values=["Table Key"] + list(metrics_df.columns),
                fill_color="paleturquoise",
                align="left",
                font=dict(size=12),
            ),
            cells=dict(
                values=[metrics_df.index]
                + [metrics_df[col] for col in metrics_df.columns],
                fill_color="lavender",
                align="left",
                font=dict(size=11),
            ),
        ),
        row=2,
        col=1,
    )

    return fig


def add_win_rates_to_figure(fig, win_rates_df, row_number):
    # Function to determine cell color based on premium value
    def get_cell_color(value):
        if value == "-":
            return "lavender"
        # Remove "$" and convert to float
        try:
            amount = float(value.replace("$", ""))
            if amount > 0:
                # Green scale for positive values
                intensity = min(
                    abs(amount) / 1000, 1
                )  # Adjust 1000 to change color intensity scaling
                return f"rgba(0, 255, 0, {0.1 + intensity * 0.3})"
            else:
                # Red scale for negative values
                intensity = min(
                    abs(amount) / 1000, 1
                )  # Adjust 1000 to change color intensity scaling
                return f"rgba(255, 0, 0, {0.1 + intensity * 0.3})"
        except:
            return "lavender"

    # Create cell colors for each column
    cell_colors = []
    for col in win_rates_df.columns:
        col_colors = [get_cell_color(val) for val in win_rates_df[col]]
        cell_colors.append(col_colors)

    fig.add_trace(
        go.Table(
            header=dict(
                values=["Year"] + list(win_rates_df.columns),
                fill_color="paleturquoise",
                align="center",
                font=dict(size=12),
                height=25,
            ),
            cells=dict(
                values=[win_rates_df.index]
                + [win_rates_df[col] for col in win_rates_df.columns],
                fill_color=["lavender"] + cell_colors,
                align="center",
                font=dict(size=11),
                height=20,
            ),
        ),
        row=row_number,
        col=1,
    )
    return fig


def plot_equity_graph(fig, dfs_dict):
    color_cycle = [
        "#1f77b4",  # Blue
        "#ff7f0e",  # Orange
        "#2ca02c",  # Green
        "#d62728",  # Red
        "#9467bd",  # Purple
        "#8c564b",  # Brown
        "#e377c2",  # Pink
        "#7f7f7f",  # Gray
        "#bcbd22",  # Yellow-green
        "#17becf",  # Cyan
    ]

    for i, (table_name_key, df) in enumerate(dfs_dict.items()):
        df["Date"] = pd.to_datetime(df["Date"])
        df["CumulativePremiumKept"] = df["PremiumKept"].cumsum()

        fig.add_trace(
            go.Scatter(
                x=df["Date"],
                y=df["CumulativePremiumKept"],
                mode="lines+markers",
                name=table_name_key,
                line=dict(color=color_cycle[i % len(color_cycle)]),
                marker=dict(size=1),
                hovertemplate="<b>Date:</b> %{x}<br>"
                + "<b>Cumulative Premium:</b> $%{y:.2f}<br>"
                + f"<b>Table Key:</b> {table_name_key}<br>"
                + "<extra></extra>",
                showlegend=True,
            ),
            row=1,
            col=1,
        )

    fig.update_xaxes(title_text="Date", row=1, col=1)
    fig.update_yaxes(title_text="Cumulative Premium Kept ($)", row=1, col=1)

    return fig


def generate_report(db_path, strategy_name, title):
    print(
        f"\nFetching data from database: {db_path} looking for strategy {strategy_name}"
    )

    backtest_runs = _fetch_backtest_run_rows(db_path, strategy_name)
    logging.debug(
        f"Found {len(backtest_runs)} backtest runs for strategy {strategy_name}"
    )

    # Collect all the trade table names from the backtest runs table
    trade_table_names = []
    for row in backtest_runs:
        trade_table_names.append(row.trade_table_name)
    logging.debug(f"Trade table names: {trade_table_names}")

    dfs_dict = {}
    metrics_dict = {}
    win_loss_analysis_dict = {}

    for row in backtest_runs:
        df = fetch_data(db_path, row.trade_table_name)
        if not df.empty:
            dfs_dict[row.table_name_key] = df
            metrics_dict[row.table_name_key] = calculate_portfolio_metrics(df)
            win_loss_analysis_dict[row.table_name_key] = analyze_win_loss_trades(df)

    if not dfs_dict:
        logging.warning("No data found in any of the tables.")
        return

    logging.debug(f"Found {len(dfs_dict)} backtest runs for {strategy_name}")

    monthly_win_rates_dict = calculate_monthly_win_rates_per_dte(dfs_dict)

    # Setup all sub plots
    specs = [
        [{"type": "xy"}],  # Equity graph
        [{"type": "table"}],  # Metrics table
    ]

    # Add specs for each DTE's win rate table and bar chart
    num_win_rate_tables = len(dfs_dict)

    for _ in range(num_win_rate_tables):
        specs.append([{"type": "table"}])  # Win rate table
        specs.append([{"type": "xy"}])  # Bar chart

    total_rows = len(specs)
    each_row_height = 800
    row_heights = [each_row_height] * total_rows
    total_height = each_row_height * total_rows

    # Create subplot titles
    subplot_titles = ["Equity Graph", "Performance Metrics by DTE"]
    for table_name_key in sorted(dfs_dict.keys()):
        backtest_run_row = next(
            (row for row in backtest_runs if row.table_name_key == table_name_key), None
        )

        # Convert raw_params to a dictionary
        raw_params_dict = {
            k: v
            for k, v in (x.split("=") for x in backtest_run_row.raw_params.split(","))
            if k not in ("verbose", "db_path", "start_date", "end_date") and v != "None"
        }
        params = ", ".join(f"{k}={v}" for k, v in raw_params_dict.items())

        # Populate Sub titles
        subplot_titles.extend(
            [
                f"Monthly Win Rates - ({params})",
                f"Win/Loss Count Analysis - ({params})",
            ]
        )

    fig = make_subplots(
        rows=total_rows,
        cols=1,
        row_heights=row_heights,
        specs=specs,
        subplot_titles=subplot_titles,
    )

    # Create the main equity plot first
    fig = plot_equity_graph(fig, dfs_dict)

    # Add metrics table
    fig = add_metrics_to_figure(fig, metrics_dict)

    # Start from row 3 as rows 1-2 are used by equity plot and metrics
    table_row = 3
    for dte in sorted(dfs_dict.keys()):
        # Add monthly win rates table
        fig = add_win_rates_to_figure(fig, monthly_win_rates_dict[dte], table_row)

        # Bar chart goes in the next row
        bar_row = table_row + 1

        months = []
        winning_trades = []
        losing_trades = []

        for year, monthly_data in sorted(win_loss_analysis_dict[dte].items()):
            for month_stats in monthly_data:
                months.append(f"{year} {month_stats['Month']}")
                winning_trades.append(month_stats["Winning Trade Count"])
                losing_trades.append(month_stats["Losing Trade Count"])

        if months:
            fig.add_trace(
                go.Bar(
                    name="Winning Trades",
                    x=months,
                    y=winning_trades,
                    marker_color="#90EE90",
                    showlegend=False,
                ),
                row=bar_row,
                col=1,
            )

            fig.add_trace(
                go.Bar(
                    name="Losing Trades",
                    x=months,
                    y=losing_trades,
                    marker_color="#FFB6C1",
                    showlegend=False,
                ),
                row=bar_row,
                col=1,
            )

            fig.update_xaxes(tickangle=45, row=bar_row, col=1)
            fig.update_yaxes(title_text="Number of Trades", row=bar_row, col=1)

        # Increment table_row by 2 to skip the bar chart row
        table_row += 2

    fig.update_layout(
        height=total_height,
        template="plotly_white",
        showlegend=True,
        barmode="group",
        title_text=title,
        title=dict(
            x=0.5,
            xanchor="center",
            yanchor="top",
        ),
        margin=dict(r=50, t=120, b=20),
    )

    return fig


def _fetch_backtest_run_rows(db_path, strategy_name):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM backtest_runs WHERE Strategy=?", (strategy_name,))
    rows = cursor.fetchall()
    result = []
    for row in rows:
        result.append(BacktestRun(*row))
    return result


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Generate equity graphs and calculate portfolio metrics based on trades data from an SQLite database.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity. Can be specified multiple times.",
    )
    parser.add_argument(
        "--db-path", type=str, required=True, help="Path to the SQLite database file"
    )
    parser.add_argument(
        "--strategy-name",
        type=str,
        required=True,
        help="Strategy name (eg. ShortPutStrategy)",
    )
    parser.add_argument(
        "--output", type=str, help="Optional: Path to save the equity graph HTML file"
    )
    parser.add_argument(
        "--title",
        type=str,
        default="<< Missing Report Title >> - Cumulative Premium Kept by DTE",
        help="Optional: Title for the equity graph",
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    setup_logging(args.verbose)

    fig = generate_report(args.db_path, args.strategy_name, args.title)

    if not fig:
        return

    if args.output:
        html_content = create_html_output(fig)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"\nEquity graph and metrics saved to: {args.output}")
    else:
        fig.show()


if __name__ == "__main__":
    main()
