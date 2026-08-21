-- ============================================================================
-- analytics refresh — run AFTER each successful scrape
-- Single-pass rollup: every stage is a window/aggregate over the 437k-row
-- fact_run, no correlated subqueries.
-- Streak: parkrun event_no increments +1 per week, so a gap == missed week.
-- ============================================================================

refresh materialized view analytics.dim_person;
refresh materialized view analytics.fact_run;
refresh materialized view analytics.fact_volunteer;
refresh materialized view analytics.rollup_event;

truncate analytics.rollup_person_park;

with runs as (
  select parkrun_id, park, event_no, position, time_s,
         age_grade_pct, is_first_timer, is_pb
  from analytics.fact_run
),
flagged as (
  select r.*,
         case when lag(event_no) over (
                partition by parkrun_id, park order by event_no
              ) = event_no - 1
              then 0 else 1 end as is_break
  from runs r
),
runs_num as (
  select f.*,
         sum(is_break) over (
           partition by parkrun_id, park order by event_no
           range unbounded preceding
         ) as streak_id,
         row_number() over (
           partition by parkrun_id, park order by event_no desc
         ) as seq_desc
  from flagged f
),
streaks_agg as (
  select parkrun_id, park, streak_id,
         count(*) as len,
         bool_or(seq_desc = 1)                    as is_current_streak,
         max(event_no) as end_event
  from runs_num
  group by parkrun_id, park, streak_id
),
person_streaks as (
  select parkrun_id, park,
         max(len)                                   as highest_consecutive,
         max(case when is_current_streak then len end) as current_consecutive
  from streaks_agg
  group by parkrun_id, park
),
dates as (
  select park, event_no, event_date
  from parkrun.event_history
),
per_park as (
  select
    r.parkrun_id, r.park,
    count(*)                                   as events_run,
    min(r.event_no)                            as first_event_no,
    max(r.event_no)                            as last_event_no,
    min(r.position)                            as best_position,
    round(avg(r.position)::numeric, 2)         as avg_position,
    min(r.time_s)                              as best_time_s,
    round(avg(r.time_s)::numeric, 2)           as avg_time_s,
    round((avg(r.age_grade_pct)
          filter (where r.age_grade_pct is not null))::numeric, 2) as avg_age_grade_pct,
    count(*) filter (where r.is_first_timer)   as n_first_timers,
    count(*) filter (where r.is_pb)            as n_personals_breaks
  from runs r
  group by r.parkrun_id, r.park
)
insert into analytics.rollup_person_park (
  parkrun_id, park, name, gender, club,
  events_run, events_volunteered,
  first_event_date, last_event_date,
  best_position, avg_position, best_time_s, avg_time_s, avg_age_grade_pct,
  n_first_timers, n_personals_breaks,
  highest_consecutive, current_consecutive
)
select
  p.parkrun_id,
  p.park,
  d.name, d.gender, d.club,
  p.events_run,
  coalesce(v.n_vol, 0)  as n_vol_final,
  fd.event_date     as first_event_date,
  ld.event_date     as last_event_date,
  p.best_position,
  p.avg_position,
  p.best_time_s,
  p.avg_time_s,
  p.avg_age_grade_pct,
  p.n_first_timers,
  p.n_personals_breaks,
  s.highest_consecutive,
  s.current_consecutive
from per_park p
join analytics.dim_person d  on d.parkrun_id = p.parkrun_id
join person_streaks    s     on s.parkrun_id = p.parkrun_id and s.park = p.park
left join (
  select parkrun_id, park, count(*) as n_vol
  from analytics.fact_volunteer
  group by parkrun_id, park
) v on v.parkrun_id = p.parkrun_id and v.park = p.park
left join dates fd on fd.park = p.park and fd.event_no = p.first_event_no
left join dates ld on ld.park = p.park and ld.event_no = p.last_event_no;

analyze analytics.rollup_person_park;