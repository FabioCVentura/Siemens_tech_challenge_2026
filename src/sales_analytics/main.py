import argparse
import logging
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from .db import create_in_memory_db
from .loaders import load_all_data
from .analytics import generate_reports
from .config import DEFAULT_REPORTS_DIR


class _RunSummaryFilter(logging.Filter):
    """Count warning and error records emitted during one pipeline run."""

    def __init__(self) -> None:
        """Initialize the per-run severity counters.

        Returns:
            None.
        """
        super().__init__()
        self.warning_count = 0
        self.error_count = 0

    def filter(self, record: logging.LogRecord) -> bool:
        """Count a log record while allowing it through to the log file.

        Args:
            record: Log record being handled by the file handler.

        Returns:
            True so the record is written to the log file.
        """
        if record.levelno >= logging.ERROR:
            self.error_count += 1
        elif record.levelno >= logging.WARNING:
            self.warning_count += 1
        return True


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

    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_path = args.output_dir / f"sales_analytics_{run_id}.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_logger = logging.getLogger("src.sales_analytics")
    run_logger.setLevel(logging.INFO)
    run_logger.propagate = False

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    summary_filter = _RunSummaryFilter()
    file_handler.addFilter(summary_filter)
    run_logger.addHandler(console_handler)
    run_logger.addHandler(file_handler)

    conn = None
    status = "succeeded"
    try:
        run_logger.info(
            f"Run started; output_dir={args.output_dir}; "
            f"from_date={args.from_date}; to_date={args.to_date}."
        )
        conn = create_in_memory_db()
        load_all_data(conn)
        generate_reports(
            conn,
            output_dir=args.output_dir,
            from_date=args.from_date,
            to_date=args.to_date,
        )
        run_logger.info(f"Reports written to {args.output_dir}.")
    except Exception:
        status = "failed"
        run_logger.exception("Pipeline run failed.")
        raise
    finally:
        if conn is not None:
            conn.close()
        run_logger.info(
            f"Run summary: status={status}; warnings={summary_filter.warning_count}; "
            f"errors={summary_filter.error_count}; log_file={log_path}."
        )
        run_logger.removeHandler(console_handler)
        run_logger.removeHandler(file_handler)
        console_handler.close()
        file_handler.close()


if __name__ == "__main__":
    main()
