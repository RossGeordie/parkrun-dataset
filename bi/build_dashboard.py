"""Build the Newcastle parkrun dashboard in Superset via REST API.

Panels:
  KPI row : unique runners | events held | finisher entries
  Top streak leaderboard (bar_horizontal, driven by native streak_type filter)
  Participants per month by park (area)
  Volunteers by year (stacked bar, series=park)
  Average age grade by park (line, monthly)
"""
import requests
import re
import sys
import json
import time

BASE = "http://10.21.63.187:8088"
ADMIN_PW = open("/home/oc/.suppw").read().strip()
DS_EVENT = 2      # analytics.rollup_event
DS_STREAK = 3     # analytics.v_person_streaks

s = requests.Session()


def csrf(s):
    r0 = s.get(f"{BASE}/login/", timeout=15)
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text).group(1)
    s.headers["X-CSRFToken"] = csrf
    s.post(f"{BASE}/login/", timeout=15,
           data={"csrf_token": csrf, "username": "admin", "password": ADMIN_PW})


csrf(s)

# ---------- verify dataset columns ----------
for did in (DS_EVENT, DS_STREAK):
    d = s.get(f"{BASE}/api/v1/dataset/{did}", timeout=30).json()["result"]
    cols = [c["column_name"] for c in d.get("columns", [])]
    print(f"dataset {did} {d['schema']}.{d['table_name']}: {cols}")
print()


def find_existing(name):
    r = s.get(f"{BASE}/api/v1/chart/", timeout=30).json()["result"]
    return [c for c in r if c.get("slice_name") == name or c.get("dashboard_title_and_slice_name") == name][:1] or \
           [c for c in r if c.get("slice_name") == name][:1]


def make_chart(name, viz, dsid, params, filters=None):
    """Create (or reuse) a chart. Returns (id, reused:bool)."""
    existing = [c for c in s.get(f"{BASE}/api/v1/chart/", timeout=30).json().get("result", [])
                if c.get("slice_name") == name]
    if existing:
        print(f"  reuse chart {name!r} id={existing[0]['id']}")
        return existing[0]["id"], True
    payload = {
        "slice_name": name,
        "viz_type": viz,
        "datasource_id": dsid,
        "datasource_type": "table",
        "params": json.dumps(params),
    }
    r = s.post(f"{BASE}/api/v1/chart/", json=payload, timeout=60)
    if r.status_code not in (200, 201):
        print(f"  FAIL chart {name!r}: {r.status_code} {r.text[:400]}")
        return None, False
    cid = r.json()["id"]
    print(f"  created chart {name!r} id={cid} viz={viz}")
    return cid, False


charts = {}

# ---------- KPIs ----------
charts["runners"] = make_chart(
    "Unique runners", "big_number_total", DS_STREAK,
    {"metrics": ["count(distinct parkrun_id)"], "adhoc_filters": []})[0]

charts["events"] = make_chart(
    "Events held", "big_number_total", DS_EVENT,
    {"metrics": ["count(*)"], "adhoc_filters": []})[0]

charts["entries"] = make_chart(
    "Finisher entries", "big_number_total", DS_EVENT,
    {"metrics": ["sum(n_finishers)"], "adhoc_filters": []})[0]

# ---------- leaderboard ----------
charts["leaderboard"] = make_chart(
    "Top streak leaderboard", "bar_horizontal", DS_STREAK,
    {
        "groupby": [
            {"name": "runner", "type": "column",
             "expression": "coalesce(nullif(name, ''), '<anonymous ' || parkrun_id || '>')",
             "label": "Runner"},
        ],
        "metrics": ["max(highest)"],
        "orderby": [{"name": "max(highest)", "order": "desc"}],
        "limit": 20,
        "adhoc_filters": [],
        "x": "runner",
    })[0]

# ---------- participants per month ----------
charts["participants"] = make_chart(
    "Participants per month by park", "area", DS_EVENT,
    {
        "x": "event_date",
        "time_grain_sqla": "P1M",
        "groupby": ["park"],
        "metrics": ["sum(n_finishers)"],
        "adhoc_filters": [],
    })[0]

# ---------- volunteers stacked ----------
charts["volunteers"] = make_chart(
    "Volunteers by year (stacked)", "bar", DS_EVENT,
    {
        "x": "event_date",
        "time_grain_sqla": "P1Y",
        "groupby": ["park"],
        "metrics": ["sum(n_volunteers)"],
        "stack": True,
        "adhoc_filters": [],
    })[0]

# ---------- age grade ----------
charts["agegrade"] = make_chart(
    "Average age grade by park (monthly)", "line", DS_EVENT,
    {
        "x": "event_date",
        "time_grain_sqla": "P1M",
        "groupby": ["park"],
        "metrics": ["avg(avg_age_grade)"],
        "adhoc_filters": [],
    })[0]

missing = [k for k, v in charts.items() if v is None]
if missing:
    print("MISSING CHARTS:", missing)
    sys.exit(1)

print("\nCHARTS:", json.dumps(charts))

# ---------- dashboard ----------
dash_name = "Newcastle parkrun — LA report"
existing_dash = [d for d in s.get(f"{BASE}/api/v1/dashboard/", timeout=30).json()["result"]
                 if d.get("dashboard_title") == dash_name]
if existing_dash:
    dash_id = existing_dash[0]["id"]
    print(f"reuse dashboard id={dash_id}")
else:
    r = s.post(f"{BASE}/api/v1/dashboard/", json={"dashboard_title": dash_name}, timeout=30)
    if r.status_code not in (200, 201):
        print("dashboard create FAIL:", r.status_code, r.text[:300])
        sys.exit(1)
    dash_id = r.json()["id"]
    print(f"created dashboard id={dash_id}")

# native filter: streak_type select on dataset 3
flt = {
    "filterType": "FILTER_SELECT",
    "id": "flt_streak_type_001",
    "name": "Streak type",
    "controlType": "filter_select",
    "ownState": {"defaultToFirstItem": False, "multiSelect": True,
                 "placeHolder": "per_park / dedicated / anywhere"},
    "targets": [{"column": {"name": "streak_type"}, "datasetId": DS_STREAK}],
    "display_configuration": {"expanded": True, "multiSelect": True,
                              "position": {"column": 0, "row": 0, "colWidth": 1, "colOffset": 0, "rowOffset": 6, "height": 12}},
}

positions = {
    f"echarts_{charts['runners']}":  {"id": charts["runners"], "key": "echarts",    "x": 0, "y": 0,  "width": 4, "height": 4, "children": []},
    f"echarts_{charts['events']}":   {"id": charts["events"],  "key": "echarts",    "x": 4, "y": 0,  "width": 4, "height": 4, "children": []},
    f"echarts_{charts['entries']}":  {"id": charts["entries"],  "key": "echarts",    "x": 8, "y": 0,  "width": 4, "height": 4, "children": []},
    f"echarts_{charts['leaderboard']}": {"id": charts["leaderboard"], "key": "echarts", "x": 0, "y": 4, "width": 12, "height": 8, "children": []},
    f"echarts_{charts['participants']}": {"id": charts["participants"], "key": "echarts", "x": 0, "y": 12, "width": 12, "height": 7, "children": []},
    f"echarts_{charts['volunteers']}": {"id": charts["volunteers"], "key": "echarts", "x": 0, "y": 19, "width": 6, "height": 7, "children": []},
    f"echarts_{charts['agegrade']}": {"id": charts["agegrade"], "key": "echarts", "x": 6, "y": 19, "width": 6, "height": 7, "children": []},
    flt["id"]: {"key": "NATIVE_FILTER", "x": 0, "y": 4, "width": 2, "height": 15, "children": []},
}

body = {
    "dashboard_title": dash_name,
    "published": True,
    "position_json": json.dumps(positions),
    "certification_details": "Star schema on PG17, verified. Streak types: per_park (event_no chain), anywhere (calendar weeks), dedicated (held weeks).",
}
r = s.put(f"{BASE}/api/v1/dashboard/{dash_id}", json=body, timeout=60)
if r.status_code not in (200, 201):
    print("dashboard PUT FAIL:", r.status_code, r.text[:500])
    sys.exit(1)
print("dashboard PUT ok")
print("\nDASHBOARD URL: %s/dashboard/%d" % (BASE, dash_id))
