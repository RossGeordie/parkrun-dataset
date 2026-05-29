#!/usr/bin/env python3
"""Complete parkrun ETL - fixed regex to match actual filename format."""
import psycopg2, openpyxl, re, time, csv
from pathlib import Path
from datetime import date

start_time = time.time()
base_dir = Path("/home/oc/Documents/Parkrun")
raw2_dir = base_dir / "Raw2"

conn = psycopg2.connect(host="10.21.63.200", dbname="parkrun", user="postgres", password="TempPass123!")
conn.autocommit = False
cur = conn.cursor()

### PHASE 0: Schema ###
print(f"[{time.time()-start_time:.1f}s] Phase 0: Schema")
for tbl in ['tracked_events', 'events', 'participation', 'volunteers', 'people', 'locations']:
    cur.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")
conn.commit()

cur.execute("CREATE TABLE tracked_events (id SERIAL, event_name TEXT, folder TEXT, latitude REAL, longitude REAL, local_authority TEXT, junior TEXT, latest_event INTEGER, guid TEXT)")
cur.execute("""CREATE TABLE locations (
    id SERIAL PRIMARY KEY, event_name TEXT NOT NULL, folder TEXT NOT NULL,
    latitude REAL NOT NULL, longitude REAL NOT NULL,
    local_authority TEXT, junior TEXT, latest_event INTEGER, guid TEXT, UNIQUE(folder)
)""")
cur.execute("""CREATE TABLE events (
    id SERIAL PRIMARY KEY, event_num INTEGER NOT NULL, location_id INTEGER REFERENCES locations(id),
    event_date DATE NOT NULL, UNIQUE(event_num, location_id)
)""")
cur.execute("""CREATE TABLE people (
    id SERIAL PRIMARY KEY, person_id INTEGER UNIQUE, person_name TEXT,
    gender TEXT, total_parkruns INTEGER DEFAULT 0, has_100_club BOOLEAN DEFAULT FALSE
)""")
cur.execute("""CREATE TABLE participation (
    event_id INTEGER REFERENCES events(id), event_num INTEGER NOT NULL,
    location_id INTEGER NOT NULL, event_date DATE NOT NULL,
    finish_position INTEGER, parkrun_id INTEGER, person_name TEXT, gender TEXT,
    finish_time TEXT, club TEXT, age_grade REAL
)""")
cur.execute("""CREATE TABLE volunteers (
    event_id INTEGER REFERENCES events(id), event_num INTEGER NOT NULL,
    location_id INTEGER NOT NULL, event_date DATE, parkrun_id INTEGER,
    person_name TEXT, volunteer_role TEXT, club TEXT
)""")
conn.commit()
print(f"[{time.time()-start_time:.1f}s] Schema created")

### PHASE 1: Load tracked_events from CSV ###
print(f"\n[{time.time()-start_time:.1f}s] Phase 1: TrackedEvents from CSV")
with open(base_dir / "TrackedEvents.csv") as f:
    csv_rows = list(csv.DictReader(f))

for row in csv_rows:
    lat = float(str(row.get("Latitude", ""))) if str(row.get("Latitude", "")).strip() not in ('None', '') else None
    lon = float(str(row.get("Longitude", ""))) if str(row.get("Longitude", "")).strip() not in ('None', '') else None
    le_str = str(row.get("LatestEventNumber", "")).replace(",", "").strip()
    latest = int(le_str) if le_str.isdigit() else None
    cur.execute("INSERT INTO tracked_events (event_name, folder, latitude, longitude, local_authority, junior, latest_event, guid) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (row["Title"], row["folder"], lat, lon, row.get("Local Authoritie"), row.get("Junior","5k"), latest, row["GUID"]))
conn.commit()
print(f"Loaded {len(csv_rows)} rows")

# Build folder → location_id mapping
cur.execute("SELECT id, folder FROM locations ORDER BY id")
folder_map = {}
for loc_id, folder in cur.fetchall():
    folder_map[folder.lower()] = loc_id
    folder_map[folder.replace(' ', '').lower()] = loc_id
    # Also try replacing spaces with hyphens
    folder_map[folder.replace(' ', '-').lower()] = loc_id
    folder_map[folder.replace('-', ' ').lower()] = loc_id
print(f"Folder map: {len(folder_map)} keys")

### PHASE 2: Event dates from history ###
print(f"\n[{time.time()-start_time:.1f}s] Phase 2: Event dates")
event_dates = {}
for hf in sorted(raw2_dir.glob("*-event_history.xlsx")):
    wb = openpyxl.load_workbook(hf, data_only=True)
    ws = wb.active
    loc_folder = hf.stem.replace("-event_history", "")
    loc_id = folder_map.get(loc_folder.lower(), None)
    if loc_id is None:
        for fl, lid in folder_map.items():
            if fl.replace(' ', '') == loc_folder.lower().replace(' ', ''):
                loc_id = lid
                break
    if loc_id is None:
        continue
    
    for row in ws.iter_rows(values_only=True):
        e_num = row[0]
        e_date_s = str(row[1]).strip().split('\n')[0].strip() if row[1] else None
        if not e_num or not e_date_s:
            continue
        m = re.match(r'(\d{2})/(\d{2})/(\d{4})', e_date_s)
        if m:
            e_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            key = (int(e_num), loc_id)
            event_dates[key] = e_date
print(f"Event dates: {len(event_dates)}")

### PHASE 3: Events & participation ###
print(f"\n[{time.time()-start_time:.1f}s] Phase 3: Events & participation")
event_files = sorted(raw2_dir.glob("*-Event-*.xlsx"))
total_participation = 0
people_dict = {}

for ef in event_files:
    # Filename format: "Denton Dene-Event-001.xlsx"
    match = re.search(r'Event-(\d+)\.xlsx$', ef.stem)
    if not match:
        continue
    event_num = int(match.group(1))
    
    # Get location
    loc_folder = ef.stem.split('-Event-')[0]
    loc_id = folder_map.get(loc_folder.lower(), None)
    if loc_id is None:
        for fl, lid in folder_map.items():
            if fl.replace(' ', '') == loc_folder.lower().replace(' ', ''):
                loc_id = lid
                break
    if loc_id is None:
        print(f"  WARNING: no location for {ef.name}")
        continue
    
    # Get date
    event_date = event_dates.get((event_num, loc_id))
    if not event_date:
        print(f"  WARNING: no date for {ef.name}")
        continue
    
    # Insert event
    cur.execute("""INSERT INTO events (event_num, location_id, event_date)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (event_num, location_id) DO UPDATE SET event_date=EXCLUDED.event_date
                   RETURNING id""", (event_num, loc_id, event_date))
    event_id = cur.fetchone()[0]
    
    # Read participation
    wb = openpyxl.load_workbook(ef, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    
    if not rows or len(rows) < 2:
        continue
    
    # Skip header row
    for row in rows[1:]:
        if not row or len(row) < 11:
            continue
        
        parkrun_id = None
        m2 = re.search(r'/parkrunner/(\d+)', str(row[3]) if row[3] else "")
        if m2:
            parkrun_id = int(m2.group(1))
        
        gender = str(row[5]).strip().upper() if row[5] is not None and str(row[5]).strip() else None
        if gender in ("MALE", "M"): gender = "M"
        elif gender in ("FEMALE", "F"): gender = "F"
        
        club = str(row[9]).strip() if row[9] is not None and str(row[9]).strip() else None
        finish_time = str(row[10]).strip() if row[10] is not None else None
        
        cur.execute("""INSERT INTO participation 
                       (event_id, event_num, location_id, event_date, finish_position, parkrun_id, person_name, gender, finish_time, club)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (event_id, event_num, loc_id, event_date, row[1], parkrun_id, str(row[2]).strip() if row[2] else None, gender, finish_time, club))
        
        total_participation += 1
        
        # Track unique people
        if parkrun_id and parkrun_id not in people_dict:
            people_dict[parkrun_id] = {'name': str(row[2]).strip() if row[2] else None, 'gender': gender}
    
    if total_participation % 50000 == 0:
        conn.commit()
        print(f"  {total_participation:,} participation rows")

conn.commit()
cur.execute("SELECT count(*) FROM events")
n_events = cur.fetchone()[0]
print(f"Events: {n_events} | Participation: {total_participation:,}")

### PHASE 4: Volunteers ###
print(f"\n[{time.time()-start_time:.1f}s] Phase 4: Volunteers")
vol_files = sorted(raw2_dir.glob("*-Volunteers-*.xlsx"))
total_vols = 0

for vf in vol_files:
    match = re.search(r'Volunteers-(\d+)\.xlsx$', vf.stem)
    if not match:
        continue
    event_num = int(match.group(1))
    
    loc_folder = vf.stem.split('-Volunteers-')[0]
    loc_id = folder_map.get(loc_folder.lower(), None)
    if loc_id is None:
        for fl, lid in folder_map.items():
            if fl.replace(' ', '') == loc_folder.lower().replace(' ', ''):
                loc_id = lid
                break
    if loc_id is None:
        continue
    
    # Get event_id
    eid = None
    cur.execute("SELECT id FROM events WHERE event_num=%s AND location_id=%s", (event_num, loc_id))
    r = cur.fetchone()
    if r:
        eid = r[0]
    else:
        continue
    
    wb = openpyxl.load_workbook(vf, data_only=True)
    ws = wb.active
    vb_rows = list(ws.iter_rows(values_only=True))
    
    # Skip header
    for row in vb_rows[1:]:
        if not row or not str(row[0]).strip():
            continue
        
        name = str(row[0]).strip()
        pid = None
        m2 = re.search(r'/parkrunner/(\d+)', str(row[1]) if row[1] else "")
        if m2: pid = int(m2.group(1))
        
        role = str(row[3]).strip().split('\n')[0].strip() if row[3] is not None and str(row[3]).strip() else None
        club = str(row[4]).strip() if row[4] is not None and str(row[4]).strip() else None
        
        # Get event_date
        edate = None
        cur2 = conn.cursor()  # use separate cursor for sub-select
        cur.execute("SELECT event_date FROM events WHERE id=%s", (eid,))
        edate_row = cur.fetchone()
        if edate_row:
            edate = edate_row[0]
        
        cur.execute("""INSERT INTO volunteers (event_id, event_num, location_id, event_date, parkrun_id, person_name, volunteer_role, club)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (eid, event_num, loc_id, edate, pid, name, role, club))
        total_vols += 1
        
        if total_vols % 50000 == 0:
            conn.commit()
            print(f"  {total_vols:,} volunteers")

conn.commit()
print(f"Volunteers: {total_vols}")

### PHASE 5: People ###
print(f"\n[{time.time()-start_time:.1f}s] Phase 5: People")

# Insert people from participation
cur.execute("""INSERT INTO people (person_id, person_name, gender)
               SELECT DISTINCT ON (parkrun_id) parkrun_id, person_name, gender
               FROM participation
               WHERE parkrun_id IS NOT NULL
               ORDER BY parkrun_id, event_date DESC""")
conn.commit()

# Update totals
cur.execute("""UPDATE people SET total_parkruns = cnt.hascnt, has_100_club = cnt.hascnt >= 100
FROM (
    SELECT parkrun_id, COUNT(*) as hascnt FROM participation WHERE finish_position IS NOT NULL GROUP BY parkrun_id
) cnt WHERE people.person_id = cnt.parkrun_id""")
conn.commit()

cur.execute("SELECT count(*), max(total_parkruns), count(*) FILTER (WHERE has_100_club) FROM people")
r = cur.fetchone()
print(f"People: {r[0]}, max parkruns: {r[1]}, 100+ club: {r[2]}")

### FINAL ###
print(f"\n{'='*60}")
print("FINAL RESULTS")
print(f"{'='*60}")
for tbl in ['tracked_events', 'events', 'people', 'participation', 'volunteers', 'locations']:
    cur.execute(f"SELECT count(*) FROM {tbl}")
    print(f"  {tbl:20} = {cur.fetchone()[0]:>10,}")
print(f"\nTotal time: {time.time()-start_time:.1f}s")
print("ETL COMPLETE!")
conn.close()
