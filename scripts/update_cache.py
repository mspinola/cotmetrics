import os
import sys
import shutil

# Add src to the Python path so we can import core modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import cotmetrics.constants as const
import cotmetrics.utils as utils
from cotmetrics.indexer import get_indexer

def run_cache_update():
    """
    Forces the COT Analyzer cache to rebuild.
    This ensures that any newly pushed mathematical metrics (like the LSR 1.0 division-by-zero patch)
    are calculated and persisted to the underlying Parquet datasets.
    """
    logger = utils.get_cot_logger()
    logger.info("Starting forced cache update...")

    # 1. Flush existing cache
    if os.path.exists(const.CACHE_DIR):
        logger.info(f"Flushing existing cache directory: {const.CACHE_DIR}")
        for filename in os.listdir(const.CACHE_DIR):
            # VERY IMPORTANT: Do NOT delete the options directory or any subdirectories. 
            # The daily options data is accretive and cannot be historically reconstructed from the API!
            file_path = os.path.join(const.CACHE_DIR, filename)
            if os.path.isfile(file_path) and file_path.endswith('.parquet'):
                try:
                    os.unlink(file_path)
                except Exception as e:
                    logger.error(f"Failed to delete {file_path}. Reason: {e}")
    else:
        logger.info(f"Cache directory {const.CACHE_DIR} does not exist. Creating it...")
        os.makedirs(const.CACHE_DIR)

    # 2. Re-calculate metrics from raw CSVs
    logger.info("Rebuilding metrics and data schemas...")
    try:
        indexer = get_indexer()
        indexer.populate_instruments()
        # Because we deleted the COT parquet files in step 1, the engine will natively rebuild them.
        # We MUST use force_refresh=False so it natively utilizes the Databento price caches in data_cache/ml/
        # Passing True attempts a 15-year synchronous Databento fetch, which the API rejects (causing empty prices).
        indexer.calculate_weekly_data(force_refresh=False)

        logger.info("Exporting summary matrices...")
        indexer.export_cot_data_to_csv()
        indexer.export_weekly_summary_results_to_csv()
        indexer.export_real_test_data_to_csv()
        
        logger.info("Cache successfully rebuilt! The dashboard will now reflect the latest mathematics.")
    except Exception as e:
        logger.error(f"Failed to rebuild cache: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_cache_update()
