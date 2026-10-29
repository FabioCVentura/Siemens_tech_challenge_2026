from datetime import date
from pathlib import Path
from sqlite3 import Connection

import pandas as pd

from .config import EXCLUDE_REFUNDS_FROM_CUSTOMER_REVENUE, TOP_PRODUCTS_LIMIT


def _date_filters(
    from_date: date | None,
    to_date: date | None,
) -> tuple[list[str], list[str]]:
    """Build parameterized, inclusive order-date filters for report queries.

    Args:
        from_date: Optional lower bound for the order date.
        to_date: Optional upper bound for the order date.

    Returns:
        A tuple containing SQL filter expressions and their bound parameters.

    Raises:
        ValueError: If the lower date bound is later than the upper bound.
    """
    filters: list[str] = []
    parameters: list[str] = []

    if from_date is not None and to_date is not None and from_date > to_date:
        raise ValueError("from_date must not be later than to_date.")
    if from_date is not None:
        filters.append("o.order_date >= ?")
        parameters.append(from_date.isoformat())
    if to_date is not None:
        filters.append("o.order_date <= ?")
        parameters.append(to_date.isoformat())

    return filters, parameters


def compute_revenue_per_customer_month(
    conn: Connection,
    from_date: date | None = None,
    to_date: date | None = None,
    exclude_refunds: bool = EXCLUDE_REFUNDS_FROM_CUSTOMER_REVENUE,
) -> pd.DataFrame:
    """Return non-refund revenue per customer and calendar month.

    Optional date bounds are inclusive and apply to the order date.

    Args:
        conn: SQLite connection containing the sales tables.
        from_date: Optional inclusive lower bound for the order date.
        to_date: Optional inclusive upper bound for the order date.
        exclude_refunds: Whether to exclude orders with negative totals.

    Returns:
        A DataFrame with customer_id, name, country, year_month, and revenue
        columns, sorted by month ascending and revenue descending.
    """
    filters, parameters = _date_filters(from_date, to_date)
    if exclude_refunds:
        filters.insert(0, "o.total_amount >= 0")
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    query = f"""
        SELECT
            c.customer_id,
            c.name,
            c.country,
            strftime('%Y-%m', o.order_date) AS year_month,
            ROUND(SUM(o.total_amount), 2) AS revenue
        FROM orders AS o
        JOIN customers AS c ON c.customer_id = o.customer_id
        {where_clause}
        GROUP BY c.customer_id, c.name, c.country, year_month
        ORDER BY year_month ASC, revenue DESC, c.customer_id ASC
    """
    return pd.read_sql_query(query, conn, params=parameters)


def compute_top_products(
    conn: Connection,
    limit: int = TOP_PRODUCTS_LIMIT,
    from_date: date | None = None,
    to_date: date | None = None,
) -> pd.DataFrame:
    """Return products ranked by quantity multiplied by unit price.

    Optional date bounds are inclusive and apply to the order date.

    Args:
        conn: SQLite connection containing the sales tables.
        limit: Maximum number of products to return; must be positive.
        from_date: Optional inclusive lower bound for the order date.
        to_date: Optional inclusive upper bound for the order date.

    Returns:
        A DataFrame with product_name and total_revenue columns, sorted by
        revenue descending.

    Raises:
        ValueError: If limit is not positive or the date bounds are reversed.
    """
    if limit <= 0:
        raise ValueError("limit must be greater than zero.")

    filters, parameters = _date_filters(from_date, to_date)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    query = f"""
        SELECT
            oi.product_name,
            ROUND(SUM(oi.quantity * oi.unit_price), 2) AS total_revenue
        FROM order_items AS oi
        JOIN orders AS o ON o.order_id = oi.order_id
        {where_clause}
        GROUP BY oi.product_name
        ORDER BY total_revenue DESC, oi.product_name ASC
        LIMIT ?
    """
    return pd.read_sql_query(query, conn, params=[*parameters, limit])


def generate_reports(
    conn: Connection,
    output_dir: Path,
    from_date: date | None = None,
    to_date: date | None = None,
    *,
    top_products_limit: int = TOP_PRODUCTS_LIMIT,
    exclude_refunds: bool = EXCLUDE_REFUNDS_FROM_CUSTOMER_REVENUE,
) -> None:
    """Write the customer revenue and top-product reports as CSV files.

    Args:
        conn: SQLite connection containing the sales tables.
        output_dir: Directory where the report CSV files will be written.
        from_date: Optional inclusive lower bound for the order date.
        to_date: Optional inclusive upper bound for the order date.
        top_products_limit: Maximum products included in the product report.
        exclude_refunds: Whether customer revenue excludes refund orders.

    Returns:
        None.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    df_rev = compute_revenue_per_customer_month(
        conn,
        from_date,
        to_date,
        exclude_refunds=exclude_refunds,
    )
    df_rev.to_csv(output_dir / "revenue_per_customer_per_month.csv", index=False)

    df_top = compute_top_products(
        conn,
        limit=top_products_limit,
        from_date=from_date,
        to_date=to_date,
    )
    df_top.to_csv(output_dir / "top_products.csv", index=False)
