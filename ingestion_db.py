
import pandas as pd
from pathlib import Path
from sqlalchemy import create_engine
import logging
import time

# Set up project directories
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=LOG_DIR / "ingestion_db.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode="a"
)

# Create SQLite engine
engine = create_engine(
    f"sqlite:///{(BASE_DIR / 'inventory.db').as_posix()}"
)

def ingest_db(df, table_name, engine, if_exists):
    """Insert a dataframe chunk into SQLite."""
    df.to_sql(
        table_name,
        con=engine,
        if_exists=if_exists,
        index=False,
        chunksize=1000
    )

def load_raw_data():
    """Load CSV files into SQLite using chunks."""
    start = time.time()

    for file in DATA_DIR.glob("*.csv"):
        print(f"Processing: {file.name}")

        first_chunk = True
        total_rows = 0

        for chunk in pd.read_csv(file, chunksize=10000):

            # Replace table for first chunk only
            mode = "replace" if first_chunk else "append"

            ingest_db(chunk, file.stem, engine, mode)

            first_chunk = False
            total_rows += len(chunk)

            print(f"Inserted {total_rows} rows")

        logging.info(
            f"Loaded {file.name}: {total_rows} rows"
        )

        print(f"Completed: {file.name}")

    total_time = (time.time() - start) / 60

    logging.info("Ingestion Complete")
    logging.info(f"Total Time: {total_time:.2f} minutes")

    print(f"Ingestion Complete! Time: {total_time:.2f} minutes")


if __name__ == "__main__":
    load_raw_data()
