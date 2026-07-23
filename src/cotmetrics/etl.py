import email.utils as email_utils
import os
import shutil
import zipfile

import pandas as pd
import requests

import cotmetrics.constants as const
import cotmetrics.utils as utils
from cotmetrics.CotDatabase import CotDatabase


class CotExtractor:
    """Handles checking CFTC headers, downloading ZIPs, and extracting XLS files."""
    def __init__(self, data_dir='data/cot_data', xls_data_dir='data/xls_data', url_prefix="https://www.cftc.gov/files/dea/history/dea_fut_xls_"):
        self.data_dir = data_dir
        self.xls_data_dir = xls_data_dir
        self.url_prefix = url_prefix
        self.cotDatabase = CotDatabase()

        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.xls_data_dir, exist_ok=True)

    def get_last_modified(self, year):
        """Get the last modified date for the zip file from the server."""
        url = f"{self.url_prefix}{year}.zip"
        response = requests.get(url, stream=True)
        return response.headers.get('Last-Modified')

    def download_and_extract_zip(self, year):
        url = f"{self.url_prefix}{year}.zip"
        zip_file_path = os.path.join(self.data_dir, f'dea_fut_xls_{year}.zip')

        response = requests.get(url, stream=True)
        with open(zip_file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=512):
                if chunk:
                    f.write(chunk)

        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            zip_ref.extractall(self.xls_data_dir)
            list_of_file_names = zip_ref.namelist()
            file_name = list_of_file_names[0]

            extracted_file_path = os.path.join(self.xls_data_dir, file_name)
            new_file_path = os.path.join(self.xls_data_dir, f'{year}.xls')

            if os.path.exists(new_file_path):
                try:
                    os.remove(new_file_path)
                except PermissionError as e:
                    utils.get_cot_logger().error(f"Could not delete {new_file_path}: {e}")
                    return

            try:
                shutil.move(extracted_file_path, new_file_path)
                utils.get_cot_logger().info(f"Renamed extracted file to: {new_file_path}")
            except PermissionError as e:
                utils.get_cot_logger().error(f"Error renaming file {extracted_file_path} to {new_file_path}: {e}")

    def fetch_updates(self, years):
        """Check for updates and download new zip files if available."""
        updated_years = []

        for year in years:
            last_modified_time_on_server = self.get_last_modified(year)
            if last_modified_time_on_server is None:
                utils.get_cot_logger().warning(f"Server did not return 'Last-Modified' header for {year}.zip, skipping...")
                continue
            try:
                parsed = email_utils.parsedate_to_datetime(last_modified_time_on_server)
                server_file_date = parsed.replace(tzinfo=None)
            except Exception:
                utils.get_cot_logger().error(f"Could not parse 'Last-Modified' server date for {year}.zip, skipping...")
                continue

            database_last_modified_time = self.cotDatabase.get_zipfile_last_modified_time(year)
            utils.get_cot_logger().debug(f"Checking {year}.zip - Server date: {server_file_date}, Database date: {database_last_modified_time}")

            if database_last_modified_time:
                if server_file_date > database_last_modified_time:
                    utils.get_cot_logger().info(f'Updating: {year}.zip')
                    self.download_and_extract_zip(year)
                    self.cotDatabase.update_zip_file(year, server_file_date)
                    updated_years.append(year)
                else:
                    utils.get_cot_logger().info(f'No update needed for {year}.zip')
            else:
                utils.get_cot_logger().info(f'Downloading: {year}.zip')
                self.download_and_extract_zip(year)
                self.cotDatabase.update_zip_file(year, server_file_date)
                utils.get_cot_logger().info(f"Updated database {year}.zip, with new date: {server_file_date}")
                updated_years.append(year)

        return updated_years


class CotTransformer:
    """Handles reading raw Excel files, standardizing symbols, mapping columns, and merging."""
    def __init__(self, target_columns=None, xls_data_dir='data/xls_data'):
        self.xls_data_dir = xls_data_dir
        self.target_columns = target_columns or [
            const.MARKET_NAME_XLS, const.REPORT_DATE_XLS,
            const.CONTRACT_CODE_XLS, const.OPEN_INTEREST_XLS,
            const.COMM_LONG_POS_XLS, const.COMM_SHORT_POS_XLS,
            const.LARGE_LONG_POS_XLS, const.LARGE_SHORT_POS_XLS,
            const.SMALL_LONG_POS_XLS, const.SMALL_SHORT_POS_XLS
        ]

    def transform(self, years):
        """Reads all specified years, cleans them, and returns a single concatenated DataFrame."""
        all_dfs = []
        for year in years:
            xl_path = os.path.join(self.xls_data_dir, f'{year}.xls')
            if os.path.exists(xl_path):
                utils.get_cot_logger().info(f"Parsing {year}.xls...")
                try:
                    df = utils.read_and_clean_xls(xl_path, target_columns=self.target_columns)
                    all_dfs.append(df)
                except Exception as e:
                    utils.get_cot_logger().error(f"Error reading {xl_path}: {e}")

        if not all_dfs:
            return pd.DataFrame()

        final_df = pd.concat(all_dfs, ignore_index=True)
        # Parse dates
        final_df[const.REPORT_DATE_XLS] = pd.to_datetime(final_df[const.REPORT_DATE_XLS]).dt.tz_localize(None)
        # Sort by date
        final_df = final_df.sort_values(by=const.REPORT_DATE_XLS, ascending=True).reset_index(drop=True)
        return final_df


class CotLoader:
    """Handles writing the final dataset to optimized storage formats."""
    def __init__(self, raw_parquet_path='data/raw_cot_data.parquet'):
        self.raw_parquet_path = raw_parquet_path

    def save(self, df):
        """Writes DataFrame to snappy-compressed parquet."""
        if df.empty:
            utils.get_cot_logger().warning("CotLoader received an empty DataFrame. Skipping save.")
            return False

        utils.get_cot_logger().info(f"Saving {len(df)} raw rows to {self.raw_parquet_path}...")
        df.to_parquet(self.raw_parquet_path, engine='pyarrow', compression='snappy')
        utils.get_cot_logger().info("Data successfully loaded into Parquet format.")
        return True
