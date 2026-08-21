#!/usr/bin/env python3
"""Superset seed: parkrun datasource + charts + dashboard.

Runs at container start (see entrypoint.sh). Idempotent: safe to re-run —
it looks up existing objects by name before creating. All parameters come
from env (see .env.example). Requires `requests` in the Superset image.
"""
import os
import sys
import time

import requests

BASE = os.environ.get("SUPERSET_BASE", "http://127.0.0.1:8088")
USER = os.environ.get("SUPERSET_ADMIN_USERNAME", "admin")
PASSWORD = os.environ.get("SUPERSET_ADMIN_PASSWORD", "")

PG_HOST = os.environ.get("PG_HOST", "10.21.63.248")
PG_PORT = os.environ.get("PG_PORT", "5432")
PG_USER = os.environ.get("PG_USER", "scraper")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "")
PG_DB = os.environ.get("PG_DATABASE", "parkrun")

DB_NAME = "parkrun"              # Superset database entry
SCHEMA = "parkrun"               # actual PG schema
TABLES = ["event_history", "finishers", "volunteers"]

log = print
sys.stdout.reconfigure(line_buffering=True)


def login(s):
    s.post(f"{BASE}/login/", json={"username": USER, "password": PASSWORD,
                                   "provider": "db", "remember_me": False})
    if s.cookies.get("session"):
        return
    # some builds POST to /api/v1/security/login
    s.post(f"{BASE}/api/v1/security/login/", json={"username": USER, "password": PASSWORD})


def find(s, path, name=None):
    """GET a list endpoint and return the entry whose name matches."""
    r = s.get(path, timeout=30)
    if not r.ok:
        return None
    data = r.json().get("result", [])
    if name is None:
        return data
    for item in data:
        if item.get("database") == name or item.get("dataset_name") == name \
           or item.get("name") == name or item.get("id") == name:
            return item
    return None


def _uri():
    p = requests.utils.quote(PG_PASSWORD, safe="")
    return "postgresql+psycopg2://%s:%s@%s:%s/%s" % (PG_USER, p, PG_HOST, PG_PORT, PG_DB)


def ensure_database(s):
    r = s.get(BASE + "/api/v1/databases/", timeout=30)
    if r.ok:
        for d in r.json().get("result", []):
            if d.get("database") == DB_NAME:
                log("  database entry exists:", DB_NAME, "id=", d["id"])
                return d["id"]
    log("  creating database entry:", DB_NAME)
    r = s.post(BASE + "/api/v1/databases/", timeout=60, json={
        "database_name": DB_NAME,
        "sqlalchemy_uri": _uri(),
        "expose_in_sqllab": False,
        "server": PG_HOST,
    })
    if r.ok:
        rr = s.get(BASE + "/api/v1/databases/", timeout=30)
        for d in rr.json().get("result", []):
            if d.get("database") == DB_NAME:
                return d["id"]
    log("  database creation FAILED:", r.text[:200])
    return None


def ensure_dataset(s, table, database_id):
    r = s.get(BASE + "/api/v1/datasets/", timeout=30)
    if r.ok:
        for d in r.json().get("result", []):
            if d.get("table_name") == table and d.get("database_id") == database_id:
                log("  dataset exists:", table, "id=", d["id"])
                return d["id"]
    log("  creating dataset:", table)
    r = s.post(BASE + "/api/v1/datasets/", timeout=60, json={
        "table_name": table,
        "schema": SCHEMA,
        "database_id": database_id,
    })
    if r.ok:
        return r.json().get("id")
    log("  dataset create note:", r.text[:200])
    return None


def create_chart(s, title, vtype, dataset_id, columns, extras=None):
    payload = {
        "slice_name": title,
        "viz_type": vtype,
        "dataset_id": dataset_id,
        "params": {
            "groupby": ["event_date"],
            "orderby": [[{"label": "event_date", "type": "DATE"}, "event_date"]],
            "metrics": [extras.get("metric", "count(*)") if extras else "count(*)"],
            "adhoc_filters": [],
            "row_limit": extras.get("row_limit", 50) if extras else 50,
        },
    }
    r = s.post(BASE + "/api/v1/chart/", timeout=60, json=payload)
    if r.ok:
        log("  chart created:", title, "id=", r.json().get("id"))
        return r.json().get("id")
    log("  chart create FAILED:", title, r.text[:200])
    return None


def create_dashboard(s, title, chart_ids):
    position = {}
    key = 0
    for idx, cid in enumerate(chart_ids or []):
        if cid is None:
            continue
        key = "a%d" % idx
        position["dnd"] = {
            "DRAGGABLE": {"dragging": False, "payload": {"key": key}},
            "GRID": {"x": idx, "y": 0, "i": key, "w": 1, "h": 4, "minW": 1, "minH": 1, "moved": False, "static": False},
        }
    payload = {
        "dashboard_title": title,
        "status": "published",
        "published": True,
        "certified_by": "",
        "certification_details": "",
        "published_json": "{}",
        "position": {
            "DASHBOARD_VERSION_KEY": "v2",
            "metadata": {"chart_order_position": {}, "refresh_frequency": 0},
            "SLASH_COMMANDS": position,
        },
        "metadata": {"shared": True, "timed_refresh_immune_slices_v2": []},
        "timed_refresh_immune_slices": "",
        "timed_refresh_immune_slices_mask": [],
        "color_scheme": "supersetColors",
        "crossfilter": False,
        "native_filter_configuration": {},
        "native_filter_time_range": False,
        "expanded_slices": [],
        "color_pairs": ["#486683", "#AAB2BD", "#DAAC03", "#5171B2", "#59A14F"],
        "label_colors": {},
        "label_map": {},
        "refresh_frequency": 0,
    }
    r = s.post(BASE + "/api/v1/dashboard/", timeout=60, json=payload)
    if r.ok:
        log("  dashboard created:", title, "id=", r.json().get("id"))
        return r.json().get("id")
    log("  dashboard create FAILED:", r.text[:200])
    return None


def main():
    log("== Superset seed: parkrun ==")
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    login(s)
    if not s.cookies.get("session"):
        log("FATAL: cannot log in to Superset (admin@ %s)" % USER)
        return 1

    db_id = ensure_database(s)
    if not db_id:
        return 1

    ds_ids = {}
    for t in TABLES:
        ds_ids[t] = ensure_dataset(s, t, db_id)
        log("  dataset", t, "->", ds_ids[t])

    # --- charts ---
    log("== creating charts ==")
    chart_ids = []

    chart_ids.append(create_chart(
        s,
        "Finishers by age group",
        "bar",
        ds_ids.get("finishers"),
        ["age_group"],
        extras={"metric": "count(*)", "row_limit": 20},
    ))

    chart_ids.append(create_chart(
        s,
        "Event count by date series",
        "line",
        ds_ids.get("event_history"),
        ["event_date"],
        extras={"metric": "count(*)"},
    ))

    chart_ids.append(create_chart(
        s,
        "Volunteer badge distribution",
        "pie",
        ds_ids.get("volunteers"),
        ["volunteer_badge"],
        extras={"metric": "count(*)"},
    ))

    chart_ids.append(create_chart(
        s,
        "Top finishing clubs",
        "bar",
        ds_ids.get("finishers"),
        ["club"],
        extras={"metric": "count(*)", "row_limit": 15},
    ))

    chart_ids.append(create_chart(
        s,
        "Volunteers by park",
        "table",
        ds_ids.get("volunteers"),
        ["park"],
        extras={"metric": "count(*)"},
    ))

    # --- dashboard ---
    log("== creating dashboard ==")
    log("  charts available:", [c for c in chart_ids if c is not None])
    dashboard_id = create_dashboard(s, "parkrun overview", chart_ids)
    if dashboard_id:
        log("DASHBOARD URL: " + BASE + "/dashboard/" + str(dashboard_id))

    log("== seeding done ==")
    return 0


if __name__ == "__main__":
    # retry — superset server may still be warming
    for i in range(12):
        try:
            requests.get(BASE, timeout=5)
            break
        except Exception:
            log(f"waiting for superset... ({i+1}/12)")
            time.sleep(10)
    raise SystemExit(main())

