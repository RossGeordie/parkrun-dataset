"""Fix chart mapping in dashboard 1 + publish via PATCH."""
import requests, re, json

BASE = "http://10.21.63.187:8088"
PW = open("/home/oc/.suppw").read().strip()

def login():
    s = requests.Session()
    r0 = s.get(BASE + "/login/", timeout=15)
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text).group(1)
    s.headers["X-CSRFToken"] = csrf
    s.post(BASE + "/login/", data={"csrf_token": csrf, "username": "admin", "password": PW}, timeout=15)
    return s

s = login()
charts = {c["slice_name"]: c["id"] for c in s.get(BASE + "/api/v1/chart/", timeout=20).json().get("result", [])}
print("charts:", charts)

# intended mapping (by name semantic)
layout = [
    # (key, x, y, w, h, chart_name)
    ("kpi_runners", 0, 0, 1, 2, "Unique runners"),
    ("kpi_events", 1, 0, 1, 2, "Events held"),
    ("kpi_entries", 2, 0, 1, 2, "Finisher entries"),
    ("trend", 0, 2, 2, 2, "Participants per month by park"),
    ("vol_stack", 2, 2, 2, 2, "Volunteers by year (stacked)"),
    ("ag_line", 0, 4, 3, 2, "Average age grade by park (monthly)"),
    ("streaks", 3, 4, 3, 2, "Top streak leaderboard"),
]

pos = {}
for key, x, y, w, h, cname in layout:
    cid = charts.get(cname)
    pos[key] = {"id": key, "key": "CHART", "x": x, "y": y, "width": w, "height": h,
                "children": [], "metadata": {"chartId": cid}}
    print(key, "->", cname, cid)

pos["nf_streak"] = {
    "key": "NATIVE_FILTER", "x": 0, "y": 6, "width": 1, "height": 1, "children": [],
    "filters": [{"name": "Streak type", "controlType": "filter_select",
                 "ownState": {"multiSelect": True, "defaultToFirstItem": False, "renderValues": True,
                               "renderTruncatedTags": True, "showSearch": True, "ignoreCase": False,
                               "labelOverride": "", "expandable": True, "displayConfiguration": {}},
                 "targets": [{"label": "Streak type", "datasetId": 3, "columnId": 34}]}],
}

DID = 1
r = s.put(BASE + f"/api/v1/dashboard/{DID}", json={"position_json": json.dumps(pos)}, timeout=60)
print("put pos:", r.status_code, r.text[:150])

# publish — try PATCH first
r = s.patch(BASE + f"/api/v1/dashboard/{DID}", json={"published": True}, timeout=30)
print("patch publish:", r.status_code, r.text[:150])
if r.status_code != 200:
    # maybe publish only on full PUT body
    body = s.get(BASE + f"/api/v1/dashboard/{DID}", timeout=15).json()["result"]
    for k in ("id", "created_on", "changed_on", "url", "status"):
        body.pop(k, None)
    body["published"] = True
    r = s.put(BASE + f"/api/v1/dashboard/{DID}", json=body, timeout=60)
    print("put publish:", r.status_code, r.text[:250])

d = s.get(BASE + f"/api/v1/dashboard/{DID}", timeout=15).json()["result"]
print("published:", d.get("published"), "temp", d.get("temporary"), "status:", d.get("status"))
pj = json.loads(d.get("position_json") or "{}")
print("pos keys:", list(pj.keys()))
print("nf:", json.dumps(pj.get("nf_streak"), indent=None)[:400])
print("\nDASHBOARD URL: http://10.21.63.187:8088/dashboard/%d" % DID)
