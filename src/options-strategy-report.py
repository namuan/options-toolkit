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

from logger import setup_logging


@dataclass
class BacktestRun:
    run_id: int
    datetime: str
    strategy: str
    raw_params: str
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


def generate_report(db_path, strategy_name, title):
    print(
        f"\nFetching data from database: {db_path} looking for strategy {strategy_name}"
    )

    rows = _fetch_backtest_run_rows(db_path, strategy_name)
    logging.debug(f"Found {len(rows)} backtest runs for strategy {strategy_name}")

    return None


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
