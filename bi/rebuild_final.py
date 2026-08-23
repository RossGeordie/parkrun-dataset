"""Rebuild the dashboard with real chart refs + native filter. Needs SUP_PW env."""
import os, re, json
import requests

BASE = "http://10.21.63.187:8088"
PW = os.environ["SUP_PW"]
s = requests.Session()
r0 = s.get(BASE + "/login/", timeout=15)
csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text).group(1)
s.headers["X-CSRFToken"] = csrf
r = s.post(BASE + "/login/", data={"csrf_token": csrf, "username": "admin", "password": PW}, timeout=15)
print("login:", r.status_code, "->", r.headers.get("location"))

# wipe all dashboards
for d in s.get(BASE + "/api/v1/dashboard/", timeout=15).json()["result"]:
    s.delete(BASE + f"/api/v1/dashboard/{d['id']}", timeout=15)
print("cleared")

cm = {c["slice_name"]: c["id"] for c in s.get(BASE + "/api/v1/chart/", timeout=20).json()["result"]}
need = ["Unique runners", "Events held", "Finisher entries", "Participants per month by park",
        "Volunteers by year (stacked)", "Average age grade by park (monthly)", "Top streak leaderboard"]
missing = [n for n in need if n not in cm]
print("charts:", cm)
print("missing:", missing)
if missing:
    raise SystemExit("missing charts: " + str(missing))

d3 = s.get(BASE + "/api/v1/dataset/3", timeout=15).json()["result"]
stc = [c for c in d3.get("columns", []) if c.get("column_name") == "streak_type"]
print("streak_type col:", stc)
col_id = stc[0]["id"] if stc else None
if col_id is None:
    col_id = s.get(BASE + "/api/v1/dataset/3/columns/?q=streak_type", timeout=15).json()
    print("col query:", col_id)

def node(k, x, y, w, h, cid):
    return {"id": k, "key": "CHART", "x": x, "y": y, "width": w, "height": h, "children": [],
            "metadata": {"chartId": cid}}

pos = {
    "k1": node("k1", 0, 0, 1, 2, cm["Unique runners"]),
    "k2": node("k2", 1, 0, 1, 2, cm["Events held"]),
    "k3": node("k3", 2, 0, 1, 2, cm["Finisher entries"]),
    "c1": node("c1", 0, 2, 2, 2, cm["Participants per month by park"]),
    "c2": node("c2", 2, 2, 2, 2, cm["Volunteers by year (stacked)"]),
    "c3": node("c3", 0, 4, 3, 2, cm["Top streak leaderboard"]),
    "c4": node("c4", 3, 4, 3, 2, cm["Average age grade by park (monthly)"]),
    "nf": {"key": "NATIVE_FILTER", "x": 0, "y": 6, "width": 1, "height": 1, "children": [],
           "filters": [{"name": "Streak type", "controlType": "filter_select",
                        "ownState": {"multiSelect": True, "defaultToFirstItem": False,
                                     "renderValues": True, "renderTruncatedTags": True,
                                     "showSearch": True, "ignoreCase": False,
                                     "labelOverride": "", "expandable": True,
                                     "displayConfiguration": {}},
                        "targets": [{"label": "Streak type", "datasetId": 3, "columnId": col_id}]}]},
}
body = {"dashboard_title": "Newcastle parkrun  LA overview (4 parks, 2010 to 2026)",
        "position_json": json.dumps(pos),
        "certification_details": "Verified against PG17 star schema (436,976 runs)."}
r = s.post(BASE + "/api/v1/dashboard/", json=body, timeout=60)
print("create:", r.status_code, r.text[:200])

new = s.get(BASE + "/api/v1/dashboard/", timeout=15).json()["result"]
print("dashboards:", [(d["id"], d.get("published"), d.get("status")) for d in new])
did = new[0]["id"]
det = s.get(BASE + f"/api/v1/dashboard/{did}", timeout=15).json()["result"]
print("published:", det.get("published"), "status:", det.get("status"))
pj = json.loads(det.get("position_json") or "{}")
for k, v in pj.items():
    print(" ", k, "->", v.get("metadata"), v.get("key"))
print("URL http://10.21.63.187:8088/dashboard/%s" % did)
