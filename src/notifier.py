"""Email notifications via Gmail SMTP (stdlib smtplib — no paid email API).

Credentials come from environment variables only; never hardcode them. See README.md for
how to create a free Gmail App Password.
"""

from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from .teeitup import COURSE_TIMEZONE, TeeTime

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


@dataclass(frozen=True)
class EmailConfig:
    sender_address: str
    app_password: str
    recipient_address: str

    @classmethod
    def from_env(cls) -> "EmailConfig":
        sender = os.environ.get("GMAIL_ADDRESS")
        password = os.environ.get("GMAIL_APP_PASSWORD")
        recipient = os.environ.get("NOTIFY_EMAIL", sender)
        missing = [
            name
            for name, value in (
                ("GMAIL_ADDRESS", sender),
                ("GMAIL_APP_PASSWORD", password),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "Missing required environment variable(s) for email: " + ", ".join(missing)
            )
        return cls(sender_address=sender, app_password=password, recipient_address=recipient)

    def with_recipient(self, recipient_address: str) -> "EmailConfig":
        return EmailConfig(
            sender_address=self.sender_address,
            app_password=self.app_password,
            recipient_address=recipient_address,
        )


# Free carrier email-to-SMS gateways. No API key, no paid service — the carrier just
# delivers an email sent to this address as a text message to the phone number in the
# local part. Unofficial but widely used; delivery isn't guaranteed and can be delayed or
# occasionally filtered as spam by the carrier (see README's SMS troubleshooting section).
CARRIER_GATEWAYS = {
    "att": "txt.att.net",
    "t-mobile": "tmomail.net",
    "tmobile": "tmomail.net",
    "verizon": "vtext.com",
    "sprint": "messaging.sprintpcs.com",
    "google-fi": "msg.fi.google.com",
    "googlefi": "msg.fi.google.com",
    "us-cellular": "email.uscc.net",
    "uscellular": "email.uscc.net",
    "cricket": "sms.cricketwireless.net",
    "boost": "sms.myboostmobile.com",
    "metro": "mymetropcs.com",
    "metropcs": "mymetropcs.com",
    "visible": "vtext.com",
}


def sms_gateway_address(phone_number: str, carrier: str) -> str:
    """Build a carrier email-to-SMS gateway address like "5551234567@vtext.com"."""
    digits = "".join(ch for ch in phone_number if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]  # strip a leading US country code
    if len(digits) != 10:
        raise ValueError(f"Expected a 10-digit US phone number, got {phone_number!r}")

    key = carrier.strip().lower()
    domain = CARRIER_GATEWAYS.get(key)
    if domain is None:
        known = ", ".join(sorted(set(CARRIER_GATEWAYS.values())))
        raise ValueError(f"Unknown carrier {carrier!r}. Known gateway domains: {known}")

    return f"{digits}@{domain}"


def _format_date_long(iso_date: str) -> str:
    d = datetime.strptime(iso_date, "%Y-%m-%d")
    return f"{d.strftime('%A, %B')} {d.day}"


def _format_time_12h(hhmm: str) -> str:
    d = datetime.strptime(hhmm, "%H:%M")
    hour_12 = d.hour % 12 or 12
    return f"{hour_12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def build_email_subject(tee_time: TeeTime) -> str:
    day_abbrev = datetime.strptime(tee_time.date, "%Y-%m-%d").strftime("%a")
    return f"Dos Lagos Tee Time Available — {day_abbrev} {_format_time_12h(tee_time.time)}"


def build_email_body(tee_time: TeeTime, checked_at: datetime | None = None) -> str:
    checked_at = checked_at or datetime.now(COURSE_TIMEZONE)
    price_line = f"${tee_time.price:.0f}/player" if tee_time.price is not None else "Price unavailable"
    spots_word = "spot" if tee_time.available_spots == 1 else "spots"

    return (
        "A matching Dos Lagos tee time is available.\n\n"
        f"{_format_date_long(tee_time.date)}\n"
        f"{_format_time_12h(tee_time.time)}\n"
        f"{tee_time.available_spots} {spots_word} available\n"
        f"{price_line}\n\n"
        "BOOK:\n"
        f"{tee_time.booking_url}\n\n"
        f"Checked at: {checked_at.strftime('%Y-%m-%d %I:%M %p %Z')}\n"
    )


def send_tee_time_alert(tee_time: TeeTime, config: EmailConfig) -> None:
    send_email(
        subject=build_email_subject(tee_time),
        body=build_email_body(tee_time),
        config=config,
    )


def build_consolidated_subject(tee_times: list[TeeTime]) -> str:
    count = len(tee_times)
    noun = "tee time" if count == 1 else "tee times"
    return f"Dos Lagos: {count} matching {noun} available"


def build_consolidated_body(tee_times: list[TeeTime], checked_at: datetime | None = None) -> str:
    """List every matching tee time, numbered, for a single consolidated email.

    The number is a 1-based position in this list (sorted by date then time) — it is
    reassigned fresh on every email, not a stable ID. It exists so a future reply-to-book
    workflow can say "book #3" in a way that's unambiguous for *that* email.
    """
    checked_at = checked_at or datetime.now(COURSE_TIMEZONE)
    ordered = sorted(tee_times, key=lambda t: (t.date, t.time))

    lines = [f"{len(ordered)} matching Dos Lagos tee time(s) available.\n"]
    for i, t in enumerate(ordered, start=1):
        spots_word = "spot" if t.available_spots == 1 else "spots"
        price_str = f"${t.price:.0f}/player" if t.price is not None else "price unavailable"
        lines.append(
            f"{i}) {_format_date_long(t.date)} — {_format_time_12h(t.time)} — "
            f"{t.available_spots} {spots_word} — {price_str}\n"
            f"   BOOK: {t.booking_url}"
        )

    lines.append(f"\nChecked at: {checked_at.strftime('%Y-%m-%d %I:%M %p %Z')}")
    return "\n".join(lines) + "\n"


def send_consolidated_alert(tee_times: list[TeeTime], config: EmailConfig) -> None:
    """Send a single email listing every matching tee time, instead of one email each."""
    send_email(
        subject=build_consolidated_subject(tee_times),
        body=build_consolidated_body(tee_times),
        config=config,
    )


def sms_config_from_env(base_config: EmailConfig) -> EmailConfig | None:
    """Build an SMS-targeted EmailConfig from PHONE_NUMBER/CARRIER env vars, if both are set.

    Reuses `base_config`'s Gmail sender/app-password — sending a text is just sending an
    email to the carrier's gateway address, over the same SMTP connection. Returns None
    (not an error) if SMS isn't configured, so it stays a purely additive, optional feature.
    """
    phone_number = os.environ.get("PHONE_NUMBER")
    carrier = os.environ.get("CARRIER")
    if not phone_number or not carrier:
        return None
    gateway_address = sms_gateway_address(phone_number, carrier)
    return base_config.with_recipient(gateway_address)


def build_sms_body(tee_times: list[TeeTime]) -> str:
    """A short text-message-friendly summary — full details go in the email, not the text.

    Carrier email-to-SMS gateways will split a longer message into multiple texts rather
    than reject it, but keeping this short and scannable matters more for a text than an
    email: this is meant to be glanced at, not read in depth.
    """
    ordered = sorted(tee_times, key=lambda t: (t.date, t.time))
    count = len(ordered)
    noun = "tee time" if count == 1 else "tee times"

    if count == 1:
        t = ordered[0]
        spots_word = "spot" if t.available_spots == 1 else "spots"
        return (
            f"Dos Lagos: {_format_date_long(t.date)} {_format_time_12h(t.time)} "
            f"({t.available_spots} {spots_word}) available. {t.booking_url}"
        )

    earliest = ordered[0]
    return (
        f"Dos Lagos: {count} matching {noun} available. "
        f"Earliest: {_format_date_long(earliest.date)} {_format_time_12h(earliest.time)}. "
        "Check email for the full list."
    )


def send_sms_alert(tee_times: list[TeeTime], sms_config: EmailConfig) -> None:
    """Send the short SMS summary. Uses no subject line — most carrier gateways either drop
    it or prepend it inconsistently, so all the content lives in the body."""
    send_email(subject="", body=build_sms_body(tee_times), config=sms_config)


def send_email(subject: str, body: str, config: EmailConfig) -> None:
    message = MIMEMultipart()
    message["From"] = config.sender_address
    message["To"] = config.recipient_address
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    logger.info("Sending email %r to %s", subject, config.recipient_address)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(config.sender_address, config.app_password)
        server.sendmail(config.sender_address, [config.recipient_address], message.as_string())
    logger.info("Email sent successfully")


def send_tee_time_alerts(tee_times: list[TeeTime], config: EmailConfig) -> None:
    """Send one email per matching tee time (keeps each alert focused and skimmable)."""
    for tee_time in tee_times:
        send_tee_time_alert(tee_time, config)
