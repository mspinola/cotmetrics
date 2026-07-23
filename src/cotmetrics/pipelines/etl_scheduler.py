import os
import smtplib
import ssl
import sys
import time
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import schedule

import cotmetrics.config as config
import cotmetrics.utils as utils
from cotmetrics.etl import CotExtractor
from cotmetrics.indexer import get_indexer, reset_indexer


class CotJobScheduler:
    """Handles polling CFTC, running the ETL pipeline, sending emails, and triggering ML."""

    def __init__(self, enable_email=True):
        self.enable_email = enable_email
        self.extractor = CotExtractor()

    def get_years_to_process(self):
        import yaml
        # Must not be cwd-relative: this runs at app boot, before the Dash server
        # binds, so a launch from any other directory killed the app outright.
        # config.params_path() honors COTMETRICS_PARAMS and otherwise falls back to
        # the packaged copy, same as CotIndexer.
        param_dir = config.params_path()
        years = []
        with open(param_dir, 'r') as yf:
            yaml_data = yaml.safe_load(yf)
            for year in yaml_data["years"]:
                years.append(year)
        if datetime.now().year not in years:
            years.append(datetime.now().year)
        return years

    def send_email_notification(self, subject, body, html_body=None, attachment_path=None):
        """Send an email notification with optional HTML body and file attachment."""
        sender_email = os.environ.get("EMAIL_USER")
        receiver_email = os.environ.get("RECEIVER_EMAIL_USER")
        password = os.environ.get("EMAIL_PASSWORD")

        if not all([sender_email, receiver_email, password]):
            utils.get_cot_logger().warning("Email credentials missing. Skipping email.")
            return

        utils.get_cot_logger().info(f"Sending email notification to {receiver_email}")

        msg = MIMEMultipart('mixed')
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = subject

        alt = MIMEMultipart('alternative')
        alt.attach(MIMEText(body, 'plain', 'utf-8'))
        if html_body:
            alt.attach(MIMEText(html_body, 'html', 'utf-8'))
        msg.attach(alt)

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            encoders.encode_base64(part)
            filename = os.path.basename(attachment_path)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(part)

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls(context=context)
                server.login(sender_email, password)
                server.sendmail(sender_email, receiver_email, msg.as_string())
            utils.get_cot_logger().info("Email notification successfully sent.")
        except Exception as e:
            utils.get_cot_logger().error(f"Failed to send email notification: {e}")

    def run_polling_window(self, attempts=20, interval_minutes=1, force_disable_email=False):
        """Polls periodically for a set number of attempts."""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"current time: {current_time} \nStarting database update check with ({attempts} attempts, {interval_minutes}m apart)"
        utils.get_cot_logger().info(msg)

        if self.enable_email and not force_disable_email:
            self.send_email_notification("cot-analyzer DB check", msg)

        for attempt in range(1, attempts + 1):
            years_to_process = self.get_years_to_process()
            updated_years = self.extractor.fetch_updates(years_to_process)

            if updated_years:
                utils.get_cot_logger().info(f"New file detected and downloaded on attempt {attempt}! Closing polling window.")
                self.handle_updates(updated_years)
                return
            if attempt < attempts:
                time.sleep(interval_minutes * 60)

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"Polling window ended ({current_time}). No new data found."
        utils.get_cot_logger().info(msg)
        if self.enable_email and not force_disable_email:
            self.send_email_notification("cot-analyzer DB check complete", msg)

    def rebuild_indexer_cache(self):
        """Drop the indexer and rebuild it against the data the ETL just loaded.

        The rebuild has to start by discarding the existing singleton, not by reusing it.
        A CotIndexer reads the params years, the roles, the instrument list, the lookbacks
        and `last_known_db_time` once, in `__init__`. An instance built before this ETL run
        therefore describes the data as it was *before* the load, and nothing short of a
        fresh construction re-reads any of it. That matters immediately: `handle_updates`
        goes on to email a Signal Matrix built through `cotmetrics.reports`, which resolves
        the same singleton, so a stale one means mailing out pre-ETL numbers under a subject
        line announcing the new data.

        Constructing is the whole rebuild. `CotIndexer.__init__` calls `try_load_from_cache`
        and, when the freshly written raw data has invalidated it, runs exactly the
        populate / calculate / export sequence this method used to spell out inline. Doing
        it here as well only re-read every raw file a second time to reach the same verdict.
        """
        utils.get_cot_logger().info("Rebuilding calculated CotIndexer cache with new data...")
        reset_indexer()
        get_indexer()

    def handle_updates(self, updated_years):
        """Runs the rest of the pipeline when new data is found."""
        # 1. Run Transform and Load
        from cotmetrics.etl import CotLoader, CotTransformer
        try:
            utils.get_cot_logger().info("Transforming extracted files...")
            transformer = CotTransformer()
            years_to_process = self.get_years_to_process()
            df = transformer.transform(years_to_process)

            utils.get_cot_logger().info("Loading transformed data into Parquet cache...")
            loader = CotLoader()
            loader.save(df)

            self.rebuild_indexer_cache()
        except Exception as e:
            utils.get_cot_logger().error(f"Failed to transform and load COT data: {e}")
            return

        if self.enable_email:
            subject = "New COT Zip Files Downloaded"
            body = "The following years had new zip files downloaded:\n\n" + "\n".join(map(str, updated_years))
            self.send_email_notification(subject, body)

        # 2.5 Run ML Predictions via pardo_quant_framework
        try:
            import subprocess
            logger = utils.get_cot_logger()
            logger.info("Triggering ML Inference for latest data...")
            pqf_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'pardo_quant_framework'))
            predict_script = os.path.join(pqf_dir, "src", "deploy", "predict.py")
            if os.path.exists(predict_script):
                subprocess.run([sys.executable, predict_script, "--all"], check=True)
                logger.info("ML Inference completed successfully.")
            else:
                logger.error(f"predict.py not found at {predict_script}")
        except Exception as e:
            utils.get_cot_logger().error(f"Failed to run ML Inference: {e}")

        # 3. Generate and send the Signal Matrix report email
        if self.enable_email:
            try:
                utils.get_cot_logger().info("Generating Signal Matrix report for email...")
                import tempfile

                from cotmetrics.reports import generate_matrix_html, get_matrix_data

                df_report = get_matrix_data(None, "Custom")
                report_date = datetime.now().strftime("%Y-%m-%d")
                html_body = generate_matrix_html(df_report, report_date=report_date)

                csv_path = os.path.join(tempfile.gettempdir(), f"cot_matrix_{report_date}.csv")
                df_report.to_csv(csv_path, index=False)

                years_str = ", ".join(map(str, updated_years))
                subject = f"📊 COT Signal Matrix — {report_date} (Updated: {years_str})"
                plain_body = (
                    f"New CFTC COT data was downloaded for: {years_str}.\n\n"
                    f"The full Signal Matrix is shown below and attached as a CSV.\n\n"
                    f"View the live matrix at your cot-analyzer dashboard."
                )

                self.send_email_notification(
                    subject,
                    plain_body,
                    html_body=html_body,
                    attachment_path=csv_path
                )
                utils.get_cot_logger().info("Signal Matrix report email sent successfully.")
            except Exception as e:
                utils.get_cot_logger().error(f"Failed to generate/send Signal Matrix report: {e}")

    def start_scheduler(self):
        """Schedule the polling window for every weekday at 15:25 Local Time."""
        database_release_time = "15:25"
        tz = "America/New_York"

        # We define a helper so we don't bind self.run_polling_window directly without kwargs support in schedule natively easily
        def poll_10_2(): self.run_polling_window(attempts=10, interval_minutes=2)
        def poll_20_1(): self.run_polling_window(attempts=20, interval_minutes=1)
        def poll_1_1(): self.run_polling_window(attempts=1, interval_minutes=1)

        schedule.every().monday.at(database_release_time, tz).do(poll_10_2)
        schedule.every().tuesday.at(database_release_time, tz).do(poll_10_2)
        schedule.every().wednesday.at(database_release_time, tz).do(poll_10_2)
        schedule.every().thursday.at(database_release_time, tz).do(poll_10_2)
        schedule.every().friday.at(database_release_time, tz).do(poll_20_1)
        utils.get_cot_logger().info(f"Smart scheduler active: Polling weekdays at {database_release_time} {tz}.")

        morning_time = "08:00"
        schedule.every().monday.at(morning_time, tz).do(poll_1_1)
        schedule.every().tuesday.at(morning_time, tz).do(poll_1_1)
        schedule.every().wednesday.at(morning_time, tz).do(poll_1_1)
        schedule.every().thursday.at(morning_time, tz).do(poll_1_1)
        schedule.every().friday.at(morning_time, tz).do(poll_1_1)
        utils.get_cot_logger().info(f"Daily scheduler active: Running every morning at {morning_time} {tz}.")

        while True:
            schedule.run_pending()
            time.sleep(30)

if __name__ == "__main__":
    scheduler = CotJobScheduler(enable_email=True)
    scheduler.start_scheduler()
