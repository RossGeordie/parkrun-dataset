#!/usr/bin/env python3
"""Simple finish: people + volunteers. No complex dict handling."""
import psycopg2, re, time, openpyxl
from pathlib import Path

T0 = time.time()
def log(m): print(f"[{time.time()-T0:.1f}s] {m}", flush=True)

log("Starting people extraction...")
conn = psycopg2.connect(host="10.21.63.200", dbname="parkrun", user="postgres", password="TempPass123!")
cur = conn.cursor()

# Count existing people
cur.execute("SELECT count(*) FROM people")
existing_people = cur.fetchone()[0]
log(f"Existing people count: {existing_people}")

# Clear and rebuild people
cur.execute("TRUNCATE people CASCADE")
conn.commit()
log("People table truncated")

# Get all distinct parkrunners
log("Extracting distinct parkrunners...")
cur.execute("""
    SELECT DISTINCT parkrun_id, person_name, gender 
    FROM participation 
    WHERE parkrun_id IS NOT NULL 
      AND person_name IS NOT NULL
      AND person_name != ''
""")
runners = cur.fetchall()
log(f"Got {len(runners)} distinct parkrunners")

# Simple dict approach
people = {}
for pid, name, gender in runners:
    pid = int(pid)
    if pid not in people:
        people[pid] = {
            'name': name,
            'gender': gender[:1].upper() if gender and gender[:1].upper() in ('M', 'F', 'X') else None,
        }

log(f"Built people dict with {len(people)} entries")

# Insert
log("Inserting people...")
inserted = 0
for pid, info in people.items():
    has_100 = False  # We'll compute this later - just store basics first
    cur.execute("SELECT COUNT(*) FROM people WHERE person_id = %s", (pid,))
    if cur.fetchone()[0] == 0:
        cur.execute("""INSERT INTO people (person_id, person_name, gender, has_100_club) 
                       VALUES (%s,%s,%s,%s)""",
                    (pid, info['name'], info['gender'], has_100))
        inserted += 1
        if inserted % 50000 == 0:
            conn.commit()

conn.commit()
cur.execute("SELECT count(*) FROM people")
log(f"People: {cur.fetchone()[0]} total after insert")

# Compute totals
log("Computing person totals...")
for pid in range(1, 999999):  # Incremental
    try:
        cur.execute("SELECT count(*) FROM participation WHERE parkrun_id = %s AND finish_position IS NOT NULL", (pid,))
        count = cur.fetchone()[0]
        if count > 0:
            cur.execute("UPDATE people SET total_parkruns = %s, has_100_club = %s WHERE person_id = %s", (count, count >= 100, pid))
    except:
        break

conn.commit()
cur.execute("SELECT MAX(total_parkruns), MIN(total_parkruns) FROM people")
log(f"Person count range: {cur.fetchone()[0]} - {cur.fetchone()[1]}")

# Volunteers
log("\nLoading volunteers...")
vol_files = sorted(Path("/home/oc/Documents/Parkrun/Raw2").glob("*-Volunteers-*.xlsx"))
log(f"  Found {len(vol_files)} volunteer files")

# Get event mapping
cur.execute("SELECT id, event_num, location_id FROM events")
evt_map = {}
for row in cur.fetchall():
    evt_map[(row[1], row[2])] = row[0]
log(f"  Event ID map: {len(evt_map)} entries")

# Get folder mapping
cur.execute("SELECT folder FROM locations")
folders = [r[0] for r in cur.fetchall()]
folder_set = set(f.lower() for f in folders)
log(f"  Locations with folders: {len(folders)}")

vol_count = 0
for i, vf in enumerate(vol_files):
    match = re.search(r'Volunteers-(\d+)', vf.stem)
    if not match:
        log(f"  Skipping {vf.stem}: no match")
        continue
    event_num = int(match.group(1))
    
    # Find location
    loc_folder = vf.stem.split('-Volunteers-')[0].lower()
    location_id = 0
    for fid, fld in cur.execute("SELECT id, folder FROM locations"):
        if fld.lower() == loc_folder:
            location_id = fid
            break
    
    if location_id == 0:
        log(f"  Warning: no location for {vf.stem}")
        continue
    
    eid = evt_map.get((event_num, location_id))
    if not eid:
        log(f"  Warning: no event for {vf.stem}")
        continue
    
    wb = openpyxl.load_workbook(vf, data_only=True)
    ws = wb.active
    vb_rows = list(ws.iter_rows(values_only=True))
    
    file_vols = 0
    for row in vb_rows:
        if not row or not str(row[0]).strip():
            continue
        name = str(row[0]).strip()
        parkrun_id = None
        if row[1]:
            m2 = re.search(r'/parkrunner/(\d+)', str(row[1]))
            parkrun_id = int(m2.group(1)) if m2 else None
        role = None
        if row[3]:
            for r2 in str(row[3]).split('\n'):
                r2 = r2.strip()
                if r2:
                    role = r2
                    break
        club = str(row[4]).strip() if row[4] and str(row[4]).strip() else None
        
        cur.execute("""INSERT INTO volunteers (event_id, event_num, location_id, event_date,
                       parkrun_id, person_name, volunteer_role, club)
                       VALUES ((SELECT event_id FROM events WHERE id = %s LIMIT 1),
                               %s, %s, (SELECT event_date FROM events WHERE id = %s LIMIT 1),
                               %s, %s, %s, %s)""",
                    (eid, event_num, location_id, eid, parkrun_id, name, role, club))
        vol_count += 1
        file_vols += 1
    
    if file_vols > 0:
        conn.commit()
        log(f"  File {i+1}/{len(vol_files)}: {file_vols} volunteers")

conn.commit()
cur.execute("SELECT count(*) FROM volunteers")
log(f"\nVolunteers: {cur.fetchone()[0]} total")

conn.close()

# Final check
log("\n=== FINAL COUNTS ===")
for tbl in ['tracked_events', 'events', 'people', 'participation', 'volunteers']:
    conn = psycopg2.connect(host="10.21.63.200", dbname="parkrun", user="postgres", password="TempPass123!")
    cur2 = conn.cursor()
    cur2.execute(f"SELECT count(*) FROM {tbl}")
    print(f"  {tbl:20} = {cur2.fetchone()[0]:>10,}")
    conn.close()

log(f"\nDONE in {time.time()-T0:.1f}s")
