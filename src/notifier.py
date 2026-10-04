"""Email notifications via Gmail SMTP (stdlib smtplib — no paid email API).

Credentials come from environment variables only; never hardcode them. See README.md for
how to create a free Gmail App Password.
"""

from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass, replace
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import requests

from .teeitup import COURSE_TIMEZONE, TeeTime

logger = logging.getLogger(__name__)

URL_SHORTENER_TIMEOUT_SECONDS = 5

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


DEFAULT_NTFY_SERVER = "https://ntfy.sh"
NTFY_TIMEOUT_SECONDS = 10


def ntfy_topic_from_env() -> str | None:
    """The ntfy.sh topic name to publish to, or None if push alerts aren't configured.

    ntfy's free public server has no access control beyond obscurity: anyone who knows (or
    guesses) the topic name can read or publish to it. Treat NTFY_TOPIC as a secret — a long,
    random string, stored only as a GitHub Secret, never committed to config.json.
    """
    return os.environ.get("NTFY_TOPIC") or None


def ntfy_server_from_env() -> str:
    return os.environ.get("NTFY_SERVER") or DEFAULT_NTFY_SERVER


def send_ntfy_alert(tee_times: list[TeeTime], topic: str, server: str = DEFAULT_NTFY_SERVER) -> None:
    """Push a notification via ntfy.sh listing every matching tee time with full links.

    Unlike carrier SMS gateways, ntfy has no link-content spam filtering and no sender
    rate-limiting we've hit — so this reuses the same full-detail body as the email (no need
    for URL shortening or hour-grouping tricks) and sets a tap-to-open link to the earliest
    match.
    """
    ordered = sorted(tee_times, key=lambda t: (t.date, t.time))
    title = build_consolidated_subject(ordered)
    body = build_consolidated_body(ordered)

    headers = {"Title": title}
    if ordered:
        headers["Click"] = ordered[0].booking_url

    url = f"{server.rstrip('/')}/{topic}"
    logger.info("Sending ntfy.sh push notification to topic (hidden) via %s", server)
    response = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=NTFY_TIMEOUT_SECONDS)
    response.raise_for_status()
    logger.info("ntfy.sh notification sent successfully")


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


def _format_date_short(iso_date: str) -> str:
    d = datetime.strptime(iso_date, "%Y-%m-%d")
    return f"{d.strftime('%a')} {d.month}/{d.day}"


def build_sms_body(tee_times: list[TeeTime]) -> str:
    """A text-message summary that always includes the booking link(s).

    Tee times are grouped by (date, booking_url) — since a link already brackets a whole
    hour (see teeitup.booking_url_for_slot), multiple matching times in the same hour share
    one link, so it's listed once per group rather than repeated per time. Carrier
    email-to-SMS gateways split a longer message into multiple texts rather than reject it,
    so there's no hard length cap to engineer around here.
    """
    ordered = sorted(tee_times, key=lambda t: (t.date, t.time))
    count = len(ordered)
    noun = "tee time" if count == 1 else "tee times"

    groups: dict[tuple[str, str], list[str]] = {}
    group_order: list[tuple[str, str]] = []
    for t in ordered:
        key = (t.date, t.booking_url)
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(_format_time_12h(t.time))

    lines = [f"Dos Lagos: {count} matching {noun} available."]
    for date_str, url in group_order:
        times_str = ", ".join(groups[(date_str, url)])
        lines.append(f"{_format_date_short(date_str)} {times_str}: {url}")

    return "\n".join(lines)


def shorten_url(url: str) -> str:
    """Shorten `url` via TinyURL's free, keyless API. Falls back to the original URL on any
    failure (network error, timeout, unexpected response) — a long link is a readability
    annoyance, not a reason to fail the whole alert.

    Tried is.gd/v.gd first during development — both flatly reject every URL on the
    teeitup.com domain with "Error, database insert failed" (confirmed against several
    different URLs and query strings, so it's a domain-level block on their end, not
    something fixable by retrying or tweaking the request). TinyURL shortens them fine and
    was verified to redirect back to the exact original URL.
    """
    try:
        response = requests.get(
            "https://tinyurl.com/api-create.php",
            params={"url": url},
            timeout=URL_SHORTENER_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        short_url = response.text.strip()
        if short_url.startswith("http"):
            return short_url
        logger.warning("URL shortener returned an unexpected response for %s: %s", url, short_url)
    except requests.RequestException:
        logger.warning("Failed to shorten URL %s; sending the full-length URL instead", url)
    return url


def _with_shortened_urls(tee_times: list[TeeTime]) -> list[TeeTime]:
    """Replace each tee time's booking_url with a shortened one, reusing one lookup per
    distinct URL (times grouped into the same hour already share a URL — no need to shorten
    it more than once)."""
    cache: dict[str, str] = {}
    shortened = []
    for t in tee_times:
        if t.booking_url not in cache:
            cache[t.booking_url] = shorten_url(t.booking_url)
        shortened.append(replace(t, booking_url=cache[t.booking_url]))
    return shortened


def send_sms_diagnostic(sms_config: EmailConfig) -> None:
    """Send three separate test texts to isolate why a text might not be arriving.

    Carrier email-to-SMS gateways and spam filters are a black box from the sending side —
    the SMTP server accepting a message (what `send_email` logs as "sent successfully")
    only means Gmail accepted it, not that the carrier delivered it to the handset. Sending
    a plain-text message, one with a full teeitup.com link, and one with a shortened link,
    as three separate texts, lets you tell the sending/receiving team concretely which ones
    an actual spam filter ate.
    """
    real_link = "https://dos-lagos-golf-course.book.teeitup.com/teetimes?course=3510"
    short_link = shorten_url(real_link)

    tests = [
        "Dos Lagos SMS test 1/3: plain text, no link.",
        f"Dos Lagos SMS test 2/3: full link. {real_link}",
        f"Dos Lagos SMS test 3/3: shortened link. {short_link}",
    ]
    for text in tests:
        send_email(subject="", body=text, config=sms_config)


def send_sms_alert(tee_times: list[TeeTime], sms_config: EmailConfig) -> None:
    """Send the SMS summary, with booking URLs shortened for readability on a phone screen.

    Uses no subject line — most carrier gateways either drop it or prepend it
    inconsistently, so all the content lives in the body.
    """
    shortened = _with_shortened_urls(tee_times)
    send_email(subject="", body=build_sms_body(shortened), config=sms_config)


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
