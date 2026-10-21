import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from sqlite3 import Connection

import pandas as pd

from .config import (
    ALLOW_EXTRA_CSV_COLUMNS,
    BLANK_TOTAL_AMOUNT_DEFAULT,
    CSV_SCHEMAS,
    DATA_DIR,
    WARN_MISSING_FOREIGN_KEYS,
    WARN_NEGATIVE_QUANTITIES,
)


logger = logging.getLogger(__name__)
_MAX_ISSUE_EXAMPLES = 3
_SQLITE_INTEGER_MIN = -(2**63)
_SQLITE_INTEGER_MAX = 2**63 - 1


@dataclass
class _DataQualitySummary:
    """Collect counts and representative row details for data-quality issues."""

    counts: Counter[str] = field(default_factory=Counter)
    examples: dict[str, list[str]] = field(default_factory=dict)

    def record(self, issue: str, detail: str) -> None:
        """Add one occurrence and retain a bounded number of examples.

        Args:
            issue: Short label identifying the data-quality issue.
            detail: Row-level context to include in the run log.

        Returns:
            None.
        """
        self.counts[issue] += 1
        issue_examples = self.examples.setdefault(issue, [])
        if len(issue_examples) < _MAX_ISSUE_EXAMPLES:
            issue_examples.append(detail)

    def log_warnings(self) -> None:
        """Write one warning per issue type, including counts and examples.

        Returns:
            None.
        """
        for issue, count in sorted(self.counts.items()):
            examples = "; ".join(self.examples[issue])
            logger.warning(
                f"Data quality issue '{issue}': {count} row(s). "
                f"Examples: {examples}.",
                extra={"affected_rows": count},
            )


def load_all_data(conn: Connection) -> None:
    """Atomically load all source tables in foreign-key dependency order.

    Args:
        conn: SQLite connection with the pipeline schema initialized.

    Returns:
        None.

    Raises:
        Exception: Re-raises any loading error after rolling back this load.
    """
    issues = _DataQualitySummary()
    conn.execute("SAVEPOINT sales_analytics_load")
    try:
        load_customers(conn, issues)
        load_orders(conn, issues)
        load_order_items(conn, issues)
        issues.log_warnings()
        conn.execute("RELEASE SAVEPOINT sales_analytics_load")
        row_counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("customers", "orders", "order_items")
        }
        logger.info(f"Data load committed; table row counts: {row_counts}.")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT sales_analytics_load")
        conn.execute("RELEASE SAVEPOINT sales_analytics_load")
        issues.log_warnings()
        raise


def _read_csv(
    filename: str,
    *,
    allow_extra_columns: bool | None = None,
) -> list[dict[str, str]]:
    """Read a configured CSV and enforce its column schema.

    Args:
        filename: CSV filename relative to the configured data directory.
        allow_extra_columns: Whether columns beyond the configured schema are
            accepted. Defaults to the project-level schema policy.

    Returns:
        CSV records as dictionaries with string values.

    Raises:
        ValueError: If the filename has no configured schema, required columns
            are missing, or unexpected columns are disallowed.
        FileNotFoundError: If the requested CSV file does not exist.
    """
    if filename not in CSV_SCHEMAS:
        raise ValueError(f"No CSV schema is configured for {filename}.")

    path = Path(DATA_DIR) / filename
    dataframe = pd.read_csv(path, dtype=str, keep_default_na=False)
    expected_columns = set(CSV_SCHEMAS[filename])
    actual_columns = set(dataframe.columns)
    missing_columns = sorted(expected_columns - actual_columns)
    extra_columns = sorted(actual_columns - expected_columns)
    reject_extra_columns = (
        not ALLOW_EXTRA_CSV_COLUMNS
        if allow_extra_columns is None
        else not allow_extra_columns
    )

    if missing_columns or (extra_columns and reject_extra_columns):
        problems = []
        if missing_columns:
            problems.append(f"missing required columns: {', '.join(missing_columns)}")
        if extra_columns and reject_extra_columns:
            problems.append(f"unexpected columns: {', '.join(extra_columns)}")
        raise ValueError(f"Invalid CSV '{path}': {'; '.join(problems)}.")

    return dataframe.to_dict(orient="records")


def _parse_integer(value: str) -> int:
    """Parse a non-blank integer field.

    Args:
        value: Text to parse as an integer.

    Returns:
        The parsed integer.

    Raises:
        ValueError: If the value is blank or is not a valid integer.
    """
    text = value.strip()
    if not text:
        raise ValueError("value is blank")
    integer = int(text)
    if not _SQLITE_INTEGER_MIN <= integer <= _SQLITE_INTEGER_MAX:
        raise ValueError("value is outside the SQLite integer range")
    return integer


def _parse_number(value: str) -> float:
    """Parse a finite, non-blank numeric field.

    Args:
        value: Text to parse as a floating-point number.

    Returns:
        The parsed finite number.

    Raises:
        ValueError: If the value is blank, invalid, or not finite.
    """
    text = value.strip()
    if not text:
        raise ValueError("value is blank")
    number = float(text)
    if not math.isfinite(number):
        raise ValueError("value must be finite")
    return number


def _existing_ids(conn: Connection, table: str, column: str) -> set[int]:
    """Return identifiers already loaded into a pipeline table.

    Args:
        conn: SQLite connection containing the table.
        table: Name of a known pipeline table.
        column: Name of that table's identifier column.

    Returns:
        A set containing the loaded integer identifiers.
    """
    rows = conn.execute(f"SELECT {column} FROM {table}").fetchall()
    return {int(row[0]) for row in rows}


def _finish_load(
    conn: Connection,
    table: str,
    starting_count: int,
    inserted_count: int,
) -> None:
    """Verify a table's row count after inserting its valid CSV records.

    Args:
        conn: SQLite connection containing the loaded table.
        table: Name of the table whose rows were loaded.
        starting_count: Number of rows before this table load.
        inserted_count: Number of successfully inserted rows.

    Returns:
        None.

    Raises:
        RuntimeError: If the actual row count differs from the expected count.
    """
    actual_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    expected_count = starting_count + inserted_count
    if actual_count != expected_count:
        raise RuntimeError(
            f"Row count check failed for {table}: expected {expected_count}, "
            f"found {actual_count}."
        )


def load_customers(
    conn: Connection,
    issues: _DataQualitySummary | None = None,
) -> None:
    """Load valid customers and record malformed or duplicate rows.

    Args:
        conn: SQLite connection with the customers table initialized.
        issues: Optional shared collector for run-level issue summaries.

    Returns:
        None.
    """
    issue_summary = issues if issues is not None else _DataQualitySummary()
    log_summary = issues is None
    rows = _read_csv("customers.csv")
    starting_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    existing_ids = _existing_ids(conn, "customers", "customer_id")
    inserted_count = 0

    for line_number, row in enumerate(rows, start=2):
        try:
            customer_id = _parse_integer(row["customer_id"])
        except ValueError as error:
            issue_summary.record(
                "invalid customer_id",
                f"customers.csv row {line_number}: {error}",
            )
            continue
        name = row["name"].strip()
        if not name:
            issue_summary.record(
                "missing customer name",
                f"customers.csv row {line_number}",
            )
            continue
        if customer_id in existing_ids:
            issue_summary.record(
                "duplicate customer_id",
                f"customers.csv row {line_number}: customer_id={customer_id}",
            )
            continue

        country = row["country"].strip() or None
        conn.execute(
            "INSERT INTO customers (customer_id, name, country) VALUES (?, ?, ?)",
            (customer_id, name, country),
        )
        existing_ids.add(customer_id)
        inserted_count += 1

    _finish_load(conn, "customers", starting_count, inserted_count)
    if log_summary:
        issue_summary.log_warnings()


def load_orders(
    conn: Connection,
    issues: _DataQualitySummary | None = None,
) -> None:
    """Load valid orders, default blank amounts, and record row-level issues.

    Args:
        conn: SQLite connection with customers and orders initialized.
        issues: Optional shared collector for run-level issue summaries.

    Returns:
        None.
    """
    issue_summary = issues if issues is not None else _DataQualitySummary()
    log_summary = issues is None
    rows = _read_csv("orders.csv")
    starting_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    existing_ids = _existing_ids(conn, "orders", "order_id")
    customer_ids = _existing_ids(conn, "customers", "customer_id")
    inserted_count = 0

    for line_number, row in enumerate(rows, start=2):
        try:
            order_id = _parse_integer(row["order_id"])
            customer_id = _parse_integer(row["customer_id"])
            order_date = row["order_date"].strip()
            parsed_date = date.fromisoformat(order_date)
            if parsed_date.isoformat() != order_date:
                raise ValueError("date must use YYYY-MM-DD format")
            amount_text = row["total_amount"].strip()
            if amount_text:
                total_amount = _parse_number(amount_text)
            else:
                total_amount = BLANK_TOTAL_AMOUNT_DEFAULT
                issue_summary.record(
                    "blank total_amount defaulted",
                    f"orders.csv row {line_number}: order_id={order_id}, "
                    f"default={total_amount}",
                )
        except ValueError as error:
            issue_summary.record(
                "invalid order data",
                f"orders.csv row {line_number}: {error}",
            )
            continue

        if customer_id not in customer_ids:
            if WARN_MISSING_FOREIGN_KEYS:
                issue_summary.record(
                    "missing customer foreign key",
                    f"orders.csv row {line_number}: customer_id={customer_id}",
                )
            continue
        if order_id in existing_ids:
            issue_summary.record(
                "duplicate order_id",
                f"orders.csv row {line_number}: order_id={order_id}",
            )
            continue

        conn.execute(
            """
            INSERT INTO orders (order_id, customer_id, order_date, total_amount)
            VALUES (?, ?, ?, ?)
            """,
            (order_id, customer_id, order_date, total_amount),
        )
        existing_ids.add(order_id)
        inserted_count += 1

    _finish_load(conn, "orders", starting_count, inserted_count)
    if log_summary:
        issue_summary.log_warnings()


def load_order_items(
    conn: Connection,
    issues: _DataQualitySummary | None = None,
) -> None:
    """Load valid line items and summarize format, quantity, and FK issues.

    Args:
        conn: SQLite connection with orders already loaded.
        issues: Optional shared collector for run-level issue summaries.

    Returns:
        None.
    """
    issue_summary = issues if issues is not None else _DataQualitySummary()
    log_summary = issues is None
    rows = _read_csv("order_items.csv")
    starting_count = conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0]
    existing_ids = _existing_ids(conn, "order_items", "order_item_id")
    order_ids = _existing_ids(conn, "orders", "order_id")
    inserted_count = 0

    for line_number, row in enumerate(rows, start=2):
        try:
            order_item_id = _parse_integer(row["order_item_id"])
            order_id = _parse_integer(row["order_id"])
            quantity = _parse_integer(row["quantity"])
            unit_price = _parse_number(row["unit_price"])
        except ValueError as error:
            issue_summary.record(
                "invalid order item data",
                f"order_items.csv row {line_number}: {error}",
            )
            continue
        product_name = row["product_name"].strip()
        if not product_name:
            issue_summary.record(
                "missing product_name",
                f"order_items.csv row {line_number}",
            )
            continue
        if order_id not in order_ids:
            if WARN_MISSING_FOREIGN_KEYS:
                issue_summary.record(
                    "missing order foreign key",
                    f"order_items.csv row {line_number}: order_id={order_id}",
                )
            continue
        if order_item_id in existing_ids:
            issue_summary.record(
                "duplicate order_item_id",
                f"order_items.csv row {line_number}: order_item_id={order_item_id}",
            )
            continue
        if quantity < 0 and WARN_NEGATIVE_QUANTITIES:
            issue_summary.record(
                "negative quantity retained",
                f"order_items.csv row {line_number}: "
                f"order_item_id={order_item_id}, quantity={quantity}",
            )

        conn.execute(
            """
            INSERT INTO order_items (
                order_item_id, order_id, product_name, quantity, unit_price
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (order_item_id, order_id, product_name, quantity, unit_price),
        )
        existing_ids.add(order_item_id)
        inserted_count += 1

    _finish_load(conn, "order_items", starting_count, inserted_count)
    if log_summary:
        issue_summary.log_warnings()
