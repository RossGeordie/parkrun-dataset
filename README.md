# parkrun-dataset

> parkrun results & volunteer data, ingested from the live parkrun.org.uk
> site into PostgreSQL, with an open-source BI layer (Apache Superset +
> Metabase) on top.

## What this is

A production pipeline that reads parkrun results and volunteer records
for multiple parks, stores them in PostgreSQL database, and serves them through
open-source BI — no proprietary stack.

The purpose of this project was twofold, firstly to prove that open source analytics
was mature enough to be a viable alternative to using paid solutions like Power
BI or Tableau and secondly to prove that Local AI was a capable tool. This entire
Repo has been written and created by our latest local AI implementation - "Sooty".

## What's in this repo

```
parkrun_pipeline.py   # main scraper — multi-park, Cloudflare-passing (Playwright + stealth)
spotcheck.py          # lightweight row-count / data spot-check against the DB
bi/
  compose.yaml        # stack: postgres + superset + metabase (+ postgres_meta initdb)
  entrypoint.sh       # initdb + seed_bi.py (Superset bootstrap, charts & dashboard)
  seed_bi.py          # Superset DB/chart/dashboard seeding
  dashboard.json      # the "Parkrun Overview" board definition
schema.sql            # DDL — parkrun schema (parks, event_history, finishers, volunteers)
.env.example          # PG credentials template (copy to .env)
requirements.txt      # run deps: psycopg2-binary, playwright, requests
requirements-dev.txt  # dev test deps
ruff.toml             # lint config
tests/                # pipeline unit tests
docs/architecture.md  # data model & scrape flow
```

## Parks supported

Registered in a `parkrun.parks` registry table at start. Current set:
- `jesmonddene` (Newcastle)
- `townmoor` (Newcastle)
- `leazes` (Newcastle)
- `dentondene` (Newcastle)

Add new parks at runtime:

```
python3 parkrun_pipeline.py add-park <slug> --name "Park Name" --city "City"
python3 parkrun_pipeline.py add-park <slug> --name "Park Name" --city "City" --disabled  # register but skip
```

## Quick start

```bash
# 1. Clone and install deps
git clone https://github.com/RossGeordie/parkrun-dataset
cd parkrun-dataset
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 2. Configure Postgres
cp .env.example .env   # fill in PG_HOST, PG_USER, PG_PASSWORD

# 3. Scrape (all modes)
python3 parkrun_pipeline.py scrape --mode init         # create schema, register parks
python3 parkrun_pipeline.py scrape --mode all          # event history + latest event per park
python3 parkrun_pipeline.py scrape --mode new          # incremental — events without finisher rows (cron mode)
python3 parkrun_pipeline.py scrape --mode backfill     # one-off — fill every event missing finishers
python3 parkrun_pipeline.py scrape --park townmoor     # restrict to one park

# 4. Verify row counts per park
python3 parkrun_pipeline.py verify
python3 parkrun_pipeline.py parks
```

## Modes

| mode       | what it does                                                        | idempotent |
|------------|---------------------------------------------------------------------|------------|
| `init`     | CREATE SCHEMA, CREATE TABLE IF NOT EXISTS, seed registry            | yes        |
| `history`  | scrape event-history table into `parkrun.event_history`             | yes (upsert) |
| `detail`   | scrape latest event's finisher + volunteer tables                   | yes (upsert) |
| `all`      | history + detail                                                    | yes        |
| `new`      | find events in history w/o finishers and scrape (safe cron mode)    | yes        |
| `latest`   | scrape the single most recent event per park                        | yes        |
| `backfill` | one-shot: all events in history that still lack finisher rows       | yes        |

## Superset / Metabase

The stack runs in Docker Compose. Bring it up against an existing Postgres
(`POSTGRES_HOST` env or `bi/.env`):

```bash
cd bi
docker compose up -d
```

| service   | port  |
|-----------|-------|
| Superset  | 8088  |
| Metabase  | 3000  |

Initial Superset credentials: `admin` / `admin`.
Superset DB + chart + dashboard seeding runs automatically on first start
(`entrypoint.sh` calls `seed_bi.py`).

## Testing / CI

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
pytest -q
```

GitHub Actions runs the same on every push/PR:
`.github/workflows/ci.yml`.

## License

MIT — see [LICENSE](LICENSE).
