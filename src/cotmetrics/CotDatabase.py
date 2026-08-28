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

        # Visitor-tracking columns added in 0.10.0, same additive pattern as above so
        # a deployed database migrates in place on the first boot after an upgrade.
        # `kind` separates a document load ('landing', the only kind the pre-0.10.0
        # rows were, which is why NULL means landing) from a client-side navigation
        # ('pageview'): Dash is a single-page app, so only the former is an HTTP GET
        # and counting page popularity off GETs alone sees entry pages only.
        for col, col_type in [('kind', 'TEXT'), ('visitor_id', 'TEXT'),
                              ('is_bot', 'INTEGER'), ('referrer', 'TEXT')]:
            try:
                c.execute(f'ALTER TABLE visitor_logs ADD COLUMN {col} {col_type}')
            except sqlite3.OperationalError:
                pass

        # One geolocation result per IP, so the consumer asks ip-api.com about an
        # address once rather than on every request it makes. No expiry: city-level
        # IP geography moves on a timescale nobody reads these charts at.
        c.execute('''
            CREATE TABLE IF NOT EXISTS geo_cache (
                ip TEXT PRIMARY KEY,
                city TEXT,
                country TEXT,
                looked_up_at TEXT,
                hosting INTEGER
            )
        ''')

        # `hosting` came later than the table, so an existing cache needs the ALTER.
        # ip-api reports it on the free tier alongside city and country, and it is the
        # only signal that separates a datacenter client sending a browser user agent
        # from an actual browser. NULL means "cached before this column existed", which
        # the consumer treats as unknown and refetches once; a row written since is
        # always 0 or 1, never NULL, so that refetch cannot become a loop.
        try:
            c.execute('ALTER TABLE geo_cache ADD COLUMN hosting INTEGER')
        except sqlite3.OperationalError:
            pass

        c.execute('CREATE INDEX IF NOT EXISTS idx_visitor_logs_timestamp '
                  'ON visitor_logs (timestamp)')
        conn.commit()
        conn.close()

    def log_visit(self, ip, path, ua, city="Unknown", country="Unknown",
                  kind="landing", visitor_id=None, is_bot=0, referrer=None):
        """Records a new visitor event to the database.

        The first five parameters keep their pre-0.10.0 positions so an existing
        caller keeps working unchanged; the additions are keyword-friendly with
        defaults that reproduce the old row shape.
        """
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('''
            INSERT INTO visitor_logs
                (timestamp, ip_address, path, user_agent, city, country,
                 kind, visitor_id, is_bot, referrer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (now, ip, path, ua, city, country,
              kind, visitor_id, int(bool(is_bot)), referrer))
        conn.commit()
        conn.close()

    def get_cached_geo(self, ip):
        """The cached (city, country) for `ip`, or None if it has never been looked up.

        None means "no answer", never "Unknown": a lookup that failed is cached AS
        ("Lookup", "Error") by the caller if it wants that, so a None here is the one
        signal that a network lookup is still worth making.
        """
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        row = c.execute('SELECT city, country FROM geo_cache WHERE ip = ?', (ip,)).fetchone()
        conn.close()
        return (row[0], row[1]) if row else None

    def cache_geo(self, ip, city, country, hosting=None):
        """Upsert one geolocation result. Last write wins, which is fine for data
        this static.

        `hosting` is trailing and optional so a pre-0.11.0 caller keeps working; pass
        a bool to record whether the address belongs to a datacenter or proxy.
        """
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('''
            INSERT INTO geo_cache (ip, city, country, looked_up_at, hosting)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ip) DO UPDATE SET
                city = excluded.city, country = excluded.country,
                looked_up_at = excluded.looked_up_at,
                hosting = excluded.hosting
        ''', (ip, city, country, now, None if hosting is None else int(bool(hosting))))
        conn.commit()
        conn.close()

    def get_cached_hosting(self, ip):
        """Is `ip` known to be a datacenter or proxy address? True, False, or None.

        Deliberately NOT folded into `get_cached_geo`'s return: that is a two-tuple
        every caller unpacks positionally, and widening it would break them all to save
        one indexed SELECT against a local file.

        None covers both "never looked up" and "looked up before the column existed".
        Both mean the same thing to a caller (ask again), and the second case resolves
        itself on the next lookup, because `cache_geo` writes 0 or 1 rather than NULL
        for anything it has an answer for.
        """
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        row = c.execute('SELECT hosting FROM geo_cache WHERE ip = ?', (ip,)).fetchone()
        conn.close()
        if row is None or row[0] is None:
            return None
        return bool(row[0])

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


