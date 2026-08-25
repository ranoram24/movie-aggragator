# Deploying to Fly.io

One deploy, one URL. FastAPI serves both the API and the built React app, so
there is no CORS and no second host to keep in sync. Fly terminates HTTPS for
you, which the app **requires** — browsers block the geolocation API on plain
`http://`, so over http your phone would silently get no location.

---

## One-time setup

**1. Install flyctl**

```powershell
powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"
```

Restart the terminal afterwards so `fly` is on your PATH.

**2. Sign in** (creates the account if you don't have one; a card is required
even on small usage)

```bash
fly auth signup
```

**3. Pick an app name.** `fly.toml` says `app = "on-cinema"`, and names are
global across all of Fly, so that one is very likely taken. Edit `fly.toml` and
change it to something unique — e.g. `on-cinema-ran`. Your URL becomes
`https://<that-name>.fly.dev`.

**4. Create the app and its volume.** The volume is what makes the database
survive: without it, SQLite lives inside the container and resets to empty on
every deploy.

```bash
fly apps create on-cinema-ran
```

```bash
fly volumes create oncinema_data --size 1 --region cdg --app on-cinema-ran
```

Keep the volume's region the same as `primary_region` in `fly.toml` (`cdg`,
Paris — the closest Fly region to Israel). A volume in a different region than
the machine simply won't mount.

**5. Set the TMDb token as a secret.** It is read from the environment and is
never in the repo, so it has to be supplied here or movie matching silently
does nothing.

```bash
fly secrets set TMDB_TOKEN="your-tmdb-token" --app on-cinema-ran
```

---

## Deploy

```bash
fly deploy
```

Then open it:

```bash
fly open
```

That URL works on your phone as-is — no VPN, no same-network requirement.

---

## What happens on first boot

The volume starts empty, so:

1. Tables are created automatically at startup.
2. The scraper begins immediately, one chain at a time, staggered.
3. **Cinema City, Movieland, Planet and Hot Cinema populate within ~2 minutes.**
4. **Lev takes ~15 minutes** — it has no JSON API and needs a cascading
   sequence of about 800 requests.

The app is usable as soon as the first chain finishes. Watch it happen:

```bash
fly logs --app on-cinema-ran
```

Or check from the browser: `https://<your-app>.fly.dev/scrape/status`

---

## After it's running

Scraping continues on its own — the fast four every 6 hours, Lev once a day.
`auto_stop_machines = false` in `fly.toml` is what keeps that true; if the
machine were allowed to suspend when idle, scraping would stop and showtimes
would go stale, which defeats the point.

Useful commands:

```bash
fly logs --app on-cinema-ran
```

```bash
fly ssh console --app on-cinema-ran
```

```bash
fly status --app on-cinema-ran
```

Force a chain to re-scrape now:

```bash
curl -X POST https://on-cinema-ran.fly.dev/scrape/planet
```

Geocode any theatres that arrive without coordinates (rare — only if a chain
adds a venue):

```bash
fly ssh console --app on-cinema-ran --command "python geocode.py"
```

---

## Cost

Roughly **$2–5/month**: one shared-cpu-1x machine at 512MB plus a 1GB volume.
The 512MB is deliberate — the API builds each response from the full screening
set in memory, and Lev's scrape holds a lot of parsed HTML. At the 256MB
default the OOM killer would likely take it out mid-scrape.

To pause billing without deleting anything:

```bash
fly scale count 0 --app on-cinema-ran
```

---

## Gotchas worth knowing

**Don't add workers.** The `CMD` pins `--workers 1` on purpose. The scraper runs
inside the web process, so N workers would mean N copies of every scrape loop
writing to one SQLite file.

**Redeploying is safe for your data** — the volume is separate from the image.
But `create_table.py --rebuild` on the server would wipe it.

**If you ever change `models.py`,** the deployed database won't gain the new
columns automatically; `create_all` only creates missing *tables*, never alters
existing ones. You'd need to rebuild the volume's database or write a migration.

**The database file is not in git** (`*.db` is gitignored), so the production
database is built entirely by scraping. Nothing local is uploaded.
