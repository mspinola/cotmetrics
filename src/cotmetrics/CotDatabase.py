import os
import sqlite3
from datetime import datetime

import pandas as pd

import cotmetrics.constants as constants
import cotmetrics.utils as utils


class CotDatabase:
    """Class to manage COT data"""
    def __init__(self, db_name=None):
        # Default to constants.DB_PATH (COTMETRICS_DB, else the XDG data dir). The
        # old default resolved relative to __file__, which after the cotmetrics
        # split landed inside the package tree, not cot-analyzer.
        self.db_name = db_name if db_name is not None else constants.DB_PATH

        # Ensure directories exist
        os.makedirs(os.path.dirname(self.db_name), exist_ok=True)

        self.setup_database()

    def setup_database(self):
        """Create the database and the necessary table if it doesn't exist."""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()

        # Add visitor logs table
        c.execute('''
            CREATE TABLE IF NOT EXISTS visitor_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                ip_address TEXT,
                path TEXT,
                user_agent TEXT,
                city TEXT,
                country TEXT
            )
        ''')

        # Add ml_predictions_v2 table
        c.execute('''
            CREATE TABLE IF NOT EXISTS ml_predictions_v2 (
                symbol TEXT,
                report_date TEXT,
                prob_success REAL,
                meta_side INTEGER,
                expectancy REAL,
                atr_mult_tp REAL,
                atr_mult_sl REAL,
                updated_at TEXT,
                PRIMARY KEY (symbol, report_date)
            )
        ''')

        # Safely add new columns to existing table
        for col, col_type in [('expectancy', 'REAL'), ('atr_mult_tp', 'REAL'), ('atr_mult_sl', 'REAL')]:
            try:
                c.execute(f'ALTER TABLE ml_predictions_v2 ADD COLUMN {col} {col_type}')
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.close()

    def log_visit(self, ip, path, ua, city="Unknown", country="Unknown"):
        """Records a new visitor event to the database."""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('''
            INSERT INTO visitor_logs (timestamp, ip_address, path, user_agent, city, country)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (now, ip, path, ua, city, country))
        conn.commit()
        conn.close()

    def get_visitor_stats(self):
        """Retrieves recent logs for the admin dashboard."""
        conn = sqlite3.connect(self.db_name)
        df = pd.read_sql_query("SELECT * FROM visitor_logs ORDER BY id DESC LIMIT 500", conn)
        conn.close()
        return df

    def latest_update_timestamp(self):
        """The COT week the store currently holds, as ``YYYY-MM-DD``, or ``None``.

        ``None`` means NO ANSWER, never "no data". Callers must not treat it as a
        value that can differ from a previous one, which is exactly what the string
        this used to return did.

        The producer rewrites status.json atomically (tmp file + os.replace), so a
        read on the producer sees one week or the other. THAT GUARANTEE DOES NOT
        SURVIVE REPLICATION: the Mac and the VPS get the file through robocopy and
        rsync, neither of which replaces it atomically, so a consumer polling a
        replica mid-sync can read a truncated or absent file. Observed 2026-08-14
        15:35, two minutes after the 2026-08-11 week landed: json.load raised
        "Expecting value: line 1 column 1 (char 0)".

        The old return of "Unknown" turned that momentary read failure into a
        freshness signal. refresh_if_stale compares against the last known value, so
        "Unknown" != "2026-08-11" read as a new week and cost a full ~90 second index
        rebuild, then a second one when the next poll read the real date again. Three
        rebuilds for one release, and the navbar badge briefly read
        "CFTC Data Release: Unknown".
        """
        try:
            import json

            import cotdata.config as _cfg
            status_file = _cfg.store_root() / "status.json"
            if status_file.exists():
                with open(status_file, "r") as f:
                    status = json.load(f)

                # newest_data is already in YYYY-MM-DD format. Absent or null is a
                # store that has never taken a COT run, which is no answer either.
                return (status.get("domains", {})
                              .get("cot_legacy", {})
                              .get("newest_data")) or None
        except Exception as e:
            utils.get_cot_logger().error(f"Error reading status.json for timestamp: {e}")

        return None

    def save_predictions(self, symbol, report_date, prob_success, meta_side, expectancy=None, atr_mult_tp=None, atr_mult_sl=None):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('''
            INSERT INTO ml_predictions_v2 (
                symbol, report_date, prob_success, meta_side, expectancy, atr_mult_tp, atr_mult_sl, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, report_date) DO UPDATE SET
                prob_success = excluded.prob_success,
                meta_side = excluded.meta_side,
                expectancy = excluded.expectancy,
                atr_mult_tp = excluded.atr_mult_tp,
                atr_mult_sl = excluded.atr_mult_sl,
                updated_at = excluded.updated_at
        ''', (symbol, report_date, prob_success, meta_side, expectancy, atr_mult_tp, atr_mult_sl, now))
        conn.commit()
        conn.close()

    def get_latest_prediction(self, symbol):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute('''
            SELECT report_date, prob_success, meta_side, updated_at
            FROM ml_predictions_v2
            WHERE symbol = ?
            ORDER BY report_date DESC LIMIT 1
        ''', (symbol,))
        row = c.fetchone()
        conn.close()
        if row:
            return {
                "report_date": row[0],
                "prob_success": row[1],
                "meta_side": row[2],
                "updated_at": row[3]
            }
        return None

    def get_prediction(self, symbol, report_date):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute('''
            SELECT report_date, prob_success, meta_side, updated_at
            FROM ml_predictions_v2
            WHERE symbol = ? AND report_date = ?
        ''', (symbol, report_date))
        row = c.fetchone()
        conn.close()
        if row:
            return {
                "report_date": row[0],
                "prob_success": row[1],
                "meta_side": row[2],
                "updated_at": row[3]
            }
        return None

    def get_all_predictions(self, symbol):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute('''
            SELECT report_date, prob_success, meta_side, updated_at
            FROM ml_predictions_v2
            WHERE symbol = ?
            ORDER BY report_date ASC
        ''', (symbol,))
        rows = c.fetchall()
        conn.close()

        predictions = []
        for row in rows:
            predictions.append({
                "report_date": row[0],
                "prob_success": row[1],
                "meta_side": row[2],
                "updated_at": row[3]
            })
        return predictions


