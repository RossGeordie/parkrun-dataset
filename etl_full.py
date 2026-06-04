#!/usr/bin/env python3
"""
Parkrun Full ETL Pipeline
Loads all event results from xlsx files into event_results table,
then builds people and people_events by merging participant + volunteer data.

Table schemas:
  event_results: parkrun, event, ParkunID, Parkrunner, category, FinishPosition, gender, Age Grade, time, etc.
  volunteers: event_id, event_num, location_id, event_date, parkrun_id, person_name, volunteer_role, club
  people: id, person_id, person_name, gender, total_parkruns, has_100_club
  people_events: parkunid, event, parkun, name, category, finish_position, gender, age_grade, club, has_100_club

Usage:
  python3 etl_full.py  # Run full ETL
"""
import os
import re
import time
import logging
import psycopg2
import psycopg2.extras
from pathlib import Path
from datetime import datetime, date
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('parkrun-etl')

CONFIG = {
    'host': '10.21.63.200',
    'port': 5432,
    'dbname': 'parkrun',
    'user': 'postgres',
    'password': 'TempPass123!'
}

RAW2 = Path('/home/oc/Documents/Parkrun/Raw2')


def clean_cell(raw):
    """Remove _x000D_ corruption from Power BI exports."""
    if raw is None:
        return ""
    return str(raw).replace('_x000D_', '').replace('\\n', '').replace('\\r', '').strip()


def extract_parkun_id(url: str) -> Optional[int]:
    """Extract numeric parkunID from parkrun URL."""
    if not url:
        return None
    m = re.search(r'/parkrunner/(\d+)', url)
    return int(m.group(1)) if m else None


def parse_time_to_minutes(time_str: str):
    """Parse 'HH:MM:SS' -> (formatted_str, total_minutes)."""
    if not time_str:
        return "", 0
    parts = str(time_str).split(':')
    if len(parts) >= 3:
        try:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            total = h * 60 + m
            return f"{total}:{s:02d}", total
        except ValueError:
            pass
    return str(time_str), 0


def parse_age_grade_pct(text: str) -> float:
    """Extract number from '68.56% age grade'."""
    if not text:
        return 0.0
    m = re.search(r'([\d.]+)%', text)
    return float(m.group(1)) if m else 0.0


def extract_event_info(filepath: Path):
    """(parkrun_name, event_num, type) from filename."""
    name = filepath.name
    event_m = re.match(r'^(.+)-Event-(\d+)\.xlsx$', name)
    if event_m:
        return event_m.group(1).strip(), int(event_m.group(2)), 'event'
    vol_m = re.match(r'^(.+)-Volunteers-(\d+)\.xlsx$', name)
    if vol_m:
        return vol_m.group(1).strip(), int(vol_m.group(2)), 'volunteer'
    return "", 0, ""


def build_person_id_map(conn):
    """Build a map from parkrun.org.uk/parkrunner/PID to local person id."""
    # First, find people by their parkrun profile URL
    cur = conn.cursor()
    
    # Get all person_ids that have a link/reference to parkrun.org.uk
    cur.execute("SELECT person_id FROM people WHERE person_id > 0 LIMIT 100000")
    person_ids = [r[0] for r in cur.fetchall()]
    
    return {pid: pid for pid in person_ids}


def load_event_file(filepath: Path, conn, person_map: dict):
    """Load single event xlsx into event_results. Returns record count."""
    import openpyxl
    
    parkrun, event_num, _ = extract_event_info(filepath)
    if not parkrun or event_num == 0:
        return 0
    
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    
    if len(rows) < 2:
        wb.close()
        return 0
    
    # Extract fields by column position (matching Power BI export structure)
    participants = []
    
    for row in rows[1:]:  # skip headers
        # Pad row to 12 cols to handle Power BI's variable column counts
        row_list = list(row) if row else []
        while len(row_list) < 12:
            row_list.append(None)
        row = tuple(row_list)
        
        # Don't skip rows with empty category (e.g. "Unknown" rows)
        if not any(row):
            continue
        
        # Handle rows where category might be None/empty but we still have valid data
        # Some rows start at col 1 (Unknown entries)
        category = str(row[0]).strip() if len(row) > 0 else ""
        if not category:
            continue
        
        # Col 1: Finish Position
        position = int(row[1]) if len(row) > 1 and row[1] else 0
        
        # Col 2: Parkrunner Name
        name = str(row[2]).strip() if len(row) > 2 and row[2] else ""
        if not name:
            continue
        
        # Col 3: Parkrun URL (extract parkun_id)
        url = str(row[3]).strip() if len(row) > 3 and row[3] else ""
        parkun_id = extract_parkun_id(url)
        
        # Col 4: Parkun count text (e.g. "346 finishes|v250")
        parkun_text = str(row[4]) if len(row) > 4 and row[4] else "0"
        total_parkuns = 0
        hundred_club = 0
        if 'finishes' in str(parkun_text).lower():
            m = re.search(r'(\d+)\s+finishes', parkun_text)
            if m:
                total_parkuns = int(m.group(1))
        if 'v100' in str(parkun_text).lower():
            hundred_club = 1
        
        # Col 5: Gender
        gender = str(row[5]).strip() if len(row) > 5 else ""
        
        # Col 6: Age Grade numeric (e.g. 67.0)
        age_grade_raw = float(row[6]) if len(row) > 6 and row[6] else 0.0
        
        # Col 8: "X% age grade" text
        age_grade_pct = parse_age_grade_pct(str(row[8]) if len(row) > 8 else "")
        
        # Col 7: Date of Birth (Power BI datetime string)
        dob = None
        if len(row) > 7 and row[7]:
            try:
                if hasattr(row[7], 'date'):
                    dob = row[7].date()
                elif isinstance(row[7], str) and 'T' in row[7]:
                    dob = datetime.fromisoformat(row[7]).date()
                else:
                    dob = date(year=2000, month=1, day=1)  # placeholder
            except (ValueError, TypeError):
                pass
        
        # Col 9: Club
        club = str(row[9]).strip() if len(row) > 9 and row[9] else ""
        
        # Col 10: Finish Time
        time_str = str(row[10]).strip() if len(row) > 10 and row[10] else ""
        time_formatted, finish_min = parse_time_to_minutes(time_str)
        
        # Col 11: Note (First Timer! / PB text)
        note_raw = str(row[11]).strip() if len(row) > 11 else ""
        first_timer = 1 if note_raw == "First Timer!" else 0
        pb_text = note_raw if note_raw and note_raw != "First Timer!" else None
        
        participants.append((
            parkrun, event_num, 
            f"{parkun_id}" if parkun_id else None,  # ParkunID as text per existing schema
            name, category, position, gender,
            age_grade_raw, club, total_parkuns, hundred_club,
            dob, first_timer if first_timer else None, 
            pb_text, time_formatted,
            datetime.now()  # loaded_at
        ))
    
    if participants:
        cur = conn.cursor()
        insert_sql = """
            INSERT INTO event_results 
            (parkrun, event, ParkunID, Parkrunner, category, FinishPosition, gender,
             "Age Grade", Total Finishers, "100 Club", club, dob, "First Timer", pb, "Time", loaded_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cur.executemany(insert_sql, participants)
        conn.commit()
        logger.info(f"  Loaded {len(participants)}: {filepath.name}")
    
    wb.close()
    return len(participants)


def build_people_from_participants(conn):
    """Build people table from event_results (participants only - parkun_id mapping)."""
    cur = conn.cursor()
    
    # Clear existing people table (start fresh)
    cur.execute("TRUNCATE TABLE people CASCADE")
    
    # Get distinct parkrun_ids with their participant data
    cur.execute("""
        INSERT INTO people (person_id, person_name, gender, total_parkruns, has_100_club)
        SELECT DISTINCT ON (ParkunID::integer)
            ParkunID::integer,
            Parkrunner,
            gender,
            CASE WHEN "Total Finishers" > 0 THEN "Total Finishers" ELSE 0 END,
            CASE WHEN "100 Club" > 0 THEN true ELSE false END
        FROM event_results
        WHERE ParkunID IS NOT NULL
        AND ParkunID ~ '^\d+$'
        ORDER BY ParkunID::integer
    """)
    
    conn.commit()
    
    cur.execute("SELECT COUNT(*) FROM people")
    count = cur.fetchone()[0]
    logger.info(f"Built people table from participants: {count} unique persons")
    return count


def build_people_events(conn):
    """Build people_events from participants and volunteers."""
    cur = conn.cursor()
    
    # Clear existing
    cur.execute("TRUNCATE TABLE people_events CASCADE")
    
    # Participants
    cur.execute("""
        INSERT INTO people_events (parkunid, event, parkun, name, category, finish_position,
                                   gender, age_grade, club, has_100_club, loaded_at)
        SELECT DISTINCT ON (ParkunID::integer, event)
            ParkunID::integer,
            event,
            Parkrunner,
            Parkrunner,
            category,
            FinishPosition,
            gender,
            "Age Grade",
            club,
            CASE WHEN "100 Club" > 0 THEN true ELSE false END,
            now()
        FROM event_results
        WHERE ParkunID IS NOT NULL
        AND ParkunID ~ '^\d+$'
        ORDER BY ParkunID::integer, event, loaded_at DESC
    """)
    
    # Add event references
    # We need to map parkrun name to location_id using tracked_events
    cur.execute("""
        UPDATE people_events pe
        SET event = e.id
        FROM tracked_events e
        WHERE e.folder = pe.parkun
        AND pe.event IS NOT NULL  -- ensure event is an int
    """)
    
    conn.commit()
    
    cur.execute("SELECT COUNT(*) FROM people_events")
    count = cur.fetchone()[0]
    logger.info(f"Built people_events: {count} records (participants)")
    
    cur.execute("SELECT COUNT(DISTINCT parkunid) FROM people_events WHERE parkunid > 0")
    unique_people = cur.fetchone()[0]
    logger.info(f"Unique people: {unique_people:,}")
    
    return count


def get_event_files():
    """Get sorted list of event xlsx files."""
    if not RAW2.exists():
        return [], []
    
    all_files = sorted([f for f in RAW2.iterdir() if f.suffix == '.xlsx'])
    event_files = [f for f in all_files if 'event' in f.name.lower()]
    vol_files = [f for f in all_files if 'volunteer' in f.name.lower()]
    
    return event_files, vol_files


def run_etl():
    """Run the full ETL pipeline."""
    logger.info("=== Parkrun Full ETL Pipeline ===")
    
    # Phase 1: Load event results
    event_files, vol_files = get_event_files()
    logger.info(f"\nFound {len(event_files)} event files, {len(vol_files)} volunteer files")
    
    conn = psycopg2.connect(**CONFIG)
    
    try:
        # Load all event files (bulk insert)
        logger.info("\nPhase 1: Loading event results from xlsx files...")
        total_loaded = 0
        start_time = time.time()
        
        for i, fp in enumerate(event_files):
            try:
                loaded = load_event_file(fp, conn, {})
                total_loaded += loaded
            except Exception as e:
                logger.error(f"Failed {fp.name}: {e}")
            except KeyboardInterrupt:
                logger.error("Interrupted!")
                break
            
            if (i + 1) % 1000 == 0:
                elapsed = time.time() - start_time
                logger.info(f"Progress: {i+1}/{len(event_files)} files, {total_loaded:,} records ({elapsed:.0f}s)")
        
        logger.info(f"\nPhase 1 complete: {total_loaded:,} records in {time.time()-start_time:.0f}s")
        
        # Phase 2: Build people table from participants
        logger.info("\nPhase 2: Building people table...")
        people_count = build_people_from_participants(conn)
        
        # Phase 3: Build participants_events
        logger.info("\nPhase 3: Building participants_events...")
        pe_count = build_people_events(conn)
        
        # Phase 4: Add event references
        logger.info("\nPhase 4: Adding event references...")
        cur = conn.cursor()
        
        # Map parkrun names to event_ids from tracked_events
        cur.execute("SELECT id, folder FROM tracked_events")
        events = cur.fetchall()
        
        # Update event_ids in people_events
        cur.execute("""
            UPDATE people_events pe
            SET event = e.id
            FROM tracked_events e
            WHERE e.folder = pe.parkun
            AND pe.event IS NULL  -- only update null events
        """)
        
        conn.commit()
        
        # Phase 5: Report final stats
        logger.info("\n=== FINAL DB STATS ===")
        cur = conn.cursor()
        for table in ['event_results', 'people', 'people_events']:
            cur.execute(f'SELECT COUNT(*) FROM {table}')
            count = cur.fetchone()[0]
            logger.info(f"  {table}: {count:>10,}")
        
        # Show event distribution
        logger.info("\n  Event distribution (top 10):")
        cur.execute("""
            SELECT parkun, count(*) as records
            FROM event_results GROUP BY parkun ORDER BY records DESC LIMIT 10
        """)
        for r in cur.fetchall():
            logger.info(f"    {r[0]:30} = {r[1]:>10,}")
        
    finally:
        conn.close()
    
    logger.info("\n=== ETL Pipeline Complete ===")


if __name__ == '__main__':
    run_etl()
