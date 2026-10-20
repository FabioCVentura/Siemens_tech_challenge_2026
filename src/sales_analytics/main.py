import argparse
import logging
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from .db import create_in_memory_db
from .loaders import load_all_data
from .analytics import generate_reports
from .config import DEFAULT_REPORTS_DIR


def _parse_iso_date(value: str) -> date:
    """Parse an ISO calendar date for an argparse option.

    Args:
        value: Date text in YYYY-MM-DD format.

    Returns:
        The parsed calendar date.

    Raises:
        argparse.ArgumentTypeError: If value is not a valid YYYY-MM-DD date.
    """
    try:
        parsed_date = date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from error
    if parsed_date.isoformat() != value:
        raise argparse.ArgumentTypeError(f"Invalid date {value!r}; expected YYYY-MM-DD.")
    return parsed_date


def _build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for report output and date filtering.

    Returns:
        An argument parser configured with the pipeline's CLI options.
    """
    parser = argparse.ArgumentParser(description="Load sales data and generate CSV reports.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_REPORTS_DIR,
        help=f"Directory for generated CSV reports (default: {DEFAULT_REPORTS_DIR}).",
    )
    parser.add_argument(
        "--from-date",
        type=_parse_iso_date,
        help="Include orders on or after this date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--to-date",
        type=_parse_iso_date,
        help="Include orders on or before this date (YYYY-MM-DD).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Load sales data and generate reports using the requested options.

    Args:
        argv: Optional command-line argument sequence. When omitted, arguments
            are read from the process command line.

    Returns:
        None.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.from_date is not None and args.to_date is not None:
        if args.from_date > args.to_date:
            parser.error("--from-date must not be later than --to-date.")

    conn = create_in_memory_db()
    try:
        load_all_data(conn)
        generate_reports(
            conn,
            output_dir=args.output_dir,
            from_date=args.from_date,
            to_date=args.to_date,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
