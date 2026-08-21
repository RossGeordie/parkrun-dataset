-- parkrun schema (canonical) — applied by `parkrun_pipeline.py scrape --mode init`
-- Target: PostgreSQL 17, database `parkrun`, schema `parkrun`

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

CREATE INDEX IF NOT EXISTS idx_fin_park_date ON parkrun.finishers (park);

-- Convenience views (optional)
CREATE OR REPLACE VIEW parkrun.event_stats AS
SELECT e.park, e.event_no, e.event_date, e.n_finishers, e.n_volunteers,
       f.avg_time_s, f.p50_time_s
FROM parkrun.event_history e
LEFT JOIN LATERAL (
    SELECT avg(time_s) AS avg_time_s,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY time_s) AS p50_time_s
    FROM parkrun.finishers WHERE park = e.park AND event_no = e.event_no
) f ON true;

CREATE OR REPLACE VIEW parkrun.top_volunteers AS
SELECT name, parkrun_id,
       count(*) AS events_volunteered,
       max(volunteer_badge) AS volunteer_badge,
       max(finishes_badge) AS finishes_badge
FROM parkrun.volunteers
GROUP BY name, parkrun_id
ORDER BY events_volunteered DESC;

-- Registry of parkrun events (parks) to scrape
CREATE TABLE IF NOT EXISTS parkrun.parks (
    slug            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    city            TEXT,
    url             TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    last_scraped_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO parkrun.parks (slug, name, city, url) VALUES
  ('jesmonddene', 'Jesmond Dene', 'Newcastle', 'https://www.parkrun.org.uk/jesmonddene/results/'),
  ('townmoor',    'Town Moor',    'Newcastle', 'https://www.parkrun.org.uk/townmoor/results/'),
  ('leazes',      'Leazes Park',  'Newcastle',   'https://www.parkrun.org.uk/leazes/results/'),
  ('dentondene',  'Denton Dene',  'Newcastle',  'https://www.parkrun.org.uk/dentondene/results/')
ON CONFLICT (slug) DO NOTHING;
