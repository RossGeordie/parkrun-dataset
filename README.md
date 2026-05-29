# Parkrun ETL Pipeline

Extract, transform, and load parkrun results data into PostgreSQL.

## Data Sources

- **TrackedEvents.csv**: CSV of all tracked parkrun locations (33 events)
- **Raw2/**: Directory of xlsx files containing:
  - `{Event Name}-Event-{NNN}.xlsx` - Event results (participation data)
  - `{Event Name}-Volunteers-{NNN}.xlsx` - Volunteer rosters  
  - `{Event Name}-Event History.xlsx` - Historical event dates

## Database Schema (PostgreSQL)

### Core Tables

| Table | Description |
|-------|-------------|
| `tracked_events` | 33 tracked parkrun events |
| `locations` | Unique event locations with coordinates |
| `events` | 11,327 events with dates and location references |
| `participation` | 2.2M participation records |
| `people` | 192K unique parkrunners with counts + 100+ club status |
| `volunteers` | 41K volunteer records |

### Schema Details

```sql
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    event_num INTEGER NOT NULL,
    location_id INTEGER REFERENCES locations(id),
    event_date DATE NOT NULL,
    UNIQUE(event_num, location_id)
);

CREATE TABLE people (
    id SERIAL PRIMARY KEY,
    person_id INTEGER UNIQUE,
    person_name TEXT,
    gender CHAR(1),  -- M/F/X
    total_parkruns INTEGER DEFAULT 0,
    has_100_club BOOLEAN DEFAULT FALSE
);

CREATE TABLE participation (
    id SERIAL PRIMARY KEY,
    event_id INTEGER REFERENCES events(id),
    event_num INTEGER NOT NULL,
    location_id INTEGER NOT NULL,
    event_date DATE NOT NULL,
    finish_position INTEGER,
    parkrun_id INTEGER,
    person_name TEXT,
    gender CHAR(1),
    finish_time TEXT,
    club TEXT,
    age_grade REAL
);

CREATE TABLE volunteers (
    id SERIAL PRIMARY KEY,
    event_id INTEGER REFERENCES events(id),
    event_num INTEGER NOT NULL,
    location_id INTEGER NOT NULL,
    event_date DATE,
    parkrun_id INTEGER,
    person_name TEXT,
    volunteer_role TEXT,
    club TEXT
);
```

## Database

- **Host**: 10.21.63.200:5432
- **Database**: parkrun
- **User**: postgres (password in .pgpass)

## Usage

```bash
python3 etl_final.py  # Run full ETL pipeline
```

## Quick Queries

Get top parkrunners:
```sql
SELECT person_name, total_parkruns, gender
FROM people 
WHERE total_parkruns >= 100 
ORDER BY total_parkruns DESC 
LIMIT 10;
```

Get event by event number and location:
```sql
SELECT e.event_num, e.event_date, l.event_name, l.folder
FROM events e 
JOIN locations l ON e.location_id = l.id 
WHERE e.event_date = '2024-01-01';
```

Get participation for specific event:
```sql
SELECT person_name, finish_position, finish_time, club, age_grade
FROM participation 
WHERE event_num = 269 AND location_id = 1
ORDER BY finish_position;
```

Get volunteer count per event:
```sql
SELECT e.event_num, e.event_date, count(v.id) as volunteer_count
FROM events e
LEFT JOIN volunteers v ON v.event_id = e.id
WHERE e.event_num = 269 AND e.location_id = 1
GROUP BY e.event_num, e.event_date;
```
