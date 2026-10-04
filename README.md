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

That's it — no other secrets are needed. There are no API keys for the tee-time data
itself; that endpoint is public (see RESEARCH.md).

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
  "earliest_time": "06:00",
  "latest_time": "11:00",
  "minimum_open_spots": 2,
  "days_ahead": 12
}
```

| Field | Meaning |
|---|---|
| `alias` / `facility_id` | Identify Dos Lagos on TeeItUp. Leave these alone unless you're adapting this project for a different course. |
| `days` | Which weekdays to check — any of `Monday` … `Sunday`. |
| `earliest_time` / `latest_time` | 24-hour `HH:MM`, inclusive. Only tee times in this window match. |
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
-- Dry run: 2 newly-available matching tee time(s) --
2026-10-10 07:30  4 spot(s)  $47.00  https://dos-lagos-golf-course.book.teeitup.com/teetimes?course=3510&date=2026-10-10&max=999999
...
```

If you see `No matching tee times found.`, that's usually correct — it just means nothing
within your date/time/spots filters is open right now. Loosen `earliest_time`/`latest_time`
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

There are two kinds of scheduled runs (see `.github/workflows/monitor.yml` and
`RESEARCH.md` §7 for the full reasoning):

- **Baseline, every 30 minutes, all day.** Catches cancellations or newly-reopened spots
  within the booking window that's already open. Cheap and simple — one quick check, no
  polling loop.
- **Burst, once a day, around the suspected release time.** Dos Lagos's booking window
  appears to advance by exactly one day at local midnight (`America/Los_Angeles`) — this is
  inferred from the vendor's config, not directly observed/confirmed down to the second
  (see RESEARCH.md). GitHub Actions cron schedules run in UTC and **are not guaranteed to
  fire at the exact minute** (GitHub's own docs note scheduled runs can be delayed,
  especially under high load), so a single fixed-time trigger isn't precise enough to
  "catch it the instant it opens." Instead, the workflow starts a few minutes early and
  polls every 30 seconds for up to 20 minutes, which comfortably absorbs both GitHub's
  scheduling slop and any imprecision in the assumed midnight rollover.
- Two separate cron entries (07:40 UTC and 08:40 UTC) cover both Pacific Daylight Time and
  Pacific Standard Time, since cron doesn't shift for daylight saving. Whichever one is
  "in season" does the real polling; the other checks the local time, sees it's outside the
  expected window, and exits in a couple of seconds — so this doesn't double your Actions
  usage.

**If you want to verify the exact rollover time yourself:** run
`python -m src.monitor --date <today+13> --dry-run` every few minutes starting around
11:45 PM Pacific and watch for the moment it stops returning "No matching tee times found."
(you may need to temporarily loosen `earliest_time`/`latest_time` to see *any* result, not
just ones matching your usual preferences). If you find it's not midnight, adjust
`--window-start`/`--window-end` in `monitor.yml`'s burst steps accordingly.

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
