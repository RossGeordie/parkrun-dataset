#!/usr/bin/env python3
"""Complete missing phases only: volunteers + people."""
import openpyxl, re, time, glob
from pathlib import Path

START = time.time()
def log(msg): print(f"[{time.time()-START:.1f}s] {msg}", flush=True)

import psycopg2
conn = psycopg2.connect(host='10.21.63.200', dbname='parkrun', user='postgres', password='TempPass123!')
cur = conn.cursor()

# Current state check
log("Current state:")
for tbl in ['tracked_events', 'events', 'participation', 'volunteers', 'people', 'locations']:
    cur.execute(f'SELECT count(*) FROM {tbl}')
    log(f'  {tbl:20} = {cur.fetchone()[0]:>10,}')

# Build location mapping (need folder→id from locations)
cur.execute('SELECT id, folder FROM locations ORDER BY id')
folder_map = {}
for loc_id, folder in cur.fetchall():
    folder_map[folder.lower()] = loc_id
    folder_map[folder.replace(' ', '').lower()] = loc_id
    folder_map[folder.replace('-', ' ').lower()] = loc_id
log(f'Folder map: {len(folder_map)} entries')

# Build event_id map from events table
cur.execute('SELECT id, event_num, location_id FROM events WHERE location_id IS NOT NULL')
evt_map = {}
for eid, enum, loc_id in cur.fetchall():
    evt_map[(enum, loc_id)] = eid
log(f'Event ID map: {len(evt_map)} entries')

# Phase 1: Volunteers
log('\nPhase 1: Volunteers')
raw2 = Path('/home/oc/Documents/Parkrun/Raw2')
vol_files = sorted(glob.glob(str(raw2 / '*-Volunteers-*.xlsx')))
log(f'Volunteer files: {len(vol_files)}')

vol_count = 0
vol_proc = 0
vol_batch = []

for i, vf in enumerate(vol_files):
    m = re.search(r'Volunteers-(\d+)\.xlsx$', Path(vf).name)
    if not m:
        # Skip files that don't match pattern (e.g., history files)
        if vol_proc % 5000 == 0:
            log(f'  Skipped (non-matching): {Path(vf).name}')
        continue
    
    event_num = int(m.group(1))
    loc_folder = Path(vf).stem.split('-Volunteers-')[0]
    
    loc_id = folder_map.get(loc_folder.lower())
    if not loc_id:
        for fl, lid in folder_map.items():
            if fl.replace(' ', '') == loc_folder.lower().replace(' ', ''):
                loc_id = lid
                break
    if not loc_id:
        continue
    
    eid = evt_map.get((event_num, loc_id))
    if not eid:
        continue
    
    event_date = None
    cur.execute('SELECT event_date FROM events WHERE id = %s', (eid,))
    r = cur.fetchone()
    if r:
        event_date = r[0]
    
    wb = openpyxl.load_workbook(vf, data_only=True)
    ws = wb.active
    vb_rows = list(ws.iter_rows(values_only=True))
    
    for row in vb_rows:
        if not row or not row[0] or not str(row[0]).strip():
            continue
        
        name = str(row[0]).strip()
        parkrun_id = None
        if row[1] and str(row[1]).strip():
            m2 = re.search(r'/parkrunner/(\d+)', str(row[1]))
            if m2:
                parkrun_id = int(m2.group(1))
        
        role = None
        if row[3] and str(row[3]).strip():
            role = str(row[3]).strip().split('\n')[0].strip()
        
        club = str(row[4]).strip() if row[4] and str(row[4]).strip() else None
        
        vol_batch.append((eid, event_num, loc_id, event_date, parkrun_id, name, role, club))
        
        if len(vol_batch) >= 10000:
            cur.executemany("""INSERT INTO volunteers (
                event_id, event_num, location_id, event_date,
                parkrun_id, person_name, volunteer_role, club
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", vol_batch)
            conn.commit()
            vol_count += len(vol_batch)
            vol_batch = []
    
    vol_proc += 1
    
    if vol_proc % 1000 == 0:
        log(f'  {vol_proc}/{len(vol_files)} files, {vol_count:,} volunteers')

# Flush remaining
if vol_batch:
    cur.executemany("""INSERT INTO volunteers (
        event_id, event_num, location_id, event_date,
        parkrun_id, person_name, volunteer_role, club
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", vol_batch)
    conn.commit()
    vol_count += len(vol_batch)
    vol_batch = []

conn.commit()
log(f'Volunteers: {vol_count} rows processed')
cur.execute('SELECT count(*) FROM volunteers')
log(f'Volunteers in DB: {cur.fetchone()[0]:,}')

# Phase 2: People from participation
log('\nPhase 2: People')
cur.execute('DELETE FROM people')
conn.commit()

# Insert distinct people, grouped by most recent entry
cur.execute("""INSERT INTO people (person_id, person_name, gender)
    SELECT DISTINCT ON (parkrun_id) parkrun_id, person_name, gender
    FROM participation
    WHERE parkrun_id IS NOT NULL
    ORDER BY parkrun_id, event_date DESC""")
conn.commit()
log(f'People inserted: {cur.rowcount}')

# Update totals
cur.execute("""UPDATE people SET total_parkruns = cnt.cnt, has_100_club = cnt.cnt >= 100
FROM (
    SELECT parkrun_id, COUNT(*) as cnt
    FROM participation
    WHERE finish_position IS NOT NULL
    GROUP BY parkrun_id
) cnt WHERE people.person_id = cnt.parkrun_id""")
conn.commit()
log(f'People totals updated')

# Final
log('\nFINAL:')
for tbl in ['tracked_events', 'events', 'people', 'participation', 'volunteers', 'locations']:
    cur.execute(f'SELECT count(*) FROM {tbl}')
    log(f'  {tbl:20} = {cur.fetchone()[0]:>10,}')

cur.execute('SELECT max(total_parkruns), min(total_parkruns), count(*) FILTER (WHERE has_100_club) FROM people')
r = cur.fetchone()
log(f'Max parkruns: {r[0]}, Min parkruns: {r[1]}, 100+ club: {r[2]}')

log(f'\nDone in {time.time()-START:.1f}s')
conn.close()
