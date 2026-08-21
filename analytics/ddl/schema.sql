-- ============================================================================
-- analytics star schema — parkrun (Newcastle + future parks)
-- Mirrors TMDL star: fact_run / fact_volunteer -> dim_person, -> dim_park,
--                    -> calendar; rollup_person_park = People_Events;
--                    rollup_event = Events.
-- Parkrun IDs are surrogate keys (parkrun_id, park+event_no).
-- ============================================================================

create schema if not exists analytics;
grant usage   on schema analytics to reader;
grant create  on schema analytics to scraper;

-- ---------------------------------------------------------------------------
-- dim_park — parks, LA, geography. TABLE (CSV + API seeded), so new parks
-- are added as rows; la_scope gates which parks enter the Newcastle report.
-- ---------------------------------------------------------------------------
drop table if exists analytics.dim_park;
create table analytics.dim_park (
  park              text primary key references parkrun.parks(slug),
  name              text not null,
  city              text,
  local_authority   text not null,
  latlon            text,          -- API string e.g. 'Lat: 54.96338 Long: -1.61815'
  lat_real          double precision,
  long_real         double precision,
  is_junior         boolean default false,
  web_url           text,
  la_scope          boolean default true
);

insert into analytics.dim_park
  (park, name, city, local_authority, latlon, lat_real, long_real,
   is_junior, web_url, la_scope)
values
  ('jesmonddene', 'Jesmond Dene', 'Newcastle upon Tyne', 'Newcastle',
   'Lat: 54.96338 Long: -1.61815', 54.96338, -1.61815, false,
   'https://www.parkrun.org.uk/jesmonddene/results/', true),
  ('dentondene',  'Denton Dene',  'Newcastle upon Tyne', 'Newcastle',
   'Lat: 54.97173 Long: -1.57812', 54.97173, -1.57812, false,
   'https://www.parkrun.org.uk/dentondene/results/', true),
  ('leazes',      'Leazes Park',  'Newcastle upon Tyne', 'Newcastle',
   'Lat: 54.96198 Long: -1.60999', 54.96198, -1.60999, false,
   'https://www.parkrun.org.uk/leazes/results/', true),
  ('townmoor',    'Town Moor',    'Newcastle upon Tyne', 'Newcastle',
   'Lat: 54.96567 Long: -1.60490', 54.96567, -1.60490, false,
   'https://www.parkrun.org.uk/townmoor/results/', true)
on conflict (park) do update set
  local_authority = excluded.local_authority,
  latlon          = excluded.latlon,
  lat_real        = excluded.lat_real,
  long_real       = excluded.long_real,
  is_junior       = excluded.is_junior,
  web_url         = excluded.web_url
;
grant select on analytics.dim_park to reader;

-- ---------------------------------------------------------------------------
-- calendar — 1 row per date (2000 → 2099)
-- ---------------------------------------------------------------------------
drop materialized view if exists analytics.calendar;
create materialized view analytics.calendar as
select
  d::date                                                    as date,
  extract(year    from d)                                     as year,
  extract(month   from d)                                     as month,
  extract(day     from d)                                     as day,
  extract(quarter from d)                                     as quarter,
  extract(isodow  from d)                                     as dayofweek,  -- 1=Mon
  to_char(d, 'IYYY')                                          as iso_year,
  to_char(d, 'IW')                                            as iso_week,
  to_char(d, 'DY')                                            as month_name
from generate_series(date '2000-01-01', date '2099-12-31', interval '1 day') d
with no data;
refresh materialized view analytics.calendar;
create unique index calendar_pkey on analytics.calendar (date);
grant select on analytics.calendar to reader;

-- ---------------------------------------------------------------------------
-- dim_person — canonical person master (runners and/or volunteers)
-- ---------------------------------------------------------------------------
drop materialized view if exists analytics.dim_person;
create materialized view analytics.dim_person as
with s as (
  select parkrun_id, lower(name) as name, park,
         nullif(trim(gender), '') as gender,
         nullif(trim(coalesce(nullif(trim(club), ''), 'None')), '') as club,
         'run' as src
  from parkrun.finishers
  where parkrun_id is not null and parkrun_id <> ''
  union all
  select parkrun_id, lower(name), park, null,
         nullif(trim(coalesce(nullif(trim(club), ''), 'None')), ''),
         'vol'
  from parkrun.volunteers
  where parkrun_id is not null and parkrun_id <> ''
)
select
  parkrun_id,
  min(coalesce(name, ''))                     as name,
  coalesce(min(gender) filter (where gender is not null),
           'Unknown')                         as gender,
  coalesce(min(club)   filter (where club   is not null),
           'Uncategorised')                   as club,
  count(distinct case when src = 'run' then park end) as n_parks_run,
  count(distinct case when src = 'vol' then park end) as n_parks_vol,
  bool_or(src = 'run')                        as is_runner,
  bool_or(src = 'vol')                        as is_volunteer
from s
group by parkrun_id
with no data;
create unique index dim_person_pkey on analytics.dim_person (parkrun_id);
grant select on analytics.dim_person to reader;

-- ---------------------------------------------------------------------------
-- fact_run — 1 row per finisher appearance (person x event x position)
-- ---------------------------------------------------------------------------
drop materialized view if exists analytics.fact_run;
create materialized view analytics.fact_run as
select
  f.park,                                                   -- dim_park.park
  f.event_no,                                               -- event key (with park)
  f.position,                                               -- finish position
  f.parkrun_id,                                             -- dim_person.parkrun_id
  lower(f.name)                    as name,
  f.time_s,
  f.age_group,
  f.age_grade,
  f.result_note,
  f.n_finishes,
  f.finishes_badge,
  f.volunteer_badge,
  nullif(trim(coalesce(nullif(trim(f.club), ''), 'None')), '') as club,
  nullif(trim(coalesce(f.gender, '')), '')            as gender,
  d.name                       as park_name,
  d.city                       as city,
  d.local_authority,
  d.latlon                     as location,
  e.event_date,
  extract(year    from e.event_date) as year,
  extract(month   from e.event_date) as month,
  extract(quarter from e.event_date) as quarter,
  extract(isodow  from e.event_date) as dayofweek,
  to_char(e.event_date::date, 'IY-\"W\"IW') as iso_week,
  to_char(e.event_date::date, 'IYYY')       as iso_year,
  case when f.result_note = 'New PB' then true else false end    as is_pb,
  case when f.result_note = 'First Timer' then true else false end as is_first_timer,
  f.age_grade::double precision              as age_grade_pct
from parkrun.finishers f
join parkrun.event_history e on e.park = f.park and e.event_no = f.event_no
join analytics.dim_park d    on d.park = f.park
where f.parkrun_id is not null and f.parkrun_id <> ''
with no data;

create unique index fact_run_pkey   on analytics.fact_run (park, event_no, position);
create index        fact_run_person on analytics.fact_run (parkrun_id, park);
create index        fact_run_date   on analytics.fact_run (event_date);
create index        fact_run_year   on analytics.fact_run (year);
grant select on analytics.fact_run to reader;

-- ---------------------------------------------------------------------------
-- fact_volunteer — 1 row per volunteer appearance (person x event)
-- ---------------------------------------------------------------------------
drop materialized view if exists analytics.fact_volunteer;
create materialized view analytics.fact_volunteer as
select
  v.park,                                                   -- dim_park.park
  v.event_no,                                               -- event key
  v.ord,
  v.parkrun_id,                                             -- dim_person.parkrun_id
  lower(v.name)                    as name,
  v.roles,
  nullif(trim(coalesce(nullif(trim(v.club), ''), 'None')), '') as club,
  v.volunteer_credits,
  v.volunteer_badge,
  v.finishes_badge,
  d.name                       as park_name,
  d.city                       as city,
  d.local_authority,
  d.latlon                     as location,
  e.event_date,
  extract(year    from e.event_date) as year,
  extract(month   from e.event_date) as month,
  extract(quarter from e.event_date) as quarter,
  extract(isodow  from e.event_date) as dayofweek,
  to_char(e.event_date::date, 'IY-\"W\"IW') as iso_week,
  to_char(e.event_date::date, 'IYYY')       as iso_year
from parkrun.volunteers v
join parkrun.event_history e on e.park = v.park and e.event_no = v.event_no
join analytics.dim_park d    on d.park = v.park
where v.parkrun_id is not null and v.parkrun_id <> ''
with no data;

create unique index fact_volunteer_pkey   on analytics.fact_volunteer (park, event_no, ord);
create index        fact_volunteer_person on analytics.fact_volunteer (parkrun_id, park);
create index        fact_volunteer_year   on analytics.fact_volunteer (year);
grant select on analytics.fact_volunteer to reader;

-- ---------------------------------------------------------------------------
-- rollup_event — per-event aggregates (TMDL "Events")
-- ---------------------------------------------------------------------------
drop materialized view if exists analytics.rollup_event;
create materialized view analytics.rollup_event as
select
  e.park,
  e.event_no,
  e.event_date,
  d.name                    as park_name,
  d.local_authority,
  e.n_finishers,
  e.n_volunteers,
  e.male_first_name,
  e.male_first_time,
  e.female_first_name,
  e.female_first_time,
  count(fr.parkrun_id)                    as n_finisher_rows,
  count(distinct fr.parkrun_id)           as n_unique_runners,
  sum(case when fr.is_pb then 1 else 0 end)          as n_pb,
  sum(case when fr.is_first_timer then 1 else 0 end) as n_first_timers,
  avg(fr.age_grade_pct)                    as avg_age_grade,
  avg(fr.time_s)                           as avg_time_s,
  min(case when fr.position = 1 then fr.name end)    as first_name_check
from parkrun.event_history e
join analytics.dim_park d           on d.park = e.park
left join analytics.fact_run fr     on fr.park = e.park and fr.event_no = e.event_no
group by e.park, e.event_no, d.name, d.local_authority
with no data;
create unique index rollup_event_pkey on analytics.rollup_event (park, event_no);
grant select on analytics.rollup_event to reader;

-- ---------------------------------------------------------------------------
-- rollup_person_park — one row per (person, park).  TMDL People_Events.
-- Streak definition: longest run of consecutive attended event_nos with no
-- gap (parkrun numbers +1 per week, so event_no gaps == missed weeks);
-- current streak = the run ending at the person's latest visit.
-- Populated by analytics/refresh.sql (needs CTEs a plain MV cannot hold).
-- ---------------------------------------------------------------------------
drop table if exists analytics.rollup_person_park;
create table analytics.rollup_person_park (
  parkrun_id            text not null,
  park                  text not null,
  name                  text,
  gender                text,
  club                  text,
  events_run            integer,
  events_volunteered    integer,
  first_event_date      date,
  last_event_date       date,
  best_position         integer,
  avg_position          numeric(8,2),
  best_time_s           integer,
  avg_time_s            double precision,
  avg_age_grade_pct     double precision,
  n_first_timers        integer,
  n_personals_breaks    integer,
  highest_consecutive   integer,
  current_consecutive   integer,
  primary key (parkrun_id, park)
);
grant select on analytics.rollup_person_park to reader;

-- Grant the reader on everything in schema too, for simplicity in Superset
do $$
declare r record;
begin
  for r in
    select tablename from pg_tables
    where schemaname = 'analytics'
  loop
    execute format('grant select on analytics.%I to reader', r.tablename);
  end loop;
end$$;

-- ---------------------------------------------------------------------------
-- rollup_person_anywhere — one row per person.  "Anywhere" streak.
-- Per-park streak breaks when a person's event_no skips a week AT THAT PARK.
-- This generalises across parks: a person who runs park A one Saturday and
-- park B the next still has an unbroken run, because consecutiveness is now
-- defined on the CALENDAR ISO week attended (any park). All 4 parks run the
-- same Saturday, so consecutive weeks land on consecutive Mondays.
-- Consecutive = attended week is exactly 7 days after the previous attended
-- week; a >7-day jump (or first/last of run) is a break. Multi-park weeks are
-- deduped to a single attended week. Same gap-method single pass as per-park.
-- ---------------------------------------------------------------------------
drop table if exists analytics.rollup_person_anywhere;
create table analytics.rollup_person_anywhere (
  parkrun_id                 text not null,
  name                       text,
  gender                     text,
  club                       text,
  days_run_anywhere          integer,        -- total finish rows, all parks
  parks_run                  integer,
  weeks_run_anywhere         integer,        -- distinct ISO weeks with >=1 run
  first_event_date           date,
  last_event_date            date,
  highest_consecutive_anywhere integer,      -- longest unbroken week-run
  current_consecutive_anywhere integer,      -- unbroken run ending at latest
  primary key (parkrun_id)
);
grant select on analytics.rollup_person_anywhere to reader;

-- ---------------------------------------------------------------------------
-- rollup_person_dedicated — one row per person.  "Dedicated / committed" run.
-- Longest run of CONSECUTIVE HELD event-weeks in which the person showed up
-- (at any of the 4 parks).  A "held event-week" = an ISO week in which at
-- least one park held a parkrun (distinct event week drawn from
-- parkrun.event_history).  Because all 4 parks share the same Saturday (they
-- run on the national calendar), HELD weeks == the parkrun calendar, so this
-- rewards runners who appeared whenever there was a parkrun to enter.
--  vs elsewhere:
--    · per_park  is park-loyal (event_no; breaks on a park hop,
--                robust to that park's cancellations);
--    · anywhere  is the strictest (breaks on ANY calendar week, even a
--                city-wide closure) but park-hop-tolerant;
--    · dedicated sits between: park-hop-tolerant AND robust to closure weeks,
--      breaking only on a held week the runner actually missed.
-- Populated by analytics/refresh.sql (same single-pass gap method).
-- ---------------------------------------------------------------------------
drop table if exists analytics.rollup_person_dedicated;
create table analytics.rollup_person_dedicated (
  parkrun_id                      text not null,
  name                            text,
  gender                          text,
  club                            text,
  attended_event_weeks            integer,     -- distinct HELD weeks with >=1 run
  parks_run                       integer,
  first_event_date                date,
  last_event_date                 date,
  highest_consecutive_dedicated   integer,     -- longest unbroken held-week run
  current_consecutive_dedicated   integer,     -- unbroken run ending at latest
  primary key (parkrun_id)
);
grant select on analytics.rollup_person_dedicated to reader;

-- ---------------------------------------------------------------------------
-- v_person_streaks — one selectable dataset for Superset.
-- All three streak definitions in one grain: (person, streak_type).
-- park is set for per_park and NULL for the two city-wide variants, so a
-- dashboard can filter on streak_type and pivot on highest/current freely.
-- ---------------------------------------------------------------------------
drop view if exists analytics.v_person_streaks;
create view analytics.v_person_streaks as
select 'per_park'   as streak_type, parkrun_id, coalesce(name, '') as name,
       park, highest_consecutive       as highest,
       current_consecutive             as current,
       first_event_date, last_event_date
from analytics.rollup_person_park
union all
select 'dedicated'  as streak_type, parkrun_id, coalesce(name, '') as name,
       null::text as park, highest_consecutive_dedicated as highest,
       current_consecutive_dedicated     as current,
       first_event_date, last_event_date
from analytics.rollup_person_dedicated
union all
select 'anywhere'   as streak_type, parkrun_id, coalesce(name, '') as name,
       null::text as park, highest_consecutive_anywhere    as highest,
       current_consecutive_anywhere      as current,
       first_event_date, last_event_date
from analytics.rollup_person_anywhere;
grant select on analytics.v_person_streaks to reader;
