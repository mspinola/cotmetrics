import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path
from datetime import datetime
import pandas as pd

# Setup paths
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from cotmetrics.reports import get_matrix_data, generate_matrix_html

def send_test_email():
    email_user = os.getenv("EMAIL_USER")
    receiver_email = os.getenv("RECEIVER_EMAIL_USER")
    email_password = os.getenv("EMAIL_PASSWORD")

    if not all([email_user, receiver_email, email_password]):
        print("Error: Missing required email environment variables (EMAIL_USER, RECEIVER_EMAIL_USER, EMAIL_PASSWORD).")
        print("Please export them or use generate-weekly-report-email.sh")
        sys.exit(1)

    print("[*] Generating Signal Matrix Data (Custom lookback)...")
    # Using Custom as the default lookback so it matches the web UI
    df = get_matrix_data(asset_classes=None, lookback="Custom")
    
    if df.empty:
        print("[!] Warning: DataFrame is empty. Ensure CotIndexer is populated.")
        
    report_date = datetime.now().strftime("%Y-%m-%d")
    print(f"[*] Generating HTML payload for {report_date}...")
    html_content = generate_matrix_html(df, report_date=report_date)

    print(f"[*] Assembling email from {email_user} to {receiver_email}...")
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"📊 COT Signal Matrix — {report_date}"
    msg["From"] = email_user
    msg["To"] = receiver_email

    # 1. Attach HTML body (nested inside an alternative part)
    alt_part = MIMEMultipart("alternative")
    alt_part.attach(MIMEText("Please enable HTML to view this email.", "plain"))
    alt_part.attach(MIMEText(html_content, "html"))
    msg.attach(alt_part)

    # 2. Attach CSV
    if not df.empty:
        csv_bytes = df.to_csv(index=False).encode('utf-8')
        part_csv = MIMEApplication(csv_bytes, Name=f"cot_signals_{report_date}.csv")
        part_csv['Content-Disposition'] = f'attachment; filename="cot_signals_{report_date}.csv"'
        msg.attach(part_csv)

    try:
        print("[*] Connecting to smtp.gmail.com:465...")
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(email_user, email_password)
        server.sendmail(email_user, receiver_email, msg.as_string())
        server.quit()
        print("[✔] Email sent successfully!")
    except Exception as e:
        print(f"[!] Failed to send email: {e}")
        sys.exit(1)

if __name__ == "__main__":
    send_test_email()
