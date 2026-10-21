import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.sales_analytics import loaders
from src.sales_analytics.analytics import (
    compute_revenue_per_customer_month,
    compute_top_products,
)
from src.sales_analytics.db import create_in_memory_db
from src.sales_analytics.main import _RunSummaryFilter


class DataQualityEndToEndTests(unittest.TestCase):
    """Exercise CSV validation, atomic loading, quality summaries, and reports."""

    def setUp(self) -> None:
        """Create isolated input files and an initialized in-memory database.

        Returns:
            None.
        """
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.data_dir_patch = patch.object(loaders, "DATA_DIR", self.data_dir)
        self.data_dir_patch.start()
        self.connection = create_in_memory_db()

    def tearDown(self) -> None:
        """Close test resources and restore the configured data directory.

        Returns:
            None.
        """
        self.connection.close()
        self.data_dir_patch.stop()
        self.temp_dir.cleanup()

    def _write_csv(
        self,
        filename: str,
        columns: list[str],
        rows: list[dict[str, str]],
    ) -> None:
        """Write a CSV fixture with exactly the requested headers and rows.

        Args:
            filename: Name of the CSV file to create in the temporary directory.
            columns: Ordered header fields to write.
            rows: Row mappings; absent values are written as empty strings.

        Returns:
            None.
        """
        with (self.data_dir / filename).open(
            "w",
            encoding="utf-8",
            newline="",
        ) as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def _write_valid_customers(self) -> None:
        """Write the minimal valid customer table needed by loader scenarios.

        Returns:
            None.
        """
        self._write_csv(
            "customers.csv",
            ["customer_id", "name", "country"],
            [{"customer_id": "1", "name": "Acme", "country": "US"}],
        )

    def _write_valid_orders(self) -> None:
        """Write the minimal valid order table needed by loader scenarios.

        Returns:
            None.
        """
        self._write_csv(
            "orders.csv",
            ["order_id", "customer_id", "order_date", "total_amount"],
            [
                {
                    "order_id": "1",
                    "customer_id": "1",
                    "order_date": "2025-01-01",
                    "total_amount": "10.00",
                }
            ],
        )

    def _write_valid_items(self) -> None:
        """Write the minimal valid line-item table needed by loader scenarios.

        Returns:
            None.
        """
        self._write_csv(
            "order_items.csv",
            ["order_item_id", "order_id", "product_name", "quantity", "unit_price"],
            [
                {
                    "order_item_id": "1",
                    "order_id": "1",
                    "product_name": "Widget",
                    "quantity": "1",
                    "unit_price": "10.00",
                }
            ],
        )

    def test_data_issues_are_summarized_and_reports_use_valid_rows(self) -> None:
        """Validate mixed-quality records and verify resulting report data.

        Returns:
            None.
        """
        self._write_csv(
            "customers.csv",
            ["customer_id", "name", "country"],
            [
                {"customer_id": "1", "name": "Acme", "country": "US"},
                {"customer_id": "2", "name": "Beta", "country": ""},
                {"customer_id": "bad", "name": "Invalid ID", "country": "US"},
                {"customer_id": "3", "name": "", "country": "US"},
                {"customer_id": "1", "name": "Duplicate", "country": "US"},
            ],
        )
        self._write_csv(
            "orders.csv",
            ["order_id", "customer_id", "order_date", "total_amount"],
            [
                {
                    "order_id": "1",
                    "customer_id": "1",
                    "order_date": "2025-01-01",
                    "total_amount": "-15",
                },
                {
                    "order_id": "2",
                    "customer_id": "1",
                    "order_date": "2025-01-02",
                    "total_amount": "",
                },
                {
                    "order_id": "3",
                    "customer_id": "2",
                    "order_date": "2025-02-01",
                    "total_amount": "30",
                },
                {
                    "order_id": "4",
                    "customer_id": "99",
                    "order_date": "2025-01-03",
                    "total_amount": "20",
                },
                {
                    "order_id": "5",
                    "customer_id": "1",
                    "order_date": "01/03/2025",
                    "total_amount": "10",
                },
                {
                    "order_id": "6",
                    "customer_id": "1",
                    "order_date": "2025-01-04",
                    "total_amount": "NaN",
                },
                {
                    "order_id": "",
                    "customer_id": "1",
                    "order_date": "2025-01-05",
                    "total_amount": "10",
                },
                {
                    "order_id": "2",
                    "customer_id": "1",
                    "order_date": "2025-01-06",
                    "total_amount": "10",
                },
            ],
        )
        self._write_csv(
            "order_items.csv",
            ["order_item_id", "order_id", "product_name", "quantity", "unit_price"],
            [
                {
                    "order_item_id": "1",
                    "order_id": "1",
                    "product_name": "Refund",
                    "quantity": "-1",
                    "unit_price": "10",
                },
                {
                    "order_item_id": "2",
                    "order_id": "2",
                    "product_name": "Standard",
                    "quantity": "2",
                    "unit_price": "5",
                },
                {
                    "order_item_id": "3",
                    "order_id": "3",
                    "product_name": "Standard",
                    "quantity": "2",
                    "unit_price": "10",
                },
                {
                    "order_item_id": "4",
                    "order_id": "999",
                    "product_name": "Orphan",
                    "quantity": "1",
                    "unit_price": "1",
                },
                {
                    "order_item_id": "5",
                    "order_id": "1",
                    "product_name": "Decimal Quantity",
                    "quantity": "1.5",
                    "unit_price": "1",
                },
                {
                    "order_item_id": "6",
                    "order_id": "1",
                    "product_name": "Infinite Price",
                    "quantity": "1",
                    "unit_price": "inf",
                },
                {
                    "order_item_id": "7",
                    "order_id": "1",
                    "product_name": "",
                    "quantity": "1",
                    "unit_price": "1",
                },
                {
                    "order_item_id": "1",
                    "order_id": "1",
                    "product_name": "Duplicate",
                    "quantity": "1",
                    "unit_price": "1",
                },
            ],
        )

        with self.assertLogs(loaders.logger, level="WARNING") as captured:
            loaders.load_all_data(self.connection)

        warning_text = "\n".join(captured.output)
        self.assertIn("blank total_amount defaulted': 1 row(s)", warning_text)
        self.assertIn("missing customer foreign key': 1 row(s)", warning_text)
        self.assertIn("invalid order data': 3 row(s)", warning_text)
        self.assertIn("negative quantity retained': 1 row(s)", warning_text)
        self.assertIn("order_items.csv row 2", warning_text)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
            2,
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            3,
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM order_items").fetchone()[0],
            3,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT total_amount FROM orders WHERE order_id = 2"
            ).fetchone()[0],
            0.0,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT quantity FROM order_items WHERE order_item_id = 1"
            ).fetchone()[0],
            -1,
        )

        revenue = compute_revenue_per_customer_month(self.connection)
        self.assertEqual(
            revenue[["customer_id", "year_month", "revenue"]].values.tolist(),
            [[1, "2025-01", 0.0], [2, "2025-02", 30.0]],
        )
        products = compute_top_products(self.connection)
        self.assertEqual(
            products[["product_name", "total_revenue"]].values.tolist(),
            [["Standard", 30.0], ["Refund", -10.0]],
        )

    def test_schema_errors_abort_and_roll_back_the_full_load(self) -> None:
        """Reject missing or unexpected columns and roll back prior table inserts.

        Returns:
            None.
        """
        for item_columns in (
            ["order_item_id", "order_id", "product_name", "quantity"],
            [
                "order_item_id",
                "order_id",
                "product_name",
                "quantity",
                "unit_price",
                "unexpected",
            ],
        ):
            with self.subTest(item_columns=item_columns):
                self.connection.close()
                self.connection = create_in_memory_db()
                self._write_valid_customers()
                self._write_valid_orders()
                self._write_csv(
                    "order_items.csv",
                    item_columns,
                    [
                        {
                            "order_item_id": "1",
                            "order_id": "1",
                            "product_name": "Widget",
                            "quantity": "1",
                            "unit_price": "10",
                            "unexpected": "not allowed",
                        }
                    ],
                )

                with self.assertRaisesRegex(ValueError, "Invalid CSV"):
                    loaders.load_all_data(self.connection)

                for table in ("customers", "orders", "order_items"):
                    self.assertEqual(
                        self.connection.execute(
                            f"SELECT COUNT(*) FROM {table}"
                        ).fetchone()[0],
                        0,
                    )

    def test_extra_columns_can_be_enabled_by_configuration(self) -> None:
        """Allow otherwise-unexpected columns when the configured policy opts in.

        Returns:
            None.
        """
        self._write_csv(
            "customers.csv",
            ["customer_id", "name", "country", "source"],
            [{"customer_id": "1", "name": "Acme", "country": "US", "source": "test"}],
        )
        self._write_csv(
            "orders.csv",
            ["order_id", "customer_id", "order_date", "total_amount", "source"],
            [
                {
                    "order_id": "1",
                    "customer_id": "1",
                    "order_date": "2025-01-01",
                    "total_amount": "10",
                    "source": "test",
                }
            ],
        )
        self._write_csv(
            "order_items.csv",
            ["order_item_id", "order_id", "product_name", "quantity", "unit_price", "source"],
            [
                {
                    "order_item_id": "1",
                    "order_id": "1",
                    "product_name": "Widget",
                    "quantity": "1",
                    "unit_price": "10",
                    "source": "test",
                }
            ],
        )

        with patch.object(loaders, "ALLOW_EXTRA_CSV_COLUMNS", True):
            loaders.load_all_data(self.connection)

        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM order_items").fetchone()[0],
            1,
        )

    def test_configurable_exercise_rules(self) -> None:
        """Verify the exercise rules can be changed through configuration.

        Returns:
            None.
        """
        self._write_valid_customers()
        self._write_csv(
            "orders.csv",
            ["order_id", "customer_id", "order_date", "total_amount"],
            [
                {
                    "order_id": "1",
                    "customer_id": "1",
                    "order_date": "2025-01-01",
                    "total_amount": "-5",
                },
                {
                    "order_id": "2",
                    "customer_id": "1",
                    "order_date": "2025-01-02",
                    "total_amount": "",
                },
            ],
        )
        self._write_csv(
            "order_items.csv",
            ["order_item_id", "order_id", "product_name", "quantity", "unit_price"],
            [],
        )

        with patch.object(loaders, "BLANK_TOTAL_AMOUNT_DEFAULT", 2.5):
            loaders.load_all_data(self.connection)

        amount = self.connection.execute(
            "SELECT total_amount FROM orders WHERE order_id = 2"
        ).fetchone()[0]
        self.assertEqual(amount, 2.5)

        with patch(
            "src.sales_analytics.analytics.EXCLUDE_REFUNDS_FROM_CUSTOMER_REVENUE",
            False,
        ):
            revenue = compute_revenue_per_customer_month(self.connection)
        self.assertEqual(revenue.iloc[0].revenue, -2.5)

    def test_run_summary_counts_affected_rows_not_only_warning_categories(self) -> None:
        """Count affected data rows attached to categorized warning records.

        Returns:
            None.
        """
        summary_filter = _RunSummaryFilter()
        warning = unittest.mock.Mock(levelno=30, affected_rows=4)
        other_warning = unittest.mock.Mock(levelno=30, affected_rows=3)
        error = unittest.mock.Mock(levelno=40, affected_rows=0)

        summary_filter.filter(warning)
        summary_filter.filter(other_warning)
        summary_filter.filter(error)

        self.assertEqual(summary_filter.warning_count, 2)
        self.assertEqual(summary_filter.affected_row_count, 7)
        self.assertEqual(summary_filter.error_count, 1)


if __name__ == "__main__":
    unittest.main()
