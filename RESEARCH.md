# Research: Dos Lagos Golf Course on TeeItUp / GolfNow (Kenna)

Investigated 2026-10-04 by inspecting network traffic on
`https://dos-lagos-golf-course.book.teeitup.com/teetimes?course=3510` and probing the
backend API directly with `curl`. All findings below come from the public booking page —
no login, no authentication bypass, no CAPTCHA/bot-protection circumvention was performed
or is required for read-only availability checks.

## 1. How availability data is actually loaded

The booking page is a Next.js (App Router / RSC) front end. The HTML/RSC payload does
**not** contain the tee-time list. After hydration, the browser makes a plain client-side
`fetch()` to a separate backend host (GolfNow's "Kenna" platform):

```
GET https://phx-api-be-east-1b.kenna.io/v2/tee-times?date=YYYY-MM-DD&facilityIds=3510
Headers:
  Accept: application/json
  x-be-alias: dos-lagos-golf-course   (required — 400 without it: "x-be-alias is required")
```

This is a **public, unauthenticated JSON API**. Verified with plain `curl` from outside the
browser (no cookies, no session, no special TLS fingerprint) — it returns `HTTP 200` with
the full JSON body. No Cloudflare challenge, no token, no API key is required for this
specific endpoint, even though the main HTML site loads a Cloudflare
`challenge-platform` script (bot management likely guards the HTML pages / login flow, not
this JSON API).

The front end also calls:
- `GET /alias/dos-lagos-golf-course/facilities` — resolves the human alias to
  facility/course metadata.
- `GET /course/<courseId>/tee-time/locks?localDate=YYYY-MM-DD` — shopping-cart holds;
  irrelevant to read-only monitoring.
- `GET /shopping-cart/<cartId>` — session cart; irrelevant.

**Decision: use the `/v2/tee-times` endpoint directly with `requests` in Python.** No
browser automation (Selenium/Playwright) is needed for monitoring.

## 2. Identifiers

| Name | Value | Notes |
|---|---|---|
| Alias (site slug) | `dos-lagos-golf-course` | Used as `x-be-alias` header and in the booking URL host/path |
| GolfNow Facility ID | `3510` | Used as `facilityIds` query param and `course=` query param on the booking site |
| Internal Kenna course ID | `54f14c830c8ad60378b02750` | Appears in response bodies (`courseId`); not needed to make requests, only to interpret them |
| GolfCourseId (rate-level) | `98447` | Appears per-rate in `golfnow.GolfCourseId`; informational only |

These are specific to Dos Lagos and are treated as config defaults, not secrets.

## 3. Request/response details

- **Method:** `GET` only. No POST needed for availability.
- **Date format:** `YYYY-MM-DD`, local course calendar date (course is in Corona, CA —
  `America/Los_Angeles`).
- **Query params:** `date` (single day), `facilityIds` (comma-separable, we only need
  `3510`).
- **Required header:** `x-be-alias: dos-lagos-golf-course`. A normal `Accept:
  application/json` and a realistic `User-Agent` were used defensively but a bare request
  with just `x-be-alias` also returned 200 in testing.
- **Timeout/retry behavior:** not documented by the vendor; the client treats this like any
  third-party API — short timeout (10s), small number of retries with backoff, and clear
  logging on failure, assuming the endpoint can be flaky or rate-limit aggressively if
  hammered.

### Response shape (per date)

```json
[
  {
    "dayInfo": { "dawn": "...", "sunrise": "...", "sunset": "...", "dusk": "..." },
    "courseId": "54f14c830c8ad60378b02750",
    "totalAvailableTeetimes": 3,
    "teetimes": [
      {
        "courseId": "54f14c830c8ad60378b02750",
        "teetime": "2026-10-04T21:53:00.000Z",   // UTC instant; convert to America/Los_Angeles
        "backNine": false,
        "minPlayers": 1,
        "maxPlayers": 4,
        "bookedPlayers": 0,
        "players": [],
        "rates": [
          {
            "_id": 311324260,
            "externalId": "311324260",
            "name": "18 Holes",
            "allowedPlayers": [1, 2, 3, 4],
            "holes": 18,
            "greenFeeCart": 4700,       // price in CENTS ($47.00)
            "acceptCreditCard": false,
            "showAsHotDeal": false,
            "golfnow": { "TTTeeTimeId": 311324260, "GolfCourseId": 98447, "GolfFacilityId": 3510 }
          }
        ]
      }
    ]
  }
]
```

Field mapping used by the client:
- **Open spots** = `maxPlayers - bookedPlayers` for the slot (a slot can be partially
  booked by other golfers since riding times share a cart).
- **Price** = cheapest rate's `greenFeeCart / 100` (only the standard "18 Holes" public
  rate is considered; "Member", "Hot Deal", "9 Holes", "Meal Included" rate types also
  exist on this facility per the site config but aren't shown on the public booking engine
  by default for this course's main 18-hole product).
- **Unique ID for dedup** = `f"{date}:{teetime}:{rate_id}"` (the rate `_id`/`externalId`
  is the per-slot tee-sheet identifier and is stable across repeated fetches of the same
  slot).

An empty-availability date returns a 200 with `totalAvailableTeetimes: 0` and an empty (or
missing) `teetimes` array — not an error. A date fully outside the booking window also
returns 200 with zero results (confirmed up to 3 months out) rather than a 4xx — so "no
results" cannot be used to detect "window not open yet" vs. "legitimately no availability
that day"; the two look identical over the API. This matters for Phase 6 scheduling (see
below).

## 4. Booking window ("how far ahead can I book")

This was empirically tested by querying every date from 2026-10-04 through 2026-11-08 and
counting results, **and then confirmed from the site's own embedded configuration**
(the Next.js app ships a JSON blob, `beSettings.inventory`, in its page HTML):

```json
"inventory": {
  "maxDaysOut": 12,
  "reservationWindowType": "precise-time",
  "sameDayReservationWindowMinutes": 30,
  "startTimeMinutesAfterSunrise": -30,
  "endTimeMinutesBeforeSunset": -60,
  "startTimeMinutesAfterMidnight": 0,
  "endTimeMinutesAfterMidnight": 1439,
  "releaseThresholdMinutes": 0,
  "defaultStartDay": "current"
}
```

**Confirmed: `maxDaysOut = 12`.** Dates 0–12 days out (inclusive, counting "today" as day
0) return tee times; day 13+ returns zero, uniformly for every day of the week. There is
**no special separate rule for Saturdays/Sundays** — every date opens on the same rolling
12-day window. This contradicts the task's suggested default of `days_ahead: 7`, so:

> **Assumption/finding flagged explicitly:** `days_ahead` should default to **12**, not 7,
> based on direct measurement + the vendor's own config. The config is still made
> user-editable in `config.json` in case Dos Lagos changes this policy later, and the
> monitor also tolerates it being wrong (it just won't find a date until the window reaches
> it).

### What is *not* confirmed: the exact rollover time-of-day

The config's `defaultStartDay: "current"` and `startTimeMinutesAfterMidnight: 0` strongly
suggest the window advances once per day at **local midnight, `America/Los_Angeles`**
(i.e., shortly after midnight Pacific, day 13 becomes day 12 and opens for booking). This
is the standard pattern for GolfNow/TeeItUp facilities and matches `releaseThresholdMinutes:
0` (no extra delay beyond the day boundary). However, this was **not directly observed**
(it would require watching the API across an actual midnight rollover), so it's treated as
a strong assumption, not a verified fact. The monitor is built so this doesn't matter much
for correctness (it just polls and compares against stored state — if the rollover happens
at a different time, the worst case is a delayed notification, not a missed or wrong one),
but it does drive the timing of the "burst polling" GitHub Action in Phase 6. See
`README.md` for how to double check/calibrate this empirically if exact-second timing
matters to you.

## 5. Booking flow / what requires login

Clicking "Book Now" on a tee time **does not** navigate to a new URL — it expands an
in-page rate selector (URL only gains `&date=...&max=999999` query params, no per-slot
identifier). After picking a rate, the next step requires the user to be logged in — the
UI immediately shows a **"You must log in to continue"** control. The page config
confirms this (`"user": {"golfIdLogin": true, "guestCheckout": true, ...}`) — login is via
GolfNow's separate `my.golfid.io` identity service (`golfIdAuthHost`), i.e. a real GolfNow
account, not a password local to this site.

**Decision, honoring the "do not bypass auth/CAPTCHA" constraint:** this project does
**not** attempt to log in, hold a cart, or submit a booking automatically. The deep link
sent in the notification email takes the user to the pre-filtered date view on the real
booking site:

```
https://dos-lagos-golf-course.book.teeitup.com/teetimes?course=3510&date=YYYY-MM-DD&max=999999
```

There is no further per-time-slot URL parameter exposed by the front end to jump straight
to one tee time — the user picks the exact card after the page loads (there are usually
only a handful of cards on a filtered date, so this is a 1-click experience in practice).
This matches the requested Phase 7 "EMAIL → CLICK TEE TIME → OPEN CORRECT BOOKING PAGE"
design. A more automated booking flow is out of scope until/unless Dos Lagos exposes a
documented, login-free booking API — which it does not appear to.

## 6. Bot protection / politeness

- The HTML site (`*.book.teeitup.com`) loads a Cloudflare `challenge-platform` script,
  indicating Cloudflare bot management is active for at least some paths (most likely the
  login/checkout flow). The read-only JSON API (`phx-api-be-east-1b.kenna.io`) did **not**
  challenge plain `curl` requests in testing.
- `robots.txt` is not meaningfully defined (the booking site serves its SPA shell for any
  unknown path, including `/robots.txt`); the API host returns a plain 404 for it. There is
  no explicit crawl-delay or disallow directive to honor.
- Given there's no documented rate limit, the client is deliberately conservative: a
  background cadence of at most once every 15–30 minutes most of the day, with a bounded
  high-frequency burst (one GitHub Actions run, checking every 20–30 seconds for at most
  ~20 minutes) only around the suspected midnight-Pacific rollover. See `README.md` /
  `.github/workflows/monitor.yml` for exact numbers. This is well within what a human
  manually refreshing the page would generate, and far below anything that could be
  considered a denial-of-service pattern.

## 7. Recommended free architecture (summary)

- **Language/runtime:** Python 3, stdlib only for the HTTP+email core (`urllib`/`requests`
  — `requests` added as the one real dependency for a cleaner retry/timeout API), `zoneinfo`
  (stdlib, Python ≥3.9) for America/Los_Angeles conversions — no `pytz` needed.
- **Hosting:** GitHub Actions only. **Recommend making the repo public** so Actions minutes
  are unlimited/free (private repos get a limited free minutes quota/month); secrets stay
  safe either way because GitHub Secrets are never exposed in logs or to forks' pull
  requests.
- **State:** a single `state.json` file committed back to the repo by the workflow after
  each run (via the default `GITHUB_TOKEN`, no extra secret needed). Simple, free, durable,
  diffable, no database.
- **Email:** Gmail SMTP (`smtplib`, stdlib) using a free Gmail **App Password** stored as a
  GitHub Secret — no paid email API.
- **Scheduling:** two workflows — a baseline check every 30 minutes (catches
  cancellations/reopenings any time of day) and a bounded "burst" run once a day around
  the suspected release time that polls every 20–30s for ~20 minutes (catches the
  instant a new day's inventory opens). See README for exact cron lines and why GitHub
  Actions cron alone is not precise enough for second-level timing.
