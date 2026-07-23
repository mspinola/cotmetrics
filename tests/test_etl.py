from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import cotmetrics.constants as const
from cotmetrics.etl import CotExtractor, CotLoader, CotTransformer


@pytest.fixture
def mock_cot_database():
    with patch('cotmetrics.etl.CotDatabase') as mock_db:
        yield mock_db

def test_extractor_no_updates(mock_cot_database):
    """Test extractor when the database already has the latest files."""
    extractor = CotExtractor(data_dir='/tmp/cot_data', xls_data_dir='/tmp/xls_data')

    # Mocking that the file hasn't been modified since our database check
    extractor.get_last_modified = MagicMock(return_value='Tue, 15 Jun 2026 12:00:00 GMT')

    db_instance = mock_cot_database.return_value
    # Setting database date to be strictly newer than server date (to simulate no update needed)
    from datetime import datetime
    db_instance.get_zipfile_last_modified_time.return_value = datetime(2026, 6, 16)

    # We mock out the download logic to ensure it doesn't run
    extractor.download_and_extract_zip = MagicMock()

    updated_years = extractor.fetch_updates([2026])

    # It shouldn't have updated anything
    assert updated_years == []
    extractor.download_and_extract_zip.assert_not_called()


def test_extractor_with_updates(mock_cot_database):
    """Test extractor when server has newer files."""
    extractor = CotExtractor(data_dir='/tmp/cot_data', xls_data_dir='/tmp/xls_data')

    # Mocking that the file is very new on the server
    extractor.get_last_modified = MagicMock(return_value='Thu, 17 Jun 2026 12:00:00 GMT')

    db_instance = mock_cot_database.return_value
    # Database only knows about older files
    from datetime import datetime
    db_instance.get_zipfile_last_modified_time.return_value = datetime(2026, 6, 16)

    extractor.download_and_extract_zip = MagicMock()

    updated_years = extractor.fetch_updates([2026])

    # It should have triggered a download and returned the updated year
    assert updated_years == [2026]
    extractor.download_and_extract_zip.assert_called_once_with(2026)


def test_transformer_empty():
    """Test transformer handles cases with no valid files."""
    transformer = CotTransformer(xls_data_dir='/invalid/dir')
    df = transformer.transform([2026])

    assert isinstance(df, pd.DataFrame)
    assert df.empty


@patch('cotmetrics.utils.read_and_clean_xls')
@patch('os.path.exists')
def test_transformer_with_data(mock_exists, mock_read_clean):
    """Test transformer with mocked excel read logic."""
    # Ensure it thinks the excel files exist
    mock_exists.return_value = True

    # Mock utils.read_and_clean_xls to return a dummy dataframe
    dummy_data = pd.DataFrame({
        const.REPORT_DATE_XLS: ['2026-06-15', '2026-06-08'],
        const.CONTRACT_CODE_XLS: ['123456', '123456'],
        const.MARKET_NAME_XLS: ['TEST COMMODITY', 'TEST COMMODITY'],
        const.OPEN_INTEREST_XLS: [1000, 950],
        const.COMM_LONG_POS_XLS: [500, 400],
        const.COMM_SHORT_POS_XLS: [400, 300],
        const.LARGE_LONG_POS_XLS: [100, 100],
        const.LARGE_SHORT_POS_XLS: [50, 50],
        const.SMALL_LONG_POS_XLS: [50, 50],
        const.SMALL_SHORT_POS_XLS: [50, 50]
    })

    mock_read_clean.return_value = dummy_data

    transformer = CotTransformer()
    df = transformer.transform([2026])

    # Assertions
    assert not df.empty
    assert len(df) == 2
    # Verify the dates were parsed to datetime and it's sorted ascending
    assert df.iloc[0][const.REPORT_DATE_XLS] == pd.Timestamp('2026-06-08')
    assert df.iloc[1][const.REPORT_DATE_XLS] == pd.Timestamp('2026-06-15')


@patch('pandas.DataFrame.to_parquet')
def test_loader_valid(mock_to_parquet):
    """Test that the loader correctly attempts to save valid dataframes."""
    loader = CotLoader(raw_parquet_path='/tmp/dummy.parquet')

    dummy_data = pd.DataFrame({'col': [1, 2]})

    result = loader.save(dummy_data)

    assert result is True
    mock_to_parquet.assert_called_once_with('/tmp/dummy.parquet', engine='pyarrow', compression='snappy')


@patch('pandas.DataFrame.to_parquet')
def test_loader_empty(mock_to_parquet):
    """Test that the loader correctly handles empty dataframes without writing."""
    loader = CotLoader(raw_parquet_path='/tmp/dummy.parquet')

    empty_data = pd.DataFrame()

    result = loader.save(empty_data)

    assert result is False
    mock_to_parquet.assert_not_called()
