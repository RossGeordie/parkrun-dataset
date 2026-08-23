"""Isolate which position shape breaks PUT. Scratch dashboards, cleaned after."""
import os, re, json
import requests

BASE = "http://10.21.63.187:8088"
PW = os.environ["SUP_PW"]
s = requests.Session()
r0 = s.get(BASE + "/login/", timeout=15)
csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text).group(1)
s.headers["X-CSRFToken"] = csrf
s.post(BASE + "/login/", data={"csrf_token": csrf, "username": "admin", "password": PW}, timeout=15)

def chart(k, x, y, w, h, cid):
    return {"id": k, "key": "CHART", "x": x, "y": y, "width": w, "height": h, "children": [],
            "metadata": {"chartId": cid}}

base3 = {
    "a": chart("a", 0, 0, 1, 2, 1),
    "b": chart("b", 1, 0, 1, 2, 2),
    "c": chart("c", 2, 0, 1, 2, 3),
}
F = {"key": "NATIVE_FILTER", "x": 0, "y": 2, "width": 1, "height": 1, "children": [],
     "filters": [{"name": "Streak type", "controlType": "filter_select",
                  "ownState": {"multiSelect": True},
                  "targets": [{"label": "Streak type", "datasetId": 3, "columnId": 34}]}]}

shapes = {}
shapes["charts_only"] = lambda: dict(base3)
shapes["charts_plus_f"] = lambda: {**base3, "nf": F}
shapes["f_no_ownstate"] = lambda: {**base3, "nf": {**F, "filters": [
    {"name": "Streak type", "controlType": "filter_select",
     "targets": [{"label": "Streak type", "datasetId": 3, "columnId": 34}]}]}}
shapes["f_with_id"] = lambda: {**base3, "nf": {**F, "id": "nf"}}

created = []
for name, fn in shapes.items():
    body = {"dashboard_title": "scratch-" + name, "position_json": json.dumps(fn()),
            "certification_details": ""}
    r = s.post(BASE + "/api/v1/dashboard/", json=body, timeout=60)
    if r.status_code not in (200, 201):
        print(name, "create", r.status_code, r.text[:100]); continue
    did = r.json()["id"]; created.append(did)
    # attempt 1: PUT published only
    r = s.put(BASE + f"/api/v1/dashboard/{did}", json={"published": True}, timeout=60)
    res = r.status_code
    if r.status_code not in (200, 201):
        r2 = s.put(BASE + f"/api/v1/dashboard/{did}", json={"published": True, "position_json": fn()}, timeout=60)
        res = str(r.status_code) + "->" + str(r2.status_code)
    print(f"{name}: {res}")

for did in created:
    s.delete(BASE + f"/api/v1/dashboard/{did}", timeout=30)
print("cleaned", created)
