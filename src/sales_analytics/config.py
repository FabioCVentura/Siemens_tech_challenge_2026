from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "reports"

# CSV column names are compared without regard to order.
CSV_SCHEMAS: dict[str, tuple[str, ...]] = {
    "customers.csv": ("customer_id", "name", "country"),
    "orders.csv": ("order_id", "customer_id", "order_date", "total_amount"),
    "order_items.csv": (
        "order_item_id",
        "order_id",
        "product_name",
        "quantity",
        "unit_price",
    ),
}
# Set to True to permit columns not listed in CSV_SCHEMAS.
ALLOW_EXTRA_CSV_COLUMNS = False

# Defaults directly required by the exercise; change only if requirements change.
EXCLUDE_REFUNDS_FROM_CUSTOMER_REVENUE: bool = True
TOP_PRODUCTS_LIMIT: int = 5
BLANK_TOTAL_AMOUNT_DEFAULT: float = 0.0
WARN_NEGATIVE_QUANTITIES: bool = True
WARN_MISSING_FOREIGN_KEYS: bool = True
