"""Send the weekly Signal Matrix as an email.

The sending used to live inside `scripts/generate-weekly-report-email.py`, which made
it reachable only by running that file. It now has three callers with three different
reasons to fire (the script, cot-analyzer's Admin button, and cot-analyzer's store
poller), so it lives here and the script is a thin CLI over it. One implementation, one
place where the subject line and the attachment are decided.

Configuration is the environment, and it is required rather than defaulted:

    EMAIL_USER            the sending account
    RECEIVER_EMAIL_USER   where the report goes
    EMAIL_PASSWORD        an app password, not the account password

Missing any of them raises `WeeklyEmailNotConfigured`. That is deliberately an
exception and not a warning-and-return: every caller wants to say something different
about it (the script exits 1, the Admin page prints it, the poller logs and carries
on), and a function that quietly does nothing gives none of them the chance.
"""
import os
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import cotmetrics.utils as utils
from cotmetrics.reports import generate_matrix_html, get_matrix_data

#: Gmail's implicit-TLS endpoint. Module constants rather than literals so a test can
#: point at a stub without monkeypatching smtplib itself.
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

REQUIRED_ENV = ("EMAIL_USER", "RECEIVER_EMAIL_USER", "EMAIL_PASSWORD")


class WeeklyEmailNotConfigured(RuntimeError):
    """The three EMAIL_* variables are not all set."""


def email_config(env=None):
    """`(sender, receiver, password)`, or raise naming exactly what is missing.

    Naming them matters more than it looks. The single most likely failure here is a
    job that runs in an environment the operator believed carried these, and "email is
    not configured" sends them looking at the wrong three things.
    """
    env = os.environ if env is None else env
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise WeeklyEmailNotConfigured(
            f"missing {', '.join(missing)}. The weekly Signal Matrix email needs all "
            f"of {', '.join(REQUIRED_ENV)} in the environment of the process that "
            f"sends it.")
    return tuple(env[name] for name in REQUIRED_ENV)


def report_date_for(df):
    """The COT week the matrix actually describes.

    Read off the frame rather than the clock. The old script stamped
    `datetime.now()`, so a send that ran on Saturday, or a resend of last week, was
    labelled with the day it was sent. The frame carries the report date because
    get_matrix_data pins every row to one, which is the same value the heatmap page
    puts in its own header.

    Falls back to today only for an empty frame, where there is no week to name.
    """
    if df.empty or "Date" not in df.columns:
        return datetime.now().strftime("%Y-%m-%d")
    return str(df.iloc[0]["Date"])


def build_message(df, report_date, sender, receiver):
    """Assemble the multipart message: HTML body, plain-text fallback, CSV attachment.

    Split from the sending so the interesting half can be tested without a network or
    a mailbox. Everything a reader would check (does the subject name the report week,
    is the table the same one the site renders, is the CSV the same frame) is decided
    here.
    """
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"📊 COT Signal Matrix — {report_date}"
    msg["From"] = sender
    msg["To"] = receiver

    alt_part = MIMEMultipart("alternative")
    alt_part.attach(MIMEText("Please enable HTML to view this email.", "plain"))
    alt_part.attach(MIMEText(generate_matrix_html(df, report_date=report_date), "html"))
    msg.attach(alt_part)

    if not df.empty:
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        part_csv = MIMEApplication(csv_bytes, Name=f"cot_signals_{report_date}.csv")
        part_csv["Content-Disposition"] = (
            f'attachment; filename="cot_signals_{report_date}.csv"')
        msg.attach(part_csv)

    return msg


def send_weekly_matrix_email(report_date=None, lookback="Custom", asset_classes=None,
                             env=None, smtp_factory=None):
    """Build the Signal Matrix and mail it. Returns the report date that was sent.

    `lookback` defaults to "Custom" so the email matches what the site shows by
    default rather than a window chosen only here.

    The universe comes from whatever COTMETRICS_PARAMS the calling process resolved,
    which is the strongest argument for sending in-process from the app: unset, that
    silently means the 6-symbol SAMPLE, and an email covering six markets looks
    exactly like an email covering forty-seven.
    """
    sender, receiver, password = email_config(env)

    df = get_matrix_data(asset_classes=asset_classes, lookback=lookback)
    if df.empty:
        utils.get_cot_logger().warning(
            "weekly email: the Signal Matrix is empty. Sending anyway, because a "
            "report that arrives empty is a visible symptom and one that never "
            "arrives is not.")

    report_date = report_date or report_date_for(df)
    msg = build_message(df, report_date, sender, receiver)

    factory = smtp_factory or (lambda: smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT))
    server = factory()
    try:
        server.login(sender, password)
        server.sendmail(sender, receiver, msg.as_string())
    finally:
        server.quit()

    utils.get_cot_logger().info(
        f"weekly email: sent the {report_date} Signal Matrix ({len(df)} rows) to "
        f"{receiver}.")
    return report_date
