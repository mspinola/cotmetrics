"""The weekly Signal Matrix email.

Every test here runs against a stub SMTP. Nothing in this file may reach a network or
a mailbox, and a regression that made it try would show up as a test that hangs rather
than one that fails, so the stub is passed in explicitly rather than monkeypatched over
smtplib.
"""
import pandas as pd
import pytest

import cotmetrics.weekly_email as we
from cotmetrics.weekly_email import (
    WeeklyEmailNotConfigured,
    build_message,
    email_config,
    report_date_for,
    send_weekly_matrix_email,
)

ENV = {
    "EMAIL_USER": "sender@example.com",
    "RECEIVER_EMAIL_USER": "reader@example.com",
    "EMAIL_PASSWORD": "app-password",
}

MATRIX = pd.DataFrame([
    {"Date": "2026-08-11", "Asset Class": "Currencies", "Asset": "Canadian Dollar",
     "Comm Index": 100, "Lrg Index": 0, "Sml Index": 0},
    {"Date": "2026-08-11", "Asset Class": "Metals", "Asset": "Gold",
     "Comm Index": 35, "Lrg Index": 62, "Sml Index": 79},
])


class StubSMTP:
    """Records what it was asked to do and never opens a socket."""

    def __init__(self):
        self.logins, self.sent, self.quits = [], [], 0

    def login(self, user, password):
        self.logins.append((user, password))

    def sendmail(self, sender, receiver, body):
        self.sent.append((sender, receiver, body))

    def quit(self):
        self.quits += 1


# ── configuration ─────────────────────────────────────────────────────────────

def test_config_returns_the_three_values():
    assert email_config(ENV) == ("sender@example.com", "reader@example.com",
                                 "app-password")


@pytest.mark.parametrize("missing", sorted(ENV))
def test_a_missing_variable_is_named(missing):
    """The likeliest failure is a process that never carried these, so say which."""
    env = {k: v for k, v in ENV.items() if k != missing}

    with pytest.raises(WeeklyEmailNotConfigured, match=missing):
        email_config(env)


def test_an_empty_variable_counts_as_missing():
    """An exported-but-blank var is the shape a half-filled .env leaves behind."""
    with pytest.raises(WeeklyEmailNotConfigured, match="EMAIL_PASSWORD"):
        email_config({**ENV, "EMAIL_PASSWORD": ""})


def test_nothing_is_sent_when_unconfigured():
    """The check must come before the matrix is built, let alone before a connection."""
    smtp = StubSMTP()

    with pytest.raises(WeeklyEmailNotConfigured):
        send_weekly_matrix_email(env={}, smtp_factory=lambda: smtp)

    assert smtp.logins == [] and smtp.sent == []


# ── which week the email claims to be about ───────────────────────────────────

def test_the_report_date_comes_from_the_frame_not_the_clock():
    """The old script stamped datetime.now(), so a Saturday send was labelled Saturday."""
    assert report_date_for(MATRIX) == "2026-08-11"


def test_an_empty_frame_falls_back_to_today():
    """There is no week to name, and a subject line still has to say something."""
    assert report_date_for(pd.DataFrame()) != ""


def test_the_subject_names_the_report_week():
    msg = build_message(MATRIX, "2026-08-11", "s@example.com", "r@example.com")

    assert "2026-08-11" in msg["Subject"]
    assert msg["From"] == "s@example.com"
    assert msg["To"] == "r@example.com"


# ── what goes in the envelope ─────────────────────────────────────────────────

def test_the_message_carries_html_a_text_fallback_and_the_csv():
    msg = build_message(MATRIX, "2026-08-11", "s@example.com", "r@example.com")
    types = [p.get_content_type() for p in msg.walk()]

    assert "text/html" in types
    assert "text/plain" in types, "no fallback for a client that will not render HTML"
    assert any(p.get_filename() == "cot_signals_2026-08-11.csv" for p in msg.walk())


def test_the_csv_is_the_same_frame_the_table_was_built_from():
    """Otherwise the attachment and the body can disagree, which is the worst outcome:
    both look authoritative."""
    msg = build_message(MATRIX, "2026-08-11", "s@example.com", "r@example.com")
    csv = next(p for p in msg.walk() if p.get_filename())

    text = csv.get_payload(decode=True).decode()
    assert "Canadian Dollar" in text and "Gold" in text


def test_an_empty_matrix_still_sends_a_message_with_no_attachment():
    """An empty report arriving is a visible symptom. One that never arrives is not."""
    msg = build_message(pd.DataFrame(), "2026-08-11", "s@example.com", "r@example.com")

    assert [p for p in msg.walk() if p.get_filename()] == []
    assert "2026-08-11" in msg["Subject"]


# ── sending ───────────────────────────────────────────────────────────────────

def test_a_send_logs_in_mails_and_hangs_up(monkeypatch):
    smtp = StubSMTP()
    monkeypatch.setattr(we, "get_matrix_data", lambda **kw: MATRIX)

    sent_date = send_weekly_matrix_email(env=ENV, smtp_factory=lambda: smtp)

    assert sent_date == "2026-08-11"
    assert smtp.logins == [("sender@example.com", "app-password")]
    assert len(smtp.sent) == 1
    assert smtp.quits == 1, "the connection was left open"


def test_the_connection_is_closed_even_when_sending_raises(monkeypatch):
    """A failed send that leaks the socket turns one bad week into a leak per poll."""
    class Failing(StubSMTP):
        def sendmail(self, *a):
            raise OSError("connection reset")

    smtp = Failing()
    monkeypatch.setattr(we, "get_matrix_data", lambda **kw: MATRIX)

    with pytest.raises(OSError):
        send_weekly_matrix_email(env=ENV, smtp_factory=lambda: smtp)

    assert smtp.quits == 1


def test_the_default_lookback_matches_the_site(monkeypatch):
    """"Custom" is what the site shows by default. An email on a different window
    would disagree with the page it is a copy of."""
    seen = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return MATRIX

    monkeypatch.setattr(we, "get_matrix_data", spy)
    send_weekly_matrix_email(env=ENV, smtp_factory=StubSMTP)

    assert seen["lookback"] == "Custom"
