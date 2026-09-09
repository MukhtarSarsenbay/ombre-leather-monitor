# Ombré Leather price monitor

FastAPI plus a scheduled command to check Tom Ford Ombré Leather **50 ml** at
**Gold Apple only**. Notify via Telegram (default) or email when a verified
price is **strictly below 71,000 KZT**. Exactly 71,000 does not trigger an alert.

Mon Amie monitoring was turned off at the user's request on 2026-09-09. Its
optional reader remains in the code, but the deployed workflow explicitly checks
only Gold Apple. No Mac scheduler was installed.

## Current verification status

- Gold Apple: successfully read **84,150 ₸ по максимальной карте** for **50 ml**
  from the live page on 2026-09-08 using Chrome. The regular price was 93,500 ₸.
  The reader checks the selected bottle size, product heading, URL and explicitly
  labelled maximum-card price. It does not use a recommendation or generic price.
- Mon Amie: successfully read **74,800 ₸ for 50 ml** on 2026-09-08 with both
  its public storefront offer endpoint and a local browser. The preferred reader
  uses the storefront's anonymous session handshake and verifies product 74160,
  the exact 50 ml SKU 73559, and its KZT price. It requires no store login or saved
  personal profile. A browser fallback cross-checks the selected size against the
  visible current price. JSON-LD is deliberately ignored because it reports the
  old **93,500 ₸** base price. Browser checks succeeded locally but failed from
  GitHub's networks. **Cloud deployment limitation:** both the browser and API
  paths were blocked in tests on GitHub's Linux, macOS and Windows runners.
  An official free WARP proxy also failed with both the API and a headed browser.
  The local API was verified again on 2026-09-09 at **74,800 ₸ for 50 ml**.
  Mon Amie is not currently a working cloud monitor and is excluded from the
  active schedule, so it does not produce failed-check notices.
- Source and workflow are deployed to the public repository
  [MukhtarSarsenbay/ombre-leather-monitor](https://github.com/MukhtarSarsenbay/ombre-leather-monitor).
  Notification delivery is gated by the `NOTIFICATIONS_ENABLED` repository variable;
  a deployment is not notification-ready until secrets and a delivery test succeed.
  Gold Apple has been verified from GitHub at 84,150 ₸. The bot token is stored
  with its private chat ID as encrypted secrets. Telegram delivery from GitHub
  succeeded on 2026-09-08 and `NOTIFICATIONS_ENABLED=true` is configured.

## Behavior

- Default schedule: **09:00 and 19:00, Asia/Almaty**, in the GitHub workflow.
- Each store is checked independently, with one retry on reading failure.
- Each scheduled run sends an alert for every store below the threshold. A price
  that stays below the threshold can produce two alerts per store per day.
- Prices above the threshold produce no price alerts. Failed checks produce a
  separate operational notice and a nonzero exit status, so failure is visible.
- Alerts identify the store, bottle size, price type, timestamp and product link.
  Availability is not established by this monitor; verify stock and checkout price
  on the store page. No card login, coupon assumptions or purchases are involved.

## Local setup

Python 3.12+:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
cp .env.example .env
```

On Linux use `python -m playwright install --with-deps chromium` to install system
dependencies too. On macOS with Chrome installed, set `BROWSER_CHANNEL=chrome`
instead of downloading Chromium.

Mon Amie's browser fallback defaults to `MONAMIE_HEADLESS=false`. On a desktop,
a temporary browser window opens and closes automatically if the API fails.
On Linux without a desktop, install
`xvfb` and `xauth` and prefix the command with `xvfb-run -a`. The GitHub workflow
and Docker web-service command provide this virtual display on Linux. The hosted
GitHub price check uses a standard Ubuntu runner.

Read live prices without sending anything:

```sh
python -m app.check --dry-run
```

Use `--store monamie` or `--store goldapple` to check just one store. Without
this option, `CHECK_STORE` is used (default `goldapple`). The FastAPI instance also
uses `CHECK_STORE`; a successful report covers only the configured stores.

The report contains successful results and per-store errors. A partially failed
check exits with code 1 while preserving the successful store's result.

### Telegram (recommended)

1. Open [@BotFather](https://t.me/BotFather), send `/newbot`, and create your bot.
2. Put the resulting token in `.env` as `TELEGRAM_BOT_TOKEN`.
3. Open your new bot and press **Start** (or send `/start`).
4. Run `python -m app.telegram_setup`. Put the printed `TELEGRAM_CHAT_ID` in `.env`.
5. Run `python -m app.check` when you want to enable notifications for that run.

Keep tokens in `.env` or hosting secrets. `.env` is excluded from Git and Docker.
The setup helper only reads updates. A bot needs you to start the conversation
before it can deliver private alerts; see the [Telegram tutorial](https://core.telegram.org/bots/tutorial).

### Email alternative

Set `NOTIFICATION_CHANNEL=email` and the SMTP/email values in `.env.example`.
The implementation uses authenticated SMTP with STARTTLS (normally port 587).
Use the app password or SMTP credential supplied by your email provider.
The selected host must allow outbound SMTP.

## Hosting without your own server

### Recommended first option: GitHub Actions

The supplied `.github/workflows/price-check.yml` runs the same monitor twice daily.
Your laptop can be off. There is no always-online FastAPI URL in this option.

1. Put this project in a **public GitHub repository** on its default branch for
   free standard hosted runners. The current deployment uses a public repository.
2. In **Settings → Secrets and variables → Actions**, add `TELEGRAM_BOT_TOKEN`
   and `TELEGRAM_CHAT_ID` as repository secrets.
3. For email instead, set repository variable `NOTIFICATION_CHANNEL=email` and
   the SMTP/email repository secrets referenced in the workflow.
4. Open **Actions → Check perfume prices → Run workflow**, leave `dry_run` checked,
   and confirm Gold Apple succeeds from GitHub's network before relying on alerts.
5. Set repository variable `NOTIFICATIONS_ENABLED=true` once the secrets are ready,
   then run again with `dry_run` unchecked to test the enabled notification path.
   Select `test_notification` to send a clearly labelled delivery test from GitHub.
   Until this variable is enabled, all runs read prices without sending messages.
   After it is enabled, scheduled runs send applicable notifications.

Standard GitHub-hosted runners are free for public repositories, including the
Ubuntu runner used here. Credentials are encrypted repository secrets, not source
files. If you make the repository private, GitHub Free instead includes 2,000
shared monthly minutes, and usage above the allowance can be billed.
[Billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

Scheduled jobs may be delayed or dropped under heavy load. In public repositories,
schedules are disabled after 60 days without repository activity. A separate
scheduled job commits `.github/monitor-heartbeat` once per month to maintain
activity; only that job has repository write permission. This is a price watch,
not an exact-time guarantee. [Scheduling documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

### Free fallback: Mon Amie on your Mac, Gold Apple on GitHub

This is a prepared option, **not an installed local schedule**. It uses the Mac's
network, where Mon Amie's public API has worked. It cannot guarantee future access.

Generate and review the local configuration:

```sh
python scripts/prepare_macos_schedule.py
plutil -lint data/kz.ombre-leather.monamie.plist
python -m app.check --store monamie --dry-run
```

The generated plist contains no credentials. It runs this project's virtualenv,
reads the existing `.env`, checks only Mon Amie, and writes logs under `data/`.
It schedules 09:00 and 19:00 in the **Mac's system timezone**, which must be set
to Asia/Almaty. Keep the project at the same path and Chrome installed for the
browser fallback. The user must be logged in and the Mac online; sleep can delay
checks. This is a macOS user LaunchAgent, as described in
[Apple's launchd documentation](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html).

If this option is chosen, install the reviewed plist in `~/Library/LaunchAgents/`
and load it with `launchctl bootstrap` for the logged-in user's GUI domain.
The deployed GitHub workflow already checks only Gold Apple. This local option
was declined and has not been activated.

### Railway: if you want FastAPI online

Railway Hobby has a **$5/month minimum**, including $5 of usage; additional usage
costs extra. [Current pricing](https://railway.com/pricing).

Deploy this Dockerfile as a web service, set a strong `API_TOKEN` plus notification
secrets, and use an external scheduler to POST `/check` twice daily. Alternatively,
deploy only a Railway cron service with command `xvfb-run -a python -m app.check` and UTC
schedule `0 4,14 * * *` for 09:00/19:00 Almaty. Cron-only does not serve FastAPI.
Do not enable both schedulers, which would duplicate alerts.

### Render: low-cost cron alternative

Render cron jobs have a **$1/month minimum per job**, with usage-based billing.
Use this Dockerfile, override the command to `xvfb-run -a python -m app.check`, and set UTC
schedule `0 4,14 * * *`. This runs the checks without serving FastAPI.
[Render cron documentation](https://render.com/docs/cronjobs).

A sleeping free web service cannot reliably run its own in-process schedule.
This project deliberately uses an external scheduler instead.
[Render free-service limitations](https://render.com/docs/free).

## FastAPI

Set `API_TOKEN` to a long random secret, then:

```sh
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

On Linux without a desktop, prefix this with `xvfb-run -a` too. The Docker default
command already does this. The virtual display keeps the browser unattended; it
does not guarantee that a cloud IP will pass the store's security checks.

- `GET /health`: process health, public; does not claim prices were checked.
- `GET /status`: most recent report/error and whether a check is running.
- `POST /check`: check both stores and send applicable notifications.
- `POST /check?dry_run=true`: check without sending anything.

All except `/health` require `Authorization: Bearer <API_TOKEN>`. A missing server
token disables protected endpoints. Use HTTPS when hosting publicly. Concurrent
checks in a single process receive 409. Run one worker/replica; no distributed
lock is included. Results are held in memory and reset on restart; scheduled CLI
runs write JSON to their job logs. No database is required.

`/check` returns 200 when both checks succeed, or 502 with the full report on
partial/complete scrape or delivery failure. Missing notification configuration
returns 503. Serving FastAPI alone does **not** start a schedule.

## Validation

```sh
python -m pytest -q
```

Tests cover the threshold boundary, card-price parsing, wrong size/product,
Mon Amie's discount/base-price distinction and inconsistent prices, dry runs,
per-store failure isolation, delivery failure, API authentication and secret
redaction. The API tests verify exact SKU selection and the anonymous session
cookie/CSRF handshake. Notifications in tests are mocked.

After installing Playwright Chromium, run the captured-page regression test with:

```sh
RUN_BROWSER_TESTS=1 python -m pytest tests/test_monamie_browser.py -q
```

This test loads the real product fragment offline, checks the 50 ml discount price,
then simulates an inconsistent display update and verifies that it is rejected.
