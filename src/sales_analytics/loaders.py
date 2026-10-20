import logging
import math
from datetime import date
from pathlib import Path
from sqlite3 import Connection

import pandas as pd

from .config import DATA_DIR


logger = logging.getLogger(__name__)


def load_all_data(conn: Connection) -> None:
    """Load all source tables in foreign-key dependency order.

    Args:
        conn: SQLite connection with the pipeline schema initialized.

    Returns:
        None.
    """
    load_customers(conn)
    load_orders(conn)
    load_order_items(conn)


def _read_csv(filename: str, required_columns: tuple[str, ...]) -> list[dict[str, str]]:
    """Read a CSV as strings and validate its required columns.

    Args:
        filename: CSV filename relative to the configured data directory.
        required_columns: Column names that must be present in the CSV header.

    Returns:
        CSV records as dictionaries with string values.

    Raises:
        ValueError: If one or more required columns are absent.
        FileNotFoundError: If the requested CSV file does not exist.
    """
    path = Path(DATA_DIR) / filename
    dataframe = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing_columns = sorted(set(required_columns) - set(dataframe.columns))
    if missing_columns:
        raise ValueError(f"{path} is missing required columns: {', '.join(missing_columns)}")
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
    return int(text)


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
    """Return identifiers already loaded into a known pipeline table.

    Args:
        conn: SQLite connection containing the table.
        table: Table name to query.
        column: Identifier column name to select.

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
    """Commit a load and verify that its inserted row count matches expectation.

    Args:
        conn: SQLite connection containing the loaded table.
        table: Name of the table whose rows were loaded.
        starting_count: Number of rows in the table before this load.
        inserted_count: Number of rows successfully inserted in this load.

    Returns:
        None.

    Raises:
        RuntimeError: If the actual table count differs from the expected count.
    """
    conn.commit()
    actual_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    expected_count = starting_count + inserted_count
    if actual_count != expected_count:
        raise RuntimeError(
            f"Row count check failed for {table}: expected {expected_count}, "
            f"found {actual_count}."
        )
    logger.info(f"Loaded {inserted_count} rows into {table}; total row count is {actual_count}.")


def load_customers(conn: Connection) -> None:
    """Load valid customers and warn when malformed or duplicate rows are skipped.

    Args:
        conn: SQLite connection with the customers table initialized.

    Returns:
        None.
    """
    rows = _read_csv("customers.csv", ("customer_id", "name", "country"))
    starting_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    existing_ids = _existing_ids(conn, "customers", "customer_id")
    inserted_count = 0

    for line_number, row in enumerate(rows, start=2):
        try:
            customer_id = _parse_integer(row["customer_id"])
        except ValueError as error:
            logger.warning(f"Skipping customers.csv row {line_number}: invalid customer_id ({error}).")
            continue
        name = row["name"].strip()
        if not name:
            logger.warning(f"Skipping customers.csv row {line_number}: name is blank.")
            continue
        if customer_id in existing_ids:
            logger.warning(
                f"Skipping customers.csv row {line_number}: duplicate customer_id {customer_id}."
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


def load_orders(conn: Connection) -> None:
    """Load valid orders, default blank amounts to zero, and skip orphan records.

    Args:
        conn: SQLite connection with customers and orders already initialized.

    Returns:
        None.
    """
    rows = _read_csv("orders.csv", ("order_id", "customer_id", "order_date", "total_amount"))
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
            total_amount = 0.0 if not amount_text else _parse_number(amount_text)
        except ValueError as error:
            logger.warning(f"Skipping orders.csv row {line_number}: invalid order data ({error}).")
            continue

        if customer_id not in customer_ids:
            logger.warning(
                f"Skipping orders.csv row {line_number}: customer_id {customer_id} does not exist."
            )
            continue
        if order_id in existing_ids:
            logger.warning(
                f"Skipping orders.csv row {line_number}: duplicate order_id {order_id}."
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


def load_order_items(conn: Connection) -> None:
    """Load valid line items, warning on negative quantities and skipping orphans.

    Args:
        conn: SQLite connection with customers and orders already loaded.

    Returns:
        None.
    """
    rows = _read_csv(
        "order_items.csv",
        ("order_item_id", "order_id", "product_name", "quantity", "unit_price"),
    )
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
            logger.warning(
                f"Skipping order_items.csv row {line_number}: invalid item data ({error})."
            )
            continue
        product_name = row["product_name"].strip()
        if not product_name:
            logger.warning(f"Skipping order_items.csv row {line_number}: product_name is blank.")
            continue
        if order_id not in order_ids:
            logger.warning(
                f"Skipping order_items.csv row {line_number}: order_id {order_id} does not exist."
            )
            continue
        if order_item_id in existing_ids:
            logger.warning(
                f"Skipping order_items.csv row {line_number}: "
                f"duplicate order_item_id {order_item_id}."
            )
            continue
        if quantity < 0:
            logger.warning(
                f"Negative quantity {quantity} in order_items.csv row {line_number}."
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
