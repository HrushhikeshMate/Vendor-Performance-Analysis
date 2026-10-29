
import sqlite3
import pandas as pd
import logging
import time
import numpy as np
from pathlib import Path

# --------------------------------------------------
# 1. SET UP PATHS
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "inventory.db"
LOG_DIR = BASE_DIR / "logs"

LOG_DIR.mkdir(exist_ok=True)

# --------------------------------------------------
# 2. CONFIGURE LOGGING
# --------------------------------------------------

logging.basicConfig(
    filename=LOG_DIR / "get_vendor_summary.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode="a"
)

# --------------------------------------------------
# 3. SQL QUERY
# --------------------------------------------------

QUERY = """
WITH FreightSummary AS (
    SELECT
        VendorNumber,
        SUM(Freight) AS FreightCost
    FROM vendor_invoice
    GROUP BY VendorNumber
),

PurchaseSummary AS (
    SELECT
        p.VendorNumber,
        p.VendorName,
        p.Brand,
        p.Description,
        p.PurchasePrice,
        pp.Price AS ActualPrice,
        pp.Volume,
        SUM(p.Quantity) AS TotalPurchaseQuantity,
        SUM(p.Dollars) AS TotalPurchaseDollars
    FROM purchases p
    JOIN purchase_prices pp
        ON p.Brand = pp.Brand
    WHERE p.PurchasePrice > 0
    GROUP BY
        p.VendorNumber,
        p.VendorName,
        p.Brand,
        p.Description,
        p.PurchasePrice,
        pp.Price,
        pp.Volume
),

SalesSummary AS (
    SELECT
        VendorNo,
        Brand,
        SUM(SalesQuantity) AS TotalSalesQuantity,
        SUM(SalesDollars) AS TotalSalesDollars,
        SUM(SalesPrice) AS TotalSalesPrice,
        SUM(ExciseTax) AS TotalExciseTax
    FROM sales
    GROUP BY VendorNo, Brand
)

SELECT
    ps.VendorNumber,
    ps.VendorName,
    ps.Brand,
    ps.Description,
    ps.PurchasePrice,
    ps.ActualPrice,
    ps.Volume,
    ps.TotalPurchaseQuantity,
    ps.TotalPurchaseDollars,
    ss.TotalSalesQuantity,
    ss.TotalSalesDollars,
    ss.TotalSalesPrice,
    ss.TotalExciseTax,
    fs.FreightCost
FROM PurchaseSummary ps

LEFT JOIN SalesSummary ss
    ON ps.VendorNumber = ss.VendorNo
    AND ps.Brand = ss.Brand

LEFT JOIN FreightSummary fs
    ON ps.VendorNumber = fs.VendorNumber

ORDER BY ps.TotalPurchaseDollars DESC
"""

# --------------------------------------------------
# 4. CLEAN DATA
# --------------------------------------------------

def clean_data(df):
    """Clean vendor summary and create KPIs."""

    df["Volume"] = pd.to_numeric(
        df["Volume"], errors="coerce"
    )

    numeric_columns = [
        "TotalPurchaseQuantity",
        "TotalPurchaseDollars",
        "TotalSalesQuantity",
        "TotalSalesDollars",
        "TotalSalesPrice",
        "TotalExciseTax",
        "FreightCost"
    ]

    df[numeric_columns] = df[numeric_columns].fillna(0)

    df["VendorName"] = df["VendorName"].fillna("").str.strip()
    df["Description"] = df["Description"].fillna("").str.strip()

    # Gross Profit
    df["GrossProfit"] = (
        df["TotalSalesDollars"]
        - df["TotalPurchaseDollars"]
    )

    # Profit Margin
    df["ProfitMargin"] = np.where(
        df["TotalSalesDollars"] != 0,
        df["GrossProfit"]
        / df["TotalSalesDollars"].replace(0, np.nan) * 100,
        0
    )

    # Stock Turnover
    df["StockTurnover"] = (
        df["TotalSalesQuantity"]
        / df["TotalPurchaseQuantity"].replace(0, np.nan)
    ).fillna(0)

    # Sales to Purchase Ratio
    df["SalesToPurchaseRatio"] = (
        df["TotalSalesDollars"]
        / df["TotalPurchaseDollars"].replace(0, np.nan)
    ).fillna(0)

    return df


# --------------------------------------------------
# 5. CREATE VENDOR SUMMARY
# --------------------------------------------------


def create_vendor_summary(conn):
    """Build vendor summary using a separate temporary database."""

    import sqlite3
    import time

    start = time.perf_counter()

    temp_db_path = BASE_DIR / "vendor_summary_temp.db"

    # Separate database for writing results
    temp_conn = sqlite3.connect(temp_db_path)

    total_rows = 0
    first_chunk = True

    try:
        print("Creating vendor sales summary...")

        for chunk in pd.read_sql_query(
            QUERY,
            conn,
            chunksize=5000
        ):
            clean_df = clean_data(chunk)

            mode = "replace" if first_chunk else "append"

            clean_df.to_sql(
                "vendor_sales_summary",
                temp_conn,
                if_exists=mode,
                index=False,
                chunksize=1000
            )

            temp_conn.commit()

            total_rows += len(clean_df)
            first_chunk = False

            print(f"Processed {total_rows:,} rows")

        if first_chunk:
            raise ValueError("SQL query returned no rows.")

    finally:
        temp_conn.close()

    # The SQL reader must be finished before writing
    # to the original database.
    conn.execute(
        "ATTACH DATABASE ? AS temp_summary",
        (str(temp_db_path),)
    )

    try:
        conn.execute("DROP TABLE IF EXISTS vendor_sales_summary")

        conn.execute("""
            CREATE TABLE vendor_sales_summary AS
            SELECT *
            FROM temp_summary.vendor_sales_summary
        """)

        conn.commit()
    finally:
        conn.execute("DETACH DATABASE temp_summary")

    elapsed = time.perf_counter() - start

    print("\nVendor Summary Completed!")
    print(f"Total Rows: {total_rows:,}")
    print(f"Time Taken: {elapsed:.2f} seconds")
    print(f"Time Taken: {elapsed / 60:.2f} minutes")

    return total_rows



# --------------------------------------------------
# 6. MAIN EXECUTION
# --------------------------------------------------

if __name__ == "__main__":

    start_time = time.perf_counter()
    conn = None

    try:
        if not DB_PATH.is_file():
            raise FileNotFoundError(
                f"Database not found: {DB_PATH}"
            )

        conn = sqlite3.connect(DB_PATH)

        total_rows = create_vendor_summary(conn)

        end_time = time.perf_counter()
        total_seconds = end_time - start_time
        total_minutes = total_seconds / 60

        print("\n--------------------------------")
        print("Vendor Summary Completed!")
        print(f"Total Rows: {total_rows:,}")
        print(f"Time Taken: {total_seconds:.2f} seconds")
        print(f"Time Taken: {total_minutes:.2f} minutes")
        print("--------------------------------")

        logging.info("Vendor Summary Completed")
        logging.info(
            f"Execution Time: {total_minutes:.2f} minutes"
        )

    except Exception as e:
        print(f"Error: {e}")
        logging.exception("Vendor summary failed")
        raise

    finally:
        if conn is not None:
            conn.close()
