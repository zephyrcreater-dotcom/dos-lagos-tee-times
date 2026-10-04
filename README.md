# Dos Lagos Tee Time Monitor

Watches Dos Lagos Golf Course's online booking system (TeeItUp/GolfNow) for tee times
matching your preferences — by default, Saturday/Sunday mornings with enough open spots —
and emails you the instant one appears. Runs entirely on GitHub Actions' free tier; costs
$0/month.

**Read [RESEARCH.md](RESEARCH.md) first** if you want to understand *how* this works (the
API it calls, the confirmed 12-day booking window, why there's no database, etc.) This
README is just the "how do I set it up" guide.

---

## 1. Create the GitHub repository

1. Go to [github.com/new](https://github.com/new).
2. Name it something like `dos-lagos-tee-times`.
3. Set visibility to **Public**. This matters: public repositories get **unlimited free**
   GitHub Actions minutes, while private repos only get ~2,000 minutes/month free. Your
   code has no secrets in it (see step 2), so there's nothing sensitive to hide by making
   it public.
4. Don't initialize it with a README (you already have one here).
5. On your computer, in this project folder, run:

```bash
git init
git add .
git commit -m "Initial commit: Dos Lagos tee time monitor"
git branch -M main
git remote add origin https://github.com/<your-username>/dos-lagos-tee-times.git
git push -u origin main
```

(Replace `<your-username>` with your actual GitHub username.)

---

## 2. Get a Gmail App Password (free email, no API keys)

This project emails you using your own Gmail account over SMTP — no SendGrid, no Mailgun,
no paid email API. You need a 16-character **App Password** (not your normal Gmail
password):

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security).
2. Turn on **2-Step Verification** if it isn't already on (App Passwords require it).
3. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
4. Under "App name", type something like `dos-lagos-monitor` and click **Create**.
5. Google shows you a 16-character password (like `abcd efgh ijkl mnop`). Copy it —
   you won't be able to see it again. You'll paste it into GitHub Secrets in the next step.

You can send the alert to the same Gmail address, or to a different address entirely (e.g.
your regular inbox) — that's the `NOTIFY_EMAIL` secret below.

---

## 3. Add GitHub Secrets

Secrets are encrypted values GitHub injects as environment variables during the workflow
run — they're never visible in logs or in the code. **Never put real credentials directly
in `config.json` or any file you commit.**

1. On your repo's GitHub page, click **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret** for each of these:

| Secret name | Value |
|---|---|
| `GMAIL_ADDRESS` | The Gmail address you created the App Password for (e.g. `you@gmail.com`) |
| `GMAIL_APP_PASSWORD` | The 16-character App Password from step 2 (spaces are fine either way) |
| `NOTIFY_EMAIL` | The email address that should **receive** alerts (can be the same as `GMAIL_ADDRESS`) |
| `NTFY_TOPIC` *(optional)* | A long, random topic name for free push notifications (see below) |

`NTFY_TOPIC` is optional — without it, you just get email. With it set, every alert also
pushes instantly to your phone via [ntfy](https://ntfy.sh), a free, open-source push
notification service — no account, no paid tier, no app-store sign-up.

**Setting up ntfy push alerts:**

1. Install the **ntfy** app ([iOS](https://apps.apple.com/us/app/ntfy/id1625396347) /
   [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)).
2. Pick a topic name that's **long and hard to guess** — ntfy's free public server has no
   login or access control, so anyone who knows your exact topic name could read your alerts
   or post fake ones to it. Something like `dos-lagos-<random-words-or-numbers-only-you-know>`
   is enough; don't use a short/obvious name like `dos-lagos-alerts`.
3. In the app, tap **+** and subscribe to that exact topic name on the default server
   (`ntfy.sh`).
4. Add it as the `NTFY_TOPIC` GitHub Secret (step 3 above).

That's it — no other secrets are needed. There are no API keys for the tee-time data
itself; that endpoint is public (see RESEARCH.md).

**Why not carrier SMS (email-to-text gateways)?** This project tried that first — it's also
free, but turned out to be unreliable in two separate ways found during testing: T-Mobile's
`tmomail.net` gateway silently drops any text containing a link at all (confirmed via a
direct A/B test — a link-free text arrived, the same message with a link didn't), and
sending more than a handful of test messages in a short window got the destination address
rate-limited/blocked outright. ntfy has shown neither problem. The carrier-SMS code path is
still in the codebase (`sms_gateway_address`, `send_sms_alert` in `src/notifier.py`) in case
you want to experiment with a different carrier, but it's not part of the recommended setup.

---

## 4. Configure your tee-time preferences

```bash
cp config.example.json config.json
```

Edit `config.json`:

```json
{
  "alias": "dos-lagos-golf-course",
  "facility_id": "3510",
  "days": ["Saturday", "Sunday"],
  "earliest_time": "00:00",
  "latest_time": "08:59",
  "minimum_open_spots": 1,
  "days_ahead": 12
}
```

| Field | Meaning |
|---|---|
| `alias` / `facility_id` | Identify Dos Lagos on TeeItUp. Leave these alone unless you're adapting this project for a different course. |
| `days` | Which weekdays to check — any of `Monday` … `Sunday`. |
| `earliest_time` / `latest_time` | 24-hour `HH:MM`, inclusive. Only tee times in this window match. The default (`00:00`–`08:59`) means "before 9:00 AM". |
| `minimum_open_spots` | Minimum open spots in the group for a tee time to count as a match. |
| `days_ahead` | How many days out to look, inclusive of today. **Leave this at 12** — that's Dos Lagos's actual, confirmed booking window (see RESEARCH.md). Raising it just means extra API calls for dates that will always come back empty. |

`config.json` has **no secrets in it** — it's meant to be committed to your repo so the
GitHub Action can read it:

```bash
git add config.json
git commit -m "Add my tee time preferences"
git push
```

---

## 5. Test the scraper locally

Make sure you have Python 3.11+ and the one dependency installed:

```bash
pip install -r requirements.txt
```

Dry-run against your configured days (no email sent, no state saved):

```bash
python -m src.monitor --dry-run
```

Check one specific date instead (useful for testing, or checking a date outside your
normal `days` filter):

```bash
python -m src.monitor --date 2026-10-10 --dry-run
```

You should see output like:

```
-- 2 of 2 matching tee time(s) are new since last run --

-- Email that would be sent (consolidated, numbered list) --
2 matching Dos Lagos tee time(s) available.

1) Saturday, October 10 — 7:30 AM — 4 spots — $47/player
   BOOK: https://dos-lagos-golf-course.book.teeitup.com/teetimes?course=3510&date=2026-10-10&max=999999
2) Sunday, October 11 — 8:15 AM — 3 spots — $47/player
   BOOK: https://dos-lagos-golf-course.book.teeitup.com/teetimes?course=3510&date=2026-10-11&max=999999

Checked at: 2026-10-04 07:48 AM PDT
```

This is exactly the body of the single email you'd get for a real run — every matching
tee time is numbered and listed together, not sent as separate emails.

If you see `No matching tee times found.`, that's usually correct — it just means nothing
within your date/time/spots filters is open right now (very common for the "before 9:00 AM"
default, since early slots tend to get booked first). Loosen `earliest_time`/`latest_time`
temporarily to double check real tee times are coming back at all.

---

## 6. Test email notifications

Set the same three values as environment variables locally (don't commit these anywhere):

```bash
export GMAIL_ADDRESS="you@gmail.com"
export GMAIL_APP_PASSWORD="abcdefghijklmnop"
export NOTIFY_EMAIL="you@gmail.com"
```

Then run a real (non-dry-run) check against a date you know has matching availability —
temporarily widen your filters in `config.json` if needed so something actually matches:

```bash
python -m src.monitor --date 2026-10-10
```

If a match is found, you should get an email within a few seconds, and `state.json` will
be created/updated locally. Run the exact same command again — you should **not** get a
second email for the same tee time, since it's already in `state.json` (that's the
duplicate-prevention working as intended). Delete `state.json` if you want to force it to
treat everything as new again.

---

## 7. Manually trigger the GitHub Action

You don't have to wait for the schedule to test the deployed version:

1. Go to your repo on GitHub → **Actions** tab.
2. Click **Dos Lagos Tee Time Monitor** in the left sidebar.
3. Click **Run workflow** (top right).
4. Optionally check "Dry run" to avoid sending email, then click the green **Run workflow**
   button.
5. Click into the run to watch the logs live.

---

## 8. How the automatic schedule works

The workflow runs **every 5 minutes, all day** (`cron: "*/5 * * * *"` in
`.github/workflows/monitor.yml`) — every run does one fetch-filter-check cycle and exits in
a few seconds. Five minutes is also the shortest interval GitHub Actions cron supports.

Two things to know about precision:

- **GitHub's own docs say scheduled runs aren't guaranteed to fire exactly on time** — they
  can be delayed by a few minutes, and under high GitHub-wide load some scheduled runs can
  be skipped entirely. In practice "every 5 minutes" means "checked very recently," not a
  guaranteed tick. This is fine for cancellations/reopenings throughout the day; the one
  case it isn't perfectly tight for is the exact instant the booking window advances to a
  new day (believed to be local midnight at the course — see RESEARCH.md; this was inferred
  from the vendor's config, not directly observed down to the second). Worst case you find
  out a few minutes later than the literal first second it opened, which checking every 5–10
  minutes already gets you most of the way to "almost immediately."
- If you want tighter precision specifically around that midnight rollover, the CLI has a
  `--burst` mode built in (`python -m src.monitor --burst --burst-minutes 20
  --poll-interval 30`) that polls every 30 seconds for a bounded window — it's just not
  wired into the default schedule right now since you asked for a simple fixed interval.
  You can add it back as an extra scheduled step if you want both.

**If you want to verify the exact rollover time yourself:** run
`python -m src.monitor --date <today+13> --dry-run` every few minutes starting around
11:45 PM Pacific and watch for the moment it stops returning "No matching tee times found."
(you may need to temporarily loosen `earliest_time`/`latest_time` to see *any* result, not
just ones matching your usual preferences).

### One consolidated email, not one per tee time

Every matching tee time across all your configured dates is combined into a **single**
numbered email (see `src/notifier.py`'s `build_consolidated_body`), not one email per slot.
An email is only sent when at least one tee time is *new* since the last check (so you
don't get re-notified every 5 minutes about something already open), but when it fires, the
email lists **every** currently-matching tee time, numbered 1, 2, 3… This numbering is
intentionally the groundwork for a future "reply with a number to book it" flow — it isn't
wired up yet (see "What this project deliberately does not do" below for why that's a
bigger, more careful step), but the list format is ready for it.

---

## 9. Troubleshooting failures

- **Actions tab shows a red ✗:** click into the run, then the `monitor` job, to see which
  step failed and the error message.
- **"Missing required environment variable(s) for email"**: one of `GMAIL_ADDRESS` /
  `GMAIL_APP_PASSWORD` isn't set as a repo secret, or is misspelled. Re-check step 3.
- **SMTP authentication error:** almost always means the App Password is wrong, has a typo,
  or 2-Step Verification got turned off (which invalidates App Passwords). Generate a new
  one and update the `GMAIL_APP_PASSWORD` secret.
- **No emails ever arrive, but dry-run shows matches:** confirm you're not still passing
  `--dry-run` somewhere, and check your spam folder once — Gmail-to-Gmail rarely gets
  flagged, but it can happen on the very first send.
- **Getting emailed repeatedly for the same tee time:** means `state.json` isn't being
  committed back successfully. Check the "Commit updated state" step's logs — a common
  cause is branch protection rules on `main` blocking the bot's push; either relax
  protection for the `github-actions[bot]` actor or push to a different branch and adjust
  the workflow's checkout ref.
- **Fetching tee times fails with a non-200 status or unexpected JSON:** Dos Lagos / TeeItUp
  changed something. Re-run the Phase 1 recon in RESEARCH.md against the live site to see
  what changed (open browser devtools → Network tab → reload the tee times page → look for
  the `kenna.io/v2/tee-times` request).
- **Actions aren't running on schedule at all:** GitHub automatically disables scheduled
  workflows on repos with **no activity for 60 days**. Push *any* commit (even just editing
  `config.json`) to re-enable it, or just keep an eye on it periodically.

---

## 10. Changing your preferences later

Just edit `config.json` and push:

```bash
# e.g. widen the time window and lower the minimum spots needed
python3 - <<'PY'
import json
cfg = json.load(open("config.json"))
cfg["earliest_time"] = "06:00"
cfg["latest_time"] = "13:00"
cfg["minimum_open_spots"] = 1
json.dump(cfg, open("config.json", "w"), indent=2)
PY
git add config.json
git commit -m "Widen tee time preferences"
git push
```

(Or just open `config.json` in any text editor — it's plain JSON.) The next scheduled run
picks up the new preferences automatically; no redeploy step needed.

---

## What this project deliberately does **not** do

- It does not log in, hold a cart, or submit a booking on your behalf. Dos Lagos requires a
  real GolfNow/GolfID account login to book, and this project does not automate
  authentication, enter your password anywhere, or attempt to bypass that.
- It does not solve or bypass any CAPTCHA, Cloudflare challenge, or other bot-protection —
  the read-only availability endpoint it uses did not require any of that in testing, and
  if that ever changes, the right fix is to stop (not to add a bypass).
- The email gives you a direct, pre-filtered link to the real booking page for the matching
  date so you can log in and book it yourself in one click — see RESEARCH.md §5 for why a
  fully automated "click one button, get a tee time" flow isn't possible here without
  crossing that line.
