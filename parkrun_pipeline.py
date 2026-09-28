#!/usr/bin/env python3
"""
parkrun_pipeline.py — scrape parkrun event history + per-event finishers/volunteers -> Postgres.

Datasets (1 parkrun, e.g. jesmonddene):
  event_history : one row per event
  finishers     : one row per finisher per event
  volunteers    : one row per volunteer per event

Usage:
  python3 parkrun_pipeline.py scrape --mode init                 # create schema (+ parks registry)
  python3 parkrun_pipeline.py scrape --mode all                  # event history + ALL events
  python3 parkrun_pipeline.py scrape --mode new                  # only events not yet in the DB (cron)
  python3 parkrun_pipeline.py scrape --mode latest --max-events N
  python3 parkrun_pipeline.py scrape --mode backfill               # fill events missing finisher rows
  python3 parkrun_pipeline.py scrape --park townmoor             # single-park override
  python3 parkrun_pipeline.py add-park dentondene --name "Denton Dene" --city "Manchester"
  python3 parkrun_pipeline.py verify                             # row counts per (registered) park
  python3 parkrun_pipeline.py parks                              # list the registry

`--park` defaults to `all` = every enabled row in the parkrun.parks registry.

Env (see .env.example): PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DATABASE  (or PG_DSN)
"""
import argparse
import asyncio
import os
import re
import sys

import psycopg2

BASE = "https://www.parkrun.org.uk/{park}/results/"
EVENTHISTORY = BASE + "eventhistory/"
EVENT_PAGE = "https://www.parkrun.org.uk/{park}/results/{num}/"

def _pg_dict() -> dict:
    url = os.environ.get("PG_DSN")
    if url:
        return dict(dsn=url, connect_timeout=10)
    if not all(os.environ.get(k) for k in ("PG_HOST", "PG_USER", "PG_PASSWORD", "PG_DATABASE")):
        raise SystemExit("PG_* env vars missing — copy .env.example to .env and export them")
    return dict(host=os.environ["PG_HOST"], port=int(os.environ.get("PG_PORT", "5432")),
                dbname=os.environ["PG_DATABASE"], user=os.environ["PG_USER"],
                password=os.environ["PG_PASSWORD"], connect_timeout=10)


def get_pg() -> dict:
    """Lazily build the psycopg2 connect dict (env-driven, no creds in source)."""
    return _pg_dict()

STEALTH = "Object.defineProperty(navigator,'webdriver',{get:()=>false});window.chrome=window.chrome||{runtime:{}};"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
DELAY_RANGE = (1.5, 3.5)  # seconds between page loads


def rand_delay():
    import random
    return random.uniform(*DELAY_RANGE)


# ---------------------------------------------------------------- SQL
SCHEMA = """
CREATE SCHEMA IF NOT EXISTS parkrun;

CREATE TABLE IF NOT EXISTS parkrun.event_history (
    park           TEXT NOT NULL,
    event_no       INTEGER NOT NULL,
    event_date     DATE NOT NULL,
    n_finishers    INTEGER,
    n_volunteers   INTEGER,
    male_first_name TEXT,
    male_first_time TEXT,
    female_first_name TEXT,
    female_first_time TEXT,
    PRIMARY KEY (park, event_no)
);

CREATE TABLE IF NOT EXISTS parkrun.finishers (
    park        TEXT NOT NULL,
    event_no    INTEGER NOT NULL,
    position    INTEGER,
    name        TEXT NOT NULL,
    gender      TEXT,
    age_group   TEXT,
    club        TEXT,
    time_raw    TEXT,
    time_s      INTEGER,
    result_note TEXT,
    age_grade   NUMERIC(5,2),
    n_finishes  INTEGER,
    finishes_badge  INTEGER,
    volunteer_badge INTEGER,
    parkrun_id  TEXT,
    PRIMARY KEY (park, event_no, position, name)
);

CREATE TABLE IF NOT EXISTS parkrun.volunteers (
    park        TEXT NOT NULL,
    event_no    INTEGER NOT NULL,
    ord         INTEGER NOT NULL,
    name        TEXT NOT NULL,
    roles       TEXT[],
    club        TEXT,
    volunteer_credits INTEGER,
    volunteer_badge INTEGER,
    finishes_badge INTEGER,
    parkrun_id  TEXT,
    PRIMARY KEY (park, event_no, ord, name)
);

-- Registry of parkrun events (parks) to scrape; slug == URL path segment
CREATE TABLE IF NOT EXISTS parkrun.parks (
    slug            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    city            TEXT,
    url             TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    last_scraped_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fin_park_date ON parkrun.finishers (park);
"""


# ------------------------------------------------------- parks registry
def list_parks(cur):
    cur.execute(
        "SELECT slug, name, city, url, enabled, last_scraped_at "
        "FROM parkrun.parks ORDER BY slug"
    )
    return cur.fetchall()


def cmd_parks():
    conn = psycopg2.connect(**get_pg())
    cur = conn.cursor()
    rows = list_parks(cur)
    if not rows:
        print("no parks registered — add one with: parkrun_pipeline.py add-park <slug> --name <Name>")
    for slug, name, city, _url, enabled, last in rows:
        print(f"  {slug:<14} {name:<14} {city or '-':<12} "
              f"{'enabled' if enabled else 'DISABLED':<8} last_scraped: {last}")
    cur.close()
    conn.close()


def cmd_add_park(slug, name=None, city=None, enabled=True):
    slug = slug.strip().lower()
    conn = psycopg2.connect(**get_pg())
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO parkrun.parks (slug, name, city, url, enabled)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (slug) DO UPDATE SET
             name=EXCLUDED.name, city=EXCLUDED.city,
             url=EXCLUDED.url, enabled=EXCLUDED.enabled""",
        (slug, name or slug.title(), city,
         f"https://www.parkrun.org.uk/{slug}/results/", enabled),
    )
    conn.commit()
    print(f"registered park: {slug}  (enabled={enabled})")
    cur.close()
    conn.close()


def parse_time_raw(t: str):
    """'17:15' -> 1035 ; '1:02:33' -> 3753 ; '' -> None"""
    t = (t or "").strip()
    parts = [p for p in t.split(":") if p.strip().isdigit()]
    if not parts:
        return None
    parts = [int(p) for p in parts]
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return secs


def clean(s):
    return re.sub(r"\s+", " ", (s or "").strip())


# ------------------------------------------------------------- scraping
async def scrape_event_history(ctx, park):
    page = await _open_event_page(ctx, EVENTHISTORY.format(park=park))
    try:
        rows = await page.evaluate(
            """() => [...document.querySelectorAll('table tbody tr')].map(tr => {
            const c = [...tr.querySelectorAll('td')].map(td => td.innerText.trim().replace(/\\n/g,' '));
            const a = tr.querySelector('a[href]');
            const href = a ? a.getAttribute('href') : null;
            return {cells: c, href, name: a ? a.innerHTML.match(/parkrunner\\/(\\d+)/) : null};
            })"""
        )
    finally:
        try:
            await page.close()
        except Exception:
            pass

    events = []
    for r in rows:
        c = r["cells"]
        if len(c) < 3 or not c[0].isdigit():
            continue
        # cells: EVENT#, date, finishers, volunteers, [name, time, name, time] interleaved
        ev = dict(
            park=park,
            event_no=int(c[0]),
            event_date=c[1],
            n_finishers=int(c[2]) if c[2].isdigit() else None,
            n_volunteers=int(c[3]) if len(c) > 3 and c[3].isdigit() else None,
            male_first_name=clean(c[4]) if len(c) > 4 else None,
            male_first_time=clean(c[5]) if len(c) > 5 else None,
            female_first_name=clean(c[6]) if len(c) > 6 else None,
            female_first_time=clean(c[7]) if len(c) > 7 else None,
        )
        events.append(ev)
    return events


def _parse_badges(clubs):
    """['Results-table--50club','Results-table--v100club',...] -> (max_finish_badge, max_volunteer_badge)"""
    fin_max, vol_max = None, None
    for c in clubs or []:
        m = re.search(r"Results-table--(v?)(\d+)club", c)
        if m:
            n = int(m.group(2))
            if m.group(1) == "v":
                vol_max = n if vol_max is None else max(vol_max, n)
            else:
                fin_max = n if fin_max is None else max(fin_max, n)
    return fin_max, vol_max


def _num(pattern, text):
    m = re.search(pattern, text or "")
    return int(m.group(1)) if m else None


async def _open_event_page(ctx, url, selector="table tbody tr", timeout_ms=30000, retries=3):
    """Navigate to a parkrun page and wait for a selector.
    parkrun pages intermittently stall on first paint.
    Retry with linear backoff; close failed pages so ctx does not leak.
    """
    import asyncio
    import urllib.parse
    last = None
    label = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1] or "page"
    for attempt in range(1, retries + 1):
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_selector(selector, timeout=timeout_ms)
            return page
        except Exception as e:
            last = e
            if attempt < retries:
                print(f"  [retry {attempt}/{retries}] {label}: "
                      f"{type(e).__name__}: {str(e)[:90]}", flush=True)
                await asyncio.sleep(1.5 * attempt)
            else:
                try:
                    await page.close()
                except Exception:
                    pass
    raise last


async def scrape_event_detail(ctx, park, event_no, timeout_ms=30000):
    page = await _open_event_page(ctx, EVENT_PAGE.format(park=park, num=event_no),
                                  timeout_ms=timeout_ms)
    try:
        await page.evaluate(
            """() => {
          for (const cls of ['js-ResultsSelect','js-VolunteersSelect']) {
            for (const s of [...document.querySelectorAll('select.' + cls)]) {
              if ([...s.options].some(o => o.value === 'detailed')) {
                s.value = 'detailed';
                s.dispatchEvent(new Event('change', {bubbles: true}));
                break;
              }
            }
          }
          return true;
        }"""
        )
        await page.wait_for_timeout(2500)
        data = await page.evaluate(
        """() => {
          const tables = [...document.querySelectorAll('table')];
          const fin = tables.find(t => /POSITION/.test((t.querySelector('thead')?.innerText)||''));
          const vol = tables.find(t => /VOLUNTEER ROLES/.test((t.querySelector('thead')?.innerText)||''));
          const grab = t => t ? [...t.querySelectorAll('tbody tr')].map(tr => {
              const a = tr.querySelector('a[href]');
              const clubs = [...tr.querySelectorAll('[class*="club"]')].map(e => (e.className||'').toString());
              return {
                cells: [...tr.querySelectorAll('td')].map(td => td.innerText.trim().replace(/\\n/g,'|')),
                href: a ? a.getAttribute('href') : null,
                aname: a ? a.innerText.trim() : null,
                clubs: [...new Set(clubs)]
              };
          }) : null;
          return {finishers: grab(fin), volunteers: grab(vol)};
        }"""
        )
    finally:
        try:
            await page.close()
        except Exception:
            pass

    finishers, volunteers = [], []

    for row in (data["finishers"] or []):
        if not row.get("cells"):
            continue
        cells = row["cells"]
        if len(cells) < 2 or not (cells[0] or "").lstrip("-").isdigit():
            continue
        text = " | ".join(cells)
        m = re.search(r"parkrunner/(\d+)", row.get("href") or "")
        # cells[1] = "NAME|272 finishes | 250 milestone ..." -> first line is the name
        name = clean((cells[1] or "").split("|")[0]) or (row.get("aname") or "").split("\n")[0].strip()
        age_m = re.search(r"(\d+(?:\.\d+)?)%\s*age grade", text)
        # cells[2] = "Male|5/181", cells[3] = "VM35-39|68.62% age grade"
        gender = clean((cells[2] or "").split("|")[0]) if len(cells) > 2 else None
        age_group = clean((cells[3] or "").split("|")[0]) if len(cells) > 3 else None
        club = clean(cells[4]) if len(cells) > 4 else None
        time_cell = (cells[5] or "") if len(cells) > 5 else ""
        time_m = re.match(r"([\d:]+)", time_cell)
        fin = dict(
            park=park, event_no=event_no,
            position=int(cells[0].lstrip("-")),
            name=name,
            gender=gender,
            age_group=age_group,
            club=club,
            time_raw=time_m.group(1) if time_m else None,
            age_grade=float(age_m.group(1)) if age_m else None,
            n_finishes=_num(r"(\d+)\s+finishes", text),
            parkrun_id=m.group(1) if m else None,
        )
        fin["finishes_badge"], fin["volunteer_badge"] = _parse_badges(row.get("clubs"))
        fin["time_s"] = parse_time_raw(fin["time_raw"])
        fin["result_note"] = next(
            (tag for tag in ("First Timer", "New PB", "New Personal Best")
             if tag.lower() in (text or "").lower()),
            None)
        finishers.append(fin)

    ord_ = 0
    for row in (data["volunteers"] or []):
        if not row.get("cells") or not row["cells"][0]:
            continue
        ord_ += 1
        cells = row["cells"]
        text = " | ".join(cells)
        m = re.search(r"parkrunner/(\d+)", row.get("href") or "")
        name = clean((cells[0] or "").split("|")[0]) or (row.get("aname") or "").split("\n")[0].strip()
        vol = dict(
            park=park, event_no=event_no, ord=ord_,
            name=name,
            roles=[clean(r) for r in cells[1].split("|") if clean(r)] if len(cells) > 1 else None,
            club=clean(cells[2]) if len(cells) > 2 else None,
            volunteer_credits=_num(r"(\d+)\s+volunteer credits", text),
            parkrun_id=m.group(1) if m else None,
        )
        vol["finishes_badge"], vol["volunteer_badge"] = _parse_badges(row.get("clubs"))
        volunteers.append(vol)
    return finishers, volunteers


# --------------------------------------------------------------- loading
def parse_date(s: str):
    """'15/08/2026' -> '2026-08-15'"""
    s = (s or "").strip()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return s


def load_events(cur, park, events):
    for ev in events:
        ev["event_date"] = parse_date(ev["event_date"])
    cur.executemany(
        """INSERT INTO parkrun.event_history
           (park,event_no,event_date,n_finishers,n_volunteers,
            male_first_name,male_first_time,female_first_name,female_first_time)
           VALUES (%(park)s,%(event_no)s,%(event_date)s,%(n_finishers)s,%(n_volunteers)s,
            %(male_first_name)s,%(male_first_time)s,%(female_first_name)s,%(female_first_time)s)
           ON CONFLICT (park,event_no) DO UPDATE SET
            event_date=EXCLUDED.event_date, n_finishers=EXCLUDED.n_finishers,
            n_volunteers=EXCLUDED.n_volunteers,
            male_first_name=EXCLUDED.male_first_name, male_first_time=EXCLUDED.male_first_time,
            female_first_name=EXCLUDED.female_first_name, female_first_time=EXCLUDED.female_first_time""",
        events)


def load_detail(cur, park, event_no, finishers, volunteers):
    cur.execute("DELETE FROM parkrun.finishers WHERE park=%s AND event_no=%s", (park, event_no))
    cur.execute("DELETE FROM parkrun.volunteers WHERE park=%s AND event_no=%s", (park, event_no))
    if finishers:
        cur.executemany(
            """INSERT INTO parkrun.finishers
               (park,event_no,position,name,gender,age_group,club,time_raw,time_s,result_note,
                age_grade,n_finishes,finishes_badge,volunteer_badge,parkrun_id)
               VALUES (%(park)s,%(event_no)s,%(position)s,%(name)s,%(gender)s,%(age_group)s,
                       %(club)s,%(time_raw)s,%(time_s)s,%(result_note)s,
                       %(age_grade)s,%(n_finishes)s,%(finishes_badge)s,%(volunteer_badge)s,%(parkrun_id)s)
               ON CONFLICT DO NOTHING""", finishers)
    if volunteers:
        vol = [{**v, "roles": v["roles"]} for v in volunteers]
        cur.executemany(
            """INSERT INTO parkrun.volunteers
               (park,event_no,ord,name,roles,club,volunteer_credits,volunteer_badge,finishes_badge,parkrun_id)
               VALUES (%(park)s,%(event_no)s,%(ord)s,%(name)s,%(roles)s,%(club)s,
                       %(volunteer_credits)s,%(volunteer_badge)s,%(finishes_badge)s,%(parkrun_id)s)
               ON CONFLICT DO NOTHING""", vol)


# ---------------------------------------------------------------- driver
async def run_park(pw, park, mode, max_events=None):
    conn = psycopg2.connect(**get_pg())
    cur = conn.cursor()
    launch_args = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
    browser = await pw.chromium.launch(headless=True, args=launch_args)
    ctx = await browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 900}, locale="en-GB")
    await ctx.add_init_script(STEALTH)
    try:
        # 1) event history
        events = await scrape_event_history(ctx, park)
        print(f"event history: {len(events)} events  (#{events[-1]['event_no']} .. #{events[0]['event_no']})")
        if events:
            # Always upsert the scraped event history: counts/dates can change
            # for already-seen events (re-counts, firsts corrections), so even a
            # fully-caught-up day refreshes the table.
            load_events(cur, park, events)
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM parkrun.event_history WHERE park=%s", (park,))
            print(f"DB event_history rows: {cur.fetchone()[0]}")
            if mode == "history":
                return 0, 0
        allowed_detail = ("all", "detail", "new", "latest", "backfill")
        if mode not in allowed_detail:
            return 0, 0

        # 2) target selection by mode
        if mode == "new":
            # "Already seen" = BOTH detail tables have at least one row for the
            # event. Anything on the website that fails that check is a
            # (re)scrape target: a newly-listed event, or an older event whose
            # detail rows were later purged. load_detail is delete-then-insert
            # for its target events, so a whole-event purge self-heals on the
            # next run; events complete in both tables are left untouched, so a
            # manual single-row removal on an otherwise-complete event is kept.
            cur.execute("SELECT event_no FROM parkrun.finishers WHERE park=%s", (park,))
            fin = {r[0] for r in cur.fetchall()}
            cur.execute("SELECT event_no FROM parkrun.volunteers WHERE park=%s", (park,))
            vol = {r[0] for r in cur.fetchall()}
            complete = fin & vol
            seen  = fin | vol
            healed = [e["event_no"] for e in events if e["event_no"] in seen
                      and e["event_no"] not in complete]
            new    = [e["event_no"] for e in events if e["event_no"] not in seen]
            targets = [e for e in events
                       if e["event_no"] in (set(new + healed))]
            if targets:
                nos = [e["event_no"] for e in targets]
                print(f"new mode: {len(targets)} events to (re)scrape  "
                      f"(#{min(nos)} .. #{max(nos)})")
                if new:
                    print(f"  new events: {sorted(new)}")
                if healed:
                    print(f"  healed (purged/stale re-scrape): {sorted(healed)}")
                load_events(cur, park, targets)
                conn.commit()
            else:
                print("new mode: no new events and nothing to heal "
                      f"(all {len(events)} scraped events have finisher+volunteer rows)")
                return 0, 0
        elif mode == "backfill":
            cur.execute("SELECT DISTINCT event_no FROM parkrun.finishers WHERE park=%s", (park,))
            done = {r[0] for r in cur.fetchall()}
            targets = [e for e in events if e["event_no"] not in done]
            nos = [e["event_no"] for e in targets]
            if not nos:
                print(f"backfill: nothing to do ({len(done)} events already scraped)")
                return 0, 0
            print(f"backfill: {len(nos)} events to scrape  (#{min(nos)} .. #{max(nos)})")
        elif mode == "latest":
            n = max_events or 5
            targets = events[:n]
            nos = [e["event_no"] for e in targets]
            print(f"latest mode: re-pulling most recent {len(targets)} events  (#{min(nos)} .. #{max(nos)})")
        else:
            targets = events if max_events is None else events[:max_events]
        targets = sorted(targets, key=lambda e: e["event_no"])  # oldest first
        ok = fail = 0
        for i, ev in enumerate(targets, start=1):
            no = ev["event_no"]
            for attempt in range(2):
                try:
                    f, v = await scrape_event_detail(ctx, park, no)
                    load_detail(cur, park, no, f, v)
                    conn.commit()
                    ok += 1
                    print(f"[{i}/{len(targets)}] event #{no}: {len(f)} finishers, {len(v)} volunteers  OK")
                    break
                except Exception as e:
                    if attempt == 1:
                        conn.rollback()
                        fail += 1
                        print(f"[{i}/{len(targets)}] event #{no}: FAILED {e}")
                    else:
                        await asyncio.sleep(3)
            if i < len(targets):
                await asyncio.sleep(rand_delay())
        # mark registry
        cur.execute(
            "UPDATE parkrun.parks SET last_scraped_at=CURRENT_TIMESTAMP WHERE slug=%s AND enabled=TRUE", (park,))
        conn.commit()
    finally:
        await browser.close()
        cur.close()
        conn.close()
    print(f"DONE [{park}]: events_ok={ok} events_fail={fail}")
    return ok, fail


async def run(parks, mode, max_events=None, verbose=False):
    """Run the pipeline for one or more parks (each with its own browser+conn)."""
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        results = {}
        for park in parks:
            if verbose:
                print(f"[parkrun_pipeline] park={park} mode={mode} max_events={max_events}")
            try:
                results[park] = await run_park(pw, park, mode, max_events)
            except Exception as e:
                results[park] = (0, 1)
                print(f"[{park}] parkrun_pipeline FAILED: {e}")
    tot_ok = sum(r[0] for r in results.values())
    tot_fail = sum(r[1] for r in results.values())
    print(f"OVERALL: parks={len(parks)} events_ok={tot_ok} events_fail={tot_fail} {results}")
    return tot_ok, tot_fail


def cmd_verify(park):
    conn = psycopg2.connect(**get_pg())
    cur = conn.cursor()
    if not park:
        cur.execute("SELECT slug FROM parkrun.parks ORDER BY slug")
        slugs = [r[0] for r in cur.fetchall()]
        print(f"registry: {slugs}")
    else:
        slugs = [park]
    tot_f = tot_v = tot_e = 0
    for s in slugs:
        cur.execute("SELECT COUNT(*) FROM parkrun.event_history WHERE park=%s", (s,))
        e = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM parkrun.finishers WHERE park=%s", (s,))
        f = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM parkrun.volunteers WHERE park=%s", (s,))
        v = cur.fetchone()[0]
        tot_e += e
        tot_f += f
        tot_v += v
        print(f"  {s:<14} events={e:<6} finishers={f:<8} volunteers={v}")
        cur.execute(
            "SELECT event_no, event_date, n_finishers FROM parkrun.event_history "
            "WHERE park=%s ORDER BY event_no DESC LIMIT 1", (s,))
        row = cur.fetchone()
        print(f"  {s:<14} latest event #{row[0]} {row[1]} ({row[2]} finishers) on website")
    print(f"TOTAL: events={tot_e} finishers={tot_f} volunteers={tot_v}")
    cur.close()
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "add-park":
        ap2 = argparse.ArgumentParser(prog="parkrun_pipeline.py add-park")
        ap2.add_argument("slug")
        ap2.add_argument("--name", default=None)
        ap2.add_argument("--city", default=None)
        ap2.add_argument("--disabled", action="store_true")
        a2 = ap2.parse_args(sys.argv[2:])
        cmd_add_park(a2.slug, name=a2.name, city=a2.city, enabled=not a2.disabled)
        sys.exit(0)

    ap = argparse.ArgumentParser()
    ap.add_argument("command",
                    choices=["scrape", "verify", "parks", "add-park"])
    ap.add_argument("--park", default=None,
                    help="single park slug (default: verify=all registered, scrape=all enabled from registry)")
    ap.add_argument("--mode", default="all", choices=["init", "history", "detail", "all", "new", "latest", "backfill"])
    ap.add_argument("--max-events", type=int, default=None)
    ap.add_argument("--name", default=None, help="for add-park: display name")
    ap.add_argument("--city", default=None, help="for add-park: city")
    ap.add_argument("--disabled", action="store_true", help="for add-park: register but do not scrape")
    a = ap.parse_args()
    if a.command == "verify":
        cmd_verify(a.park or "")
    elif a.command == "parks":
        cmd_parks()
    elif a.command == "add-park":
        cmd_add_park(sys.argv[1], name=a.name, city=a.city, enabled=not a.disabled)
    else:
        if a.mode == "init":
            conn = psycopg2.connect(**get_pg())
            cur = conn.cursor()
            cur.execute(SCHEMA)
            # Idempotent migration for pre-existing tables (CT 305 already had the base schema).
            for col, typ in [
                ("age_grade", "NUMERIC(5,2)"),
                ("n_finishes", "INTEGER"),
                ("finishes_badge", "INTEGER"),
                ("volunteer_badge", "INTEGER"),
                ("result_note", "TEXT"),
                ("parkrun_id", "TEXT"),
            ]:
                cur.execute(f"ALTER TABLE parkrun.finishers ADD COLUMN IF NOT EXISTS {col} {typ}")
            for col, typ in [
                ("volunteer_badge", "INTEGER"),
                ("finishes_badge", "INTEGER"),
                ("parkrun_id", "TEXT"),
            ]:
                cur.execute(f"ALTER TABLE parkrun.volunteers ADD COLUMN IF NOT EXISTS {col} {typ}")
            # Seed the initial park set if the registry is empty (idempotent).
            cur.execute("SELECT COUNT(*) FROM parkrun.parks")
            if cur.fetchone()[0] == 0:
                for slug, name, city in [
                    ("jesmonddene", "Jesmond Dene", "Newcastle"),
                    ("townmoor", "Town Moor", "Sheffield"),
                    ("leazes", "Leazes Park", "Swansea"),
                    ("dentondene", "Denton Dene", "Barnsley"),
                ]:
                    cur.execute(
                        "INSERT INTO parkrun.parks (slug, name, city, url, enabled) VALUES (%s,%s,%s,%s,TRUE)",
                        (slug, name, city, f"https://www.parkrun.org.uk/{slug}/results/"))
            conn.commit()
            cur.close()
            conn.close()
            print("schema created / columns ensured / registry seeded (if empty)")
        # resolve park list: explicit --park wins, else enabled registry
        if a.park:
            parks = [a.park]
        else:
            conn = psycopg2.connect(**get_pg())
            cur = conn.cursor()
            cur.execute("SELECT slug FROM parkrun.parks WHERE enabled=TRUE ORDER BY slug")
            parks = [r[0] for r in cur.fetchall()]
            cur.close()
            conn.close()
            if not parks:
                raise SystemExit(
                    "no enabled parks in registry — run: parkrun_pipeline.py add-park <slug> or seed via --mode init")
        asyncio.run(run(parks, a.mode, a.max_events, verbose=len(parks) > 1))
