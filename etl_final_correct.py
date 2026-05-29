#!/usr/bin/env python3
"""Complete Parkrun ETL - fixed location mapping, resumable."""
import psycopg2
import openpyxl
import re
import csv
from pathlib import Path
from datetime import datetime, date
import time

BASE_DIR = Path("/home/oc/Documents/Parkrun")
RAW_DIR = BASE_DIR / "Raw2"
start_time = time.time()

def log(msg):
    print(f"[{time.time()-start_time:.1f}s] {msg}", flush=True)

def phase(name):
    log(f"\n{'='*60}")
    log(f"[{name}]")
    log(f"{'='*60}")

phase("PARKRUN ETL - BEGIN")

# === CONNECT ===
conn = psycopg2.connect(host="10.21.63.200", dbname="parkrun", user="postgres", password="TempPass123!")
cur = conn.cursor()

# Check if we can resume (tables exist with data)
cur.execute("SELECT COUNT(*) FROM tracked_events")
te_count = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM events")
ev_count = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM participation")
pp_count = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM volunteers")
pv_count = cur.fetchone()[0]

log(f"Existing data: tracked_events={te_count}, events={ev_count}, participation={pp_count}, volunteers={pv_count}")

if te_count > 0 and pp_count > 0:
    log("Tables already populated - skipping to stats")
    # Print stats
    cur.execute("SELECT COUNT(*) FROM people")
    log(f"  people:            {cur.fetchone()[0]:>8,}")
    log(f"  tracked_events:    {te_count:>8,}")
    log(f"  events:            {ev_count:>8,}")
    log(f"  participation:     {pp_count:>8,}")
    log(f"  volunteers:        {pv_count:>8,}")
    log("\nDone!")
    conn.close()
    exit()

# === PHASE 1: SCHEMA ===
phase("SCHEMA SETUP")
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
existing = [r[0] for r in cur.fetchall()]
log(f"Existing tables before: {existing}")

for tbl in existing:
    cur.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")
conn.commit()

cur.execute("""CREATE TABLE tracked_events (
    id SERIAL PRIMARY KEY,
    event_name VARCHAR(255), folder VARCHAR(255), URL VARCHAR(512),
    latitude DOUBLE PRECISION, longitude DOUBLE PRECISION,
    local_authority VARCHAR(100), junior VARCHAR(20),
    latest_event INTEGER, guid VARCHAR(255)
)""")

cur.execute("""CREATE TABLE locations (
    id SERIAL PRIMARY KEY,
    location_name VARCHAR(255),
    folder VARCHAR(255),
    url_slug VARCHAR(255),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    local_authority VARCHAR(100),
    junior VARCHAR(20),
    latest_event INTEGER,
    guid VARCHAR(255)
)""")

cur.execute("""CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    event_num INTEGER NOT NULL,
    location_id INTEGER REFERENCES locations(id),
    event_name VARCHAR(255),
    location_folder VARCHAR(255),
    event_date DATE,
    UNIQUE(event_num, location_id)
)""")

cur.execute("""CREATE TABLE people (
    id SERIAL PRIMARY KEY,
    person_id INTEGER NOT NULL UNIQUE,
    person_name VARCHAR(255),
    gender VARCHAR(10),
    total_parkruns INTEGER DEFAULT 0,
    has_100_club BOOLEAN DEFAULT FALSE,
    last_seen DATE,
    UNIQUE(person_id)
)""")

cur.execute("""CREATE TABLE participation (
    id SERIAL PRIMARY KEY,
    event_id INTEGER REFERENCES events(id),
    event_num INTEGER,
    location_id INTEGER,
    event_date DATE,
    parkrun_id INTEGER,
    person_name VARCHAR(255),
    gender VARCHAR(10),
    finish_position INTEGER,
    club VARCHAR(255),
    age_grade DECIMAL(10,4),
    finish_time VARCHAR(30)
)""")

cur.execute("""CREATE TABLE volunteers (
    id SERIAL PRIMARY KEY,
    event_id INTEGER REFERENCES events(id),
    event_num INTEGER,
    location_id INTEGER,
    event_date DATE,
    parkrun_id INTEGER,
    person_name VARCHAR(255),
    volunteer_role VARCHAR(100),
    club VARCHAR(255)
)""")

cur.execute("CREATE INDEX idx_part_parkrun ON participation (parkrun_id)")
cur.execute("CREATE INDEX idx_part_event ON participation (event_num, location_id)")
cur.execute("CREATE INDEX idx_part_date ON participation (event_date)")
cur.execute("CREATE INDEX idx_vol_parkrun ON volunteers (parkrun_id)")
cur.execute("CREATE INDEX idx_vol_event ON volunteers (event_num, location_id)")
cur.execute("CREATE INDEX idx_events_date ON events (event_date)")
cur.execute("CREATE INDEX idx_locations ON locations(folder)")
conn.commit()
log("Schema OK ✓")

# === PHASE 2: TRACKEDEVENTS + LOCATIONS ===
phase("TRACKEDEVENTS + LOCATIONS")
csv_path = BASE_DIR / "TrackedEvents.csv"
with open(csv_path, 'r') as f:
    csv_rows = list(csv.DictReader(f))

log(f"CSV has {len(csv_rows)} tracked locations")

for row in csv_rows:
    lat_s = str(row.get('Latitude', '')).strip()
    lon_s = str(row.get('Longitude', '')).strip()
    lat = float(lat_s) if lat_s and lat_s not in ('None', '') else None
    lon = float(lon_s) if lon_s and lon_s not in ('None', '') else None
    latest_s = str(row.get('LatestEventNumber', '')).strip().replace(',', '')
    latest = int(latest_s) if latest_s.isdigit() else None
    
    cur.execute("""INSERT INTO tracked_events (event_name, folder, URL, latitude, longitude, local_authority, junior, latest_event, guid)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (row['Title'], row['folder'], row['URL'], lat, lon,
         row.get('Local Authoritie'), row.get('Junior','5k'), latest, row['GUID']))

    # Also populate locations table (one row per tracked event)
    cur.execute("""INSERT INTO locations (location_name, folder, url_slug, latitude, longitude, local_authority, junior, latest_event, guid)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (row['Title'], row['folder'], row['URL'].split('/')[-1] if row['URL'] else row['folder'],
         lat, lon, row.get('Local Authoritie'), row.get('Junior','5k'), latest, row['GUID']))

conn.commit()

# Verify count
cur.execute("SELECT COUNT(*) FROM locations")
log(f"Locations loaded: {cur.fetchone()[0]} rows")

cur.execute("SELECT id, location_name, folder, url_slug FROM locations ORDER BY id")
for loc in cur.fetchall():
    log(f"  id={loc[0]}: {loc[1]:25} folder={loc[2]:25} url={loc[3]}")

# Build mapping: xlsx folder name → location_id
# xlsx files have names like "Denton Dene-Event-001.xlsx" or "jesmonddene-Event-001.xlsx"
# CSV folder names are the canonical match
folder_map = {}
cur.execute("SELECT id, folder FROM locations")
for rid, folder in cur.fetchall():
    folder_map[folder.lower()] = rid
    folder_map[folder] = rid  # case-sensitive too
    folder_map[folder.replace(' ', '').lower()] = rid

log("\nFolder mapping:")
for k, v in sorted(folder_map.items()):
    log(f"  '{k}' → {v}")

# === PHASE 3: EVENT DATES FROM HISTORY ===
phase("EVENT DATES (from history files)")
history_files = sorted(RAW_DIR.glob("*-event_history.xlsx"))
event_date_map = {}  # (la_part, event_num) → date

for hf in history_files:
    wb = openpyxl.load_workbook(hf, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        continue
    base = hf.stem.replace('-event_history', '')
    for row in rows:
        if not row or row[0] is None:
            continue
        e_num = row[0]
        if not isinstance(e_num, (int, float)):
            continue
        e_num = int(e_num)
        if not row[1]:
            continue
        date_s = str(row[1]).strip().split('\n')[0].split('\n')[0].strip()
        m = re.match(r'(\d{2}/\d{2}/\d{4})', date_s)
        if m:
            d = datetime.strptime(m.group(1), '%d/%m/%Y').date()
            event_date_map[(base, e_num)] = d
            event_date_map[(base.lower(), e_num)] = d

log(f"Dates loaded: {len(event_date_map)} entries")

# === PHASE 4: EVENTS ===
phase("EVENTS")
event_files = sorted(RAW_DIR.glob("*-Event-*.xlsx"))
vol_files_all = sorted(RAW_DIR.glob("*-Volunteers-*.xlsx"))
log(f"Event files: {len(event_files)}, Vol files: {len(vol_files_all)}")

all_events = []
seen = set()

for ef in event_files:
    match = re.search(r'Event-(\d+)', ef.stem)
    if not match:
        continue
    event_num = int(match.group(1))
    
    # Get location folder from filename (everything before -Event)
    loc_folder = ef.stem.split('-Event-')[0]
    
    # Find location_id
    location_id = 0
    for lk, vid in folder_map.items():
        if loc_folder.lower() == lk.lower() or loc_folder.replace(' ', '').lower() == lk.replace(' ', '').lower():
            location_id = vid
            break
    
    event_date = event_date_map.get((loc_folder, event_num))
    if not event_date:
        event_date = event_date_map.get((loc_folder.lower(), event_num))
    
    key = (event_num, location_id)
    if key not in seen:
        seen.add(key)
        all_events.append((event_num, event_date, location_id, loc_folder))

# Also add events from history files not in xlsx
for hf in history_files:
    wb = openpyxl.load_workbook(hf, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    base = hf.stem.replace('-event_history', '')
    
    # Find location_id
    location_id = 0
    for lk, vid in folder_map.items():
        if lk.lower() == base.lower():
            location_id = vid
            break
    
    for row in rows:
        if not row or row[0] is None:
            continue
        e_num = row[0]
        if not isinstance(e_num, (int, float)):
            continue
        e_num = int(e_num)
        if not row[1]:
            continue
        date_s = str(row[1]).strip().split('\n')[0].split('\n')[0].strip()
        m = re.match(r'(\d{2}/\d{2}/\d{4})', date_s)
        if m:
            d = datetime.strptime(m.group(1), '%d/%m/%Y').date()
            key = (e_num, location_id)
            if key not in seen:
                seen.add(key)
                all_events.append((e_num, d, location_id, base))

log(f"Total unique events: {len(all_events)}")

# Insert events
cur = conn.cursor()
evt_insert = "INSERT INTO events (event_num, event_date, location_id, location_folder, event_name) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(event_num,location_id) DO NOTHING"
for i in range(0, len(all_events), 1000):
    batch = all_events[i:i+1000]
    cur.executemany(evt_insert, [(e[0], e[1], e[2], e[3], e[3]) for e in batch])
conn.commit()

cur.execute("SELECT COUNT(*) FROM events")
log(f"Events inserted: {cur.fetchone()[0]}")

# Get event_id map: (event_num, location_id) → event_id
cur.execute("SELECT id, event_num, location_id FROM events")
evt_map = {}
for r in cur.fetchall():
    evt_map[(r[1], r[2])] = r[0]
log(f"Event ID map: {len(evt_map)} entries")
log(f"Events with location: {sum(1 for e in evt_map if e[1] > 0)}")

# === PHASE 5: PARTICIPATION ===
phase("PARTICIPATION")
def extract_parkrun_id(url):
    if not url: return None
    m = re.search(r'/parkrunner/(\d+)', str(url).strip())
    return int(m.group(1)) if m else None

def parse_age_grade(raw):
    if not raw or str(raw).strip() in ('None', ''): return None
    m = re.search(r'([\d.]+)%', str(raw))
    return float(m.group(1)) / 100.0 if m else None

def clean_time(raw):
    if not raw: return None
    s = str(raw).strip()
    if s.startswith('1 day') or s.startswith('2 day'):
        m = re.search(r'(\d+):(\d+):(\d+)$', s)
        if m: return f"{m.group(1).zfill(2)}:{m.group(2).zfill(2)}:{m.group(3).zfill(2)}"
    return s

people_dict = {}
part_count = 0
processed = 0
part_insert = "INSERT INTO participation (event_id, event_num, location_id, event_date, parkrun_id, person_name, gender, finish_position, club, age_grade, finish_time) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"

cur = conn.cursor()

for ef in event_files:
    match = re.search(r'Event-(\d+)', ef.stem)
    if not match:
        continue
    event_num = int(match.group(1))
    event_date = None
    location_id = 0
    location_id_set = False
    
    # Find location
    loc_folder = ef.stem.split('-Event-')[0]
    for lk, vid in folder_map.items():
        if loc_folder.lower() == lk.lower():
            event_date = event_date_map.get((loc_folder, event_num))
            if not event_date:
                event_date = event_date_map.get((loc_folder.lower(), event_num))
            location_id = vid
            location_id_set = True
            break
    
    eid = evt_map.get((event_num, location_id))
    
    wb = openpyxl.load_workbook(ef, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    
    data_rows = []
    for row in rows:
        if not row or row[1] is None:  # position must exist
            continue
        if all(v is None or (isinstance(v, str) and v.strip() == '') for v in row):
            continue
        if not row[2] or not str(row[2]).strip():
            continue
        
        name = str(row[2]).strip()
        parkrun_id = extract_parkrun_id(row[3])
        
        gender_raw = str(row[5]).strip().upper() if row[5] else None
        gender = None
        if gender_raw and gender_raw in ('MALE', 'FEMALE', 'M', 'F', 'X'):
            gender = 'M' if gender_raw in ('MALE','M') else ('F' if gender_raw in ('FEMALE','F') else 'X')
        
        club = None
        if row[9] and str(row[9]).strip():
            club = str(row[9]).strip()
        
        age_grade = parse_age_grade(row[8])
        finish_time = clean_time(row[10])
        
        data_rows.append({
            'parkrun_id': parkrun_id,
            'name': name, 'gender': gender,
            'club': club, 'age_grade': age_grade, 'finish_time': finish_time,
            'position': int(row[1]) if row[1] is not None else None,
        })
        
        if parkrun_id:
            people_dict[parkrun_id] = {'name': name, 'gender': gender, 'club': club}

    part_count += len(data_rows)
    processed += 1

    if processed % 2000 == 0:
        log(f"  {processed}/{len(event_files)} files, ~{part_count:,} rows")

    if data_rows and eid:
        batch = []
        for dr in data_rows:
            batch.append((
                eid, event_num, location_id, event_date,
                dr['parkrun_id'], dr['name'], dr['gender'],
                dr['position'], dr['club'], dr['age_grade'], dr['finish_time']
            ))
        cur.executemany(part_insert, batch)
        conn.commit()

    if processed % 2000 == 0 and part_count > 0:
        log(f"  checkpoint {processed} files, {part_count:,} rows")

conn.commit()
log(f"Participation: {processed} files, {part_count:,} rows ✓")

# === PHASE 6: PEOPLE ===
phase("PEOPLE")
for pid, info in list(people_dict.items()):
    try:
        cur.execute("""INSERT INTO people (person_id, person_name, gender, last_seen)
            VALUES (%s,%s,%s,%s) ON CONFLICT(person_id) DO UPDATE SET
            person_name=EXCLUDED.person_name, total_parkruns=people.total_parkruns+1,
            last_seen=COALESCE(EXCLUDED.last_seen, people.last_seen)""",
            (pid, info['name'], info['gender'], date.today()))
        if pid % 5000 == 0:
            conn.commit()
    except:
        pass
conn.commit()
cur.execute("SELECT COUNT(*) FROM people")
log(f"People: {cur.fetchone()[0]} unique parkrunners ✓")

# === PHASE 7: VOLUNTEERS ===
phase("VOLUNTEERS")
vol_count = 0
vol_proc = 0
vol_insert = "INSERT INTO volunteers (event_id, event_num, location_id, event_date, parkrun_id, person_name, volunteer_role, club) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"

for vf in vol_files_all:
    match = re.search(r'Volunteers-(\d+)', vf.stem)
    if not match:
        continue
    event_num = int(match.group(1))
    event_date = None
    location_id = 0
    
    loc_folder = vf.stem.split('-Volunteers-')[0]
    for lk, vid in folder_map.items():
        if loc_folder.lower() == lk.lower():
            event_date = event_date_map.get((loc_folder, event_num))
            if not event_date:
                event_date = event_date_map.get((loc_folder.lower(), event_num))
            location_id = vid
            break
    
    eid = evt_map.get((event_num, location_id))
    
    wb = openpyxl.load_workbook(vf, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    
    data_rows = []
    for row in rows:
        if not row or row[0] is None or not row[0] or not str(row[0]).strip():
            continue
        if all(v is None or (isinstance(v, str) and v.strip() == '') for v in row):
            continue
        
        name = str(row[0]).strip()
        parkrun_id = extract_parkrun_id(row[1])
        
        role = None
        if row[3]:
            roles = [str(row[3]).strip()]
            for r2 in roles:
                for r3 in r2.split('\n'):
                    r3 = r3.strip()
                    if r3 and role is None:
                        role = r3
                    elif r3 and role:
                        role += f', {r3}'
        
        club = None
        if row[4] and str(row[4]).strip():
            club = str(row[4]).strip()
        
        data_rows.append({'parkrun_id': parkrun_id, 'name': name, 'role': role, 'club': club})

    vol_count += len(data_rows)
    vol_proc += 1

    if vol_proc % 2000 == 0:
        log(f"  {vol_proc}/{len(vol_files_all)} files, ~{vol_count:,} rows")

    if data_rows and eid:
        batch = []
        for dr in data_rows:
            batch.append((eid, event_num, location_id, event_date,
                         dr['parkrun_id'], dr['name'], dr['role'], dr['club']))
        cur.executemany(vol_insert, batch)
        conn.commit()

conn.commit()
cur.execute("SELECT COUNT(*) FROM volunteers")
log(f"Volunteers: {vol_proc} files, {cur.fetchone()[0]:,} rows ✓")

# === FINAL STATS ===
log("\n" + "=" * 60)
log("FINAL RESULTS")
log("=" * 60)

for tbl in ['tracked_events', 'events', 'people', 'participation', 'volunteers']:
    cur.execute(f"SELECT COUNT(*) FROM {tbl}")
    log(f"  {tbl:20} = {cur.fetchone()[0]:>8,}")

cur.execute("SELECT e.event_num,e.event_date,e.event_name,l.location_name FROM events e JOIN locations l ON e.location_id=l.id ORDER BY e.event_date DESC LIMIT 5")
log("\nLatest events:")
for r in cur.fetchall():
    log(f"  #{r[0]:>4} {r[2]:25} {r[3]:25} on {r[1]}")

cur.execute("SELECT l.location_name, COUNT(e.event_num) as cnt FROM events e JOIN locations l ON e.location_id=l.id GROUP BY l.location_name ORDER BY cnt DESC")
log("\nTop events by count:")
for r in cur.fetchall()[:5]:
    log(f"  {r[0]:25} = {r[1]:>4} events")

cur.execute("SELECT person_name, total_parkruns FROM people ORDER BY total_parkruns DESC LIMIT 3")
log("\nTop people:")
for r in cur.fetchall():
    log(f"  {r[0]:40} = {r[1]:>4} parkruns")

log(f"\nTotal time: {time.time()-start_time:.0f}s")
log("ETL COMPLETE!")
conn.close()
