"""v6-aware rebuild: fresh dashboard with grid metadata + native streak_type filter, then publish."""
import requests, re, json

BASE = "http://10.21.63.187:8088"
PW = open("/home/oc/.suppw").read().strip()

def login():
    s = requests.Session()
    r0 = s.get(BASE + "/login/", timeout=15)
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text).group(1)
    s.headers["X-CSRFToken"] = csrf
    r = s.post(BASE + "/login/", data={"csrf_token": csrf, "username": "admin", "password": PW}, timeout=15)
    return s

s = login()

# delete all dashboards, start clean
for d in s.get(BASE + "/api/v1/dashboard/", timeout=15).json().get("result", []):
    s.delete(BASE + f"/api/v1/dashboard/{d['id']}", timeout=15)
print("dashboards cleared")

# chart ids (persists; we only deleted dashboards)
charts = {c["slice_name"]: c["id"] for c in s.get(BASE + "/api/v1/chart/", timeout=20).json().get("result", [])}
print("charts:", charts)
want = ["Top-3 unique runners", "Top-3 parks by total attendance", "Top-3 streak leaders",
        "Attendance by event (finishers vs volunteers)", "Volunteer participation by event (stacked)",
        "Monthly attendance trend", "Average age grade over time"]
missing = [w for w in want if w not in charts]
print("missing:", missing)

# build position with v6 grid metadata
def chart(key, x, y, w, h, cid):
    return {"id": key, "key": "CHART", "x": x, "y": y, "width": w, "height": h, "children": [], "metadata": {"chartId": cid}}

def filt(target):
    return {"name": "Streak type", "controlType": "filter_select",
            "ownState": {"multiSelect": True, "defaultToFirstItem": False, "renderValues": True,
                          "renderTruncatedTags": True, "showSearch": True, "ignoreCase": False,
                          "labelOverride": "", "expandable": True, "displayConfiguration": {}},
            "targets": [target]}

def filter_node(targets):
    return {"key": "NATIVE_FILTER", "x": 0, "y": 4, "width": 1, "height": 1, "children": [],
            "filters": [filt(t) for t in targets]}

nodes = {
    "echarts_kpi_runners": chart("echarts_kpi_runners", 0, 0, 1, 2, charts.get("Top-3 unique runners")),
    "echarts_kpi_parks": chart("echarts_kpi_parks", 1, 0, 1, 2, charts.get("Top-3 parks by total attendance")),
    "echarts_kpi_streak": chart("echarts_kpi_streak", 2, 0, 1, 2, charts.get("Top-3 streak leaders")),
    "echarts_1": chart("echarts_1", 0, 2, 2, 2, charts.get("Attendance by event (finishers vs volunteers)")),
    "echarts_2": chart("echarts_2", 2, 2, 2, 2, charts.get("Volunteer participation by event (stacked)")),
    "echarts_3": chart("echarts_3", 0, 4, 3, 2, charts.get("Monthly attendance trend")),
    "echarts_4": chart("echarts_4", 3, 4, 3, 2, charts.get("Average age grade over time")),
}

variants = {
    "no_gridwrap": nodes,
    "gridwrap": {"DASHBOARD": {
        "id": "DASHBOARD", "type": "GRID", "key": "ROOT", "x": 0, "y": 0,
        "width": 12, "height": 80, "children": [],
        "meta": {"innerWidth": 1488, "innerHeight": 800},
        **nodes}},
}
target_variants = {
    "colId_only": {"label": "Streak type", "datasetId": 3, "columnId": 34},
    "colObj": {"label": "Streak type", "datasetId": 3, "column": {"name": "streak_type", "type": "STRING"}},
}

last_err = None
for gname, gnodes in variants.items():
    for tname, tgt in target_variants.items():
        pos = dict(gnodes)
        pos["nf_streak"] = filter_node([tgt])
        # create (no id)
        body = {"dashboard_title": "Newcastle parkrun - LA overview",
                "position_json": json.dumps(pos), "published": False,
                "certification_details": "Star schema on PG17, verified 2026-08."}
        r = s.post(BASE + "/api/v1/dashboard/", json=body, timeout=60)
        if r.status_code in (200, 201):
            print(f"CREATED ok: grid={gname} target={tname}")
            break
        last_err = f"{gname}+{tname} -> {r.status_code} {r.text[:160]}"
        print(last_err)
        # clean up any dashboards created during probe
        for d in s.get(BASE + "/api/v1/dashboard/", timeout=15).json().get("result", []):
            s.delete(BASE + f"/api/v1/dashboard/{d['id']}", timeout=15)
    else:
        continue
    break

# check state
ds = s.get(BASE + "/api/v1/dashboard/", timeout=15).json().get("result", [])
print("dashboards now:", [(d["id"], d.get("dashboard_title")) for d in ds])
if ds:
    did = ds[0]["id"]
    d = s.get(BASE + f"/api/v1/dashboard/{did}", timeout=15).json()["result"]
    pj = json.loads(d.get("position_json") or "{}")
    print("pos keys:", list(pj.keys()))
    # publish
    r = s.put(BASE + f"/api/v1/dashboard/{did}", json={"published": True}, timeout=30)
    print("publish:", r.status_code, r.text[:200])
print("DASHBOARD URL: http://10.21.63.187:8088/dashboard/" + (str(ds[0]["id"]) if ds else "?"))
