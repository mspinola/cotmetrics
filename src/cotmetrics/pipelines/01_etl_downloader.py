
import yaml

import cotmetrics.config as config
import cotmetrics.utils as utils
from cotmetrics.etl import CotExtractor, CotLoader, CotTransformer


def get_years_to_process():
    # Same cwd-relative trap as CotJobScheduler.get_years_to_process; see the note there.
    param_dir = config.params_path()
    years = []
    with open(param_dir, 'r') as yf:
        yaml_data = yaml.safe_load(yf)
        for year in yaml_data["years"]:
            years.append(year)
    return years

def run_etl_pipeline():
    """
    Step 1 of the Decoupled Data Pipeline.
    Downloads the latest CFTC zip files using CotExtractor, processes them with
    CotTransformer, and saves them to parquet using CotLoader.
    """
    logger = utils.get_cot_logger()
    logger.info("Starting ETL Downloader Pipeline (Decoupled Classes)...")

    years_to_process = get_years_to_process()

    # 1. Extract
    extractor = CotExtractor()
    logger.info("Checking for new CFTC zip files...")
    updated_years = extractor.fetch_updates(years_to_process)

    if not updated_years:
        logger.info("No new data found on CFTC servers.")
    else:
        logger.info(f"Updated data found for years: {updated_years}")

    # 2. Transform
    logger.info("Converting raw .xls files to a unified dataframe...")
    transformer = CotTransformer()
    # Note: the transformer processes all active years to ensure the unified dataset is complete
    final_df = transformer.transform(years_to_process)

    # 3. Load
    if not final_df.empty:
        loader = CotLoader()
        loader.save(final_df)
        logger.info("ETL Pipeline completed successfully.")
    else:
        logger.warning("No data extracted/transformed to process.")

if __name__ == "__main__":
    run_etl_pipeline()

