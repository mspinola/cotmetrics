"""Send the weekly Signal Matrix email from the command line.

A thin CLI. The building and sending live in `cotmetrics.weekly_email`, because this
is no longer the only caller: cot-analyzer's Admin button shells out to this file, and
its store poller sends in-process when the COT week advances. Keeping the logic here
would have forked the subject line and the attachment three ways.

Configuration is the environment (EMAIL_USER, RECEIVER_EMAIL_USER, EMAIL_PASSWORD).
This file loads no .env of its own: the process that invokes it decides what it can
send as, which is what lets the same script be safe in a crontab, under systemd, and
behind an Admin button.
"""
import argparse
import sys
from pathlib import Path

# Support running straight from a checkout (python scripts/...), where cotmetrics may
# not be installed. Harmless when it is.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from cotmetrics.weekly_email import (  # noqa: E402
    WeeklyEmailNotConfigured,
    send_weekly_matrix_email,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Send the weekly Signal Matrix email.")
    parser.add_argument(
        "--lookback", default="Custom",
        help="index lookback window, matching the site's selector (default: Custom)")
    parser.add_argument(
        "--report-date", default=None,
        help="override the COT week in the subject line. Defaults to the week the "
             "matrix itself carries, which is almost always what you want")
    args = parser.parse_args(argv)

    print("[*] Building the Signal Matrix...")
    try:
        report_date = send_weekly_matrix_email(report_date=args.report_date,
                                               lookback=args.lookback)
    except WeeklyEmailNotConfigured as e:
        print(f"[!] Not configured: {e}")
        return 1
    except Exception as e:
        print(f"[!] Failed to send email: {e}")
        return 1

    print(f"[*] Email sent for the {report_date} report.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
