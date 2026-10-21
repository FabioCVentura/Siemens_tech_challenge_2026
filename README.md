# Sales Analytics ETL Test

A practical coding exercise for Python data engineers. The pipeline creates an in-memory SQLite database, loads sales data, and generates basic reports. **It works, but requires improvements.**

## 🎯 Business Requirements & Tasks

### What the Application Does (Current State)

The pipeline processes **sales transaction data** for a B2B software company selling analytics tools:

1. **Data Sources**: 3 CSV files (`customers.csv`, `orders.csv`, `order_items.csv`)
2. **Processing**: Loads data into **in-memory SQLite** → runs SQL analytics → outputs CSV reports
3. **Current Reports**:
   - `revenue_per_customer_per_month.csv` - Revenue by customer/month (**TODO: implement report. Currently only placeholder report**)
   - `top_products.csv` - Top products by quantity (**TODO: implement report. Currently only placeholder report**)

**Current Issues**:
- Revenue per client per month and Top product reports need to be implemented.
- No data validation or error handling
- Hardcoded paths, no CLI arguments

### Business Requirements

The **sales director** needs **accurate, reliable reports** for monthly business reviews:

1. **Customer Revenue Trends**: Monthly revenue per customer **excluding refunds**
2. **Product Performance**: Top 5 products by **total revenue** generated
3. **Data Reliability**: Bad data must be **handled gracefully** without crashing
4. **Operational Flexibility**: Configurable output directory and date ranges

### 📋 Required Tasks

#### 1. Customer Revenue Report (Critical Business Need)

**Business context**: The sales director uses this report in monthly business reviews to track how much revenue each customer generated in each calendar month. This report needs to exclude refunds (negative-amount orders) to avoid understating real performance and confusion.

**Implement a SQL query in the `compute_revenue_per_customer_month` function found in `analytics.py`**:
- **Exclude refunds**: filter out any order where `total_amount < 0` — these are reversal/refund entries and must not count as revenue
- **Group correctly**: aggregate `SUM(total_amount)` per `(customer_id, year_month)` — `year_month`
- **Output columns** (in order): `customer_id`, `name`, `country`, `year_month`, `revenue`
- **Sort**: by `year_month` ASC, then `revenue` DESC within each month

**Expected output sample** (January 2025, Acme Corp):

| customer_id | name      | country | year_month | revenue |
|-------------|-----------|---------|------------|---------|
| 1           | Acme Corp | US      | 2025-01    | 1200.00 |

#### 2. Top Products Report (Critical Business Need)

**Business context**: The sales, marketing, and procurement teams use this report to identify the highest-earning products. The business needs ranking by **revenue generated** (`quantity × unit_price`) to reflect actual commercial performance.

**Implement a SQL query in the `compute_top_products` function found in `analytics.py`**:
- **Correct metric**: compute product revenue from all orders `quantity * unit_price` per product
- **Limit**: return only the top 5 products ordered by total revenue
- **Output columns** (in order): `product_name`, `total_revenue`

**Expected output format**:

| product_name      | total_revenue |
|-------------------|---------------|
| Laptop Pro        | 6000.00       |

#### 3. Data Quality Controls
**Requirement**: "Pipeline must **handle bad data** without crashing or corrupting reports."

**TODO**:
- Replace blank `total_amount` → `0.0` during CSV loading
- Log warnings for data quality issues (negative quantities, missing FKs)
- Validate row counts after each load step (customers → orders → order_items)

### ⭐ Bonus Tasks

#### 1. Database Optimization (Performance Requirement)
**Requirement**: "Queries must scale without significant slowdowns."

**TODO**:
- Add indexes: `customer_id` (FK), `order_date`

#### 2. CLI Configuration (Operations Requirement)
**Requirement**: "Ops team needs configurable output directory and date filtering."

**TODO** - Add `argparse` support:
```bash
python -m src.sales_analytics.main --output-dir ./custom_reports --from-date 2025-01-01 --to-date 2025-02-28
```

## 🚀 Setup & Run
The following are instructions to run the application on your local machine using [Conda environment manager](https://docs.conda.io/projects/conda/en/stable/user-guide/install/index.html). (If you don't like conda, feel free to use your favorite environment/package manager.)

### Linux/macOS (Bash/Zsh)

```bash
# Create and activate project-local conda environment
conda create --prefix .venv python=3.12 -y
conda activate ./.venv

# Install dependencies using the local environment
python -m pip install -r requirements.txt

# Run the pipeline
python -m src.sales_analytics.main
```

### Windows (Powershell/cmd)

```markdown
# Create and activate project-local conda environment
conda create --prefix .venv python=3.12 -y
conda activate .\.venv

# Install dependencies using the local environment
python -m pip install -r requirements.txt

# Run the pipeline
python -m src.sales_analytics.main
```

## Implementation Notes

- The customer revenue report groups by customer and calendar month and excludes negative-amount refund orders. The product report ranks by summed `quantity * unit_price` and returns five products. Blank `total_amount` values default to `0.0`; negative quantities and missing foreign keys are reported as required by the exercise.
- These configurable exercise settings are in `src/sales_analytics/config.py`: `EXCLUDE_REFUNDS_FROM_CUSTOMER_REVENUE`, `TOP_PRODUCTS_LIMIT`, `BLANK_TOTAL_AMOUNT_DEFAULT`, `WARN_NEGATIVE_QUANTITIES`, and `WARN_MISSING_FOREIGN_KEYS`. Their defaults implement the exercise. Change them only if the business requirements are revised.
- CSV headers are checked against the configured schemas in `src/sales_analytics/config.py`. Expected columns are required, unexpected columns are rejected by default, and column order does not matter. `ALLOW_EXTRA_CSV_COLUMNS` controls whether additional columns are accepted.
- A full data load is atomic: if reading, validating, or inserting any source table fails, all inserts from that load are rolled back. Row-level data issues are summarized by type with counts and up to three example rows per type.
- Integer fields must parse as integers; order dates must use `YYYY-MM-DD`; required text fields must be nonblank; numeric amounts and prices must be finite. Invalid rows and orphan foreign keys are skipped, while schema errors fail the load.
- The database indexes `orders.customer_id` and `orders.order_date`. Optional inclusive `YYYY-MM-DD` date bounds filter both reports by order date; the start date cannot be later than the end date.
- The documented CLI options are implemented: `--output-dir`, `--from-date`, and `--to-date`. Report queries, loader validation, and command-line behavior are documented in code docstrings and explicit log/error messages.
- Each run creates a timestamped log in the selected output directory. Its summary distinguishes warning categories from total affected rows; details and representative source rows are included. Pipeline exceptions are logged and re-raised.

### Suggestions to Discuss

- The exercise requires warning about negative quantities but does not specify whether those rows should be retained. They are currently retained, so their values contribute to product revenue.
- Missing foreign-key and malformed data rows are currently skipped after being counted and logged. Confirm whether a future business process should reject the full file instead.
- Currency report values are rounded to two decimal places. Confirm whether this is the desired reporting precision.
- The exercise does not define whether IDs or unit prices must be positive, or whether `orders.total_amount` must reconcile with its order-item totals. No such validation is applied; decide these rules with the business owner before adding them.

Run the end-to-end data-quality tests with the standard library test runner:

```bash
python -m unittest discover -s tests -v
```

Run with custom settings, for example:

```bash
python -m src.sales_analytics.main --output-dir ./custom_reports --from-date 2025-01-01 --to-date 2025-02-28
```
