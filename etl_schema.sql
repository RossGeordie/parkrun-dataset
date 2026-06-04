-- ====================================================================
-- Parkrun Analytics Database Schema (v2)
-- ====================================================================
-- Tables: event_master, volunteers, event_role, event_results, volunteer_events
-- Usage: psql -h 10.21.63.200 -U postgres -d parkrun -f etl_schema.sql
-- ====================================================================
BEGIN;

-- Drop dependent tables first
DROP TABLE IF EXISTS event_role;
DROP TABLE IF EXISTS event_results;
DROP TABLE IF EXISTS volunteer_events;
DROP TABLE IF EXISTS volunteers;
DROP TABLE IF EXISTS event_master CASCADE;

-- == EVENT MASTER - one row per specific parkrun event occurrence ==
CREATE TABLE event_master (
    event_id        SERIAL PRIMARY KEY,
    event_code      TEXT NOT NULL,       -- e.g. 'newcastle-324'
    event_name      TEXT NOT NULL,       -- display name
    event_date      DATE NOT NULL,       -- date the event occurred
    event_type      TEXT,                -- '5K', '10K', 'trail', etc.
    course_status   TEXT,                -- 'open', 'closed', etc.
    parkrun_id      INTEGER,             -- external parkrun.org ID
    UNIQUE (parkrun_id),
    UNIQUE (event_code, event_date)
);

CREATE INDEX idx_em_date ON event_master (event_date);
CREATE INDEX idx_em_code ON event_master (event_code);

-- == VOLUNTEERS - unique person rows ==
CREATE TABLE volunteers (
    volunteer_id       SERIAL PRIMARY KEY,
    parkrun_id         INTEGER NOT NULL,  -- external parkrun.org member ID
    name               TEXT NOT NULL,
    email              TEXT,
    first_volunteer_date DATE,
    last_volunteer_date  DATE,
    total_roles        INTEGER DEFAULT 0,
    UNIQUE (parkrun_id)
);

CREATE INDEX idx_vol_parkrun ON volunteers (parkrun_id);
CREATE INDEX idx_vol_name ON volunteers (name);

-- == EVENT_ROLE - mapping table (n:m) ==
CREATE TABLE event_role (
    event_role_id  SERIAL PRIMARY KEY,
    volunteer_id   INTEGER NOT NULL REFERENCES volunteers(volunteer_id),
    event_id       INTEGER NOT NULL REFERENCES event_master(event_id),
    roles          TEXT,
    event_date     DATE,
    UNIQUE (volunteer_id, event_id)
);

-- == EVENT RESULTS - one row per runner per event ==
CREATE TABLE event_results (
    result_id        SERIAL PRIMARY KEY,
    event_id         INTEGER NOT NULL REFERENCES event_master(event_id),
    parkrun_id       INTEGER,             -- external parkrun.org member ID
    name             TEXT NOT NULL,
    position         INTEGER,
    age_grade        NUMERIC(6,2),
    sex              TEXT,
    age_group        TEXT,  -- e.g. 'M35', 'F25'
    time             INTERVAL,  -- NULL for TD/no-show
    participant_count INTEGER DEFAULT 0,
    club             TEXT,
    pb_status        TEXT,  -- NULL or PB timestamp
    loaded_at        TIMESTAMP DEFAULT NOW(),
    UNIQUE (event_id, parkrun_id, name)
);

CREATE INDEX idx_er_event ON event_results (event_id);
CREATE INDEX idx_er_parkrun ON event_results (parkrun_id);
CREATE INDEX idx_er_time ON event_results (time) WHERE time IS NOT NULL;
CREATE INDEX idx_er_age_grade ON event_results (age_grade) WHERE age_grade > 0;

-- == VOLUNTEER EVENTS - contribution log ==
CREATE TABLE volunteer_events (
    volunteer_event_id  SERIAL PRIMARY KEY,
    volunteer_id        INTEGER NOT NULL REFERENCES volunteers(volunteer_id),
    event_id            INTEGER NOT NULL REFERENCES event_master(event_id),
    roles               TEXT,
    event_date          DATE,
    loaded_at           TIMESTAMP DEFAULT NOW(),
    UNIQUE (volunteer_id, event_id)
);

-- == ANALYTICS HELPERS ==
CREATE OR REPLACE FUNCTION etl_fix_volunteer_roles()
RETURNS integer AS $$
DECLARE cleaned_count integer;
BEGIN
    UPDATE event_role SET roles = REPLACE(roles, '_x000D_', '') WHERE event_role_id >= 1;
    UPDATE event_role SET roles = TRIM(roles) WHERE event_role_id >= 1;
    SELECT count(*) INTO cleaned_count FROM volunteer_events WHERE volunteer_event_id >= 1;
    RETURN cleaned_count;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION etl_count_participants()
RETURNS bigint AS $$
SELECT count(DISTINCT parkrun_id) FROM event_results;
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION etl_participants_per_event(p_event_id integer)
RETURNS TABLE(parkrun_id integer, participant_count bigint) AS $$
    SELECT parkrun_id, count(*) FROM event_results
    WHERE event_id = p_event_id GROUP BY parkrun_id;
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION etl_count_volunteers(p_event_id integer)
RETURNS integer AS $$
    SELECT count(DISTINCT volunteer_id) FROM volunteer_events WHERE event_id = p_event_id;
$$ LANGUAGE sql;

-- == DEDUPE ==
CREATE OR REPLACE FUNCTION etl_clean_people_events()
RETURNS void AS $$
BEGIN
    -- Remove event_results duplicates: keep earliest loaded_at
    DELETE FROM event_results
    WHERE ctid NOT IN (
        SELECT FIRST_VALUE(ctid) FROM event_results
        GROUP BY event_id, parkrun_id, name
    ) SORTED_LIMIT 1;

    -- Remove volunteer_events duplicates
    DELETE FROM volunteer_events
    WHERE ctid NOT IN (
        SELECT FIRST_VALUE(ctid) FROM volunteer_events
        GROUP BY volunteer_id, event_id
    ) SORTED_LIMIT 1;
END;
$$ LANGUAGE plpgsql;

COMMIT;
