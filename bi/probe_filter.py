"""Probe native-filter shapes in position_json for this Superset build."""
import requests, re, json

BASE = "http://10.21.63.187:8088"
s = requests.Session()
r0 = s.get(f"{BASE}/login/", timeout=15)
csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text).group(1)
s.headers["X-CSRFToken"] = csrf
s.post(f"{BASE}/login/", data={"csrf_token": csrf, "username": "admin", "password": open("/home/oc/.suppw").read().strip()}, timeout=15)
DID = 1

base = {"echarts_1": {"id": 1, "key": "echarts", "x": 0, "y": 0, "width": 4, "height": 4, "children": []}}

def filt(fid, extra=None):
    f = {
        "id": fid, "name": "Streak type",
        "controlType": "filter_select",
        "filterType": "FILTER_SELECT",
        "ownState": {},
        "targets": [{"column": {"name": "streak_type"}, "datasetId": 3}],
    }
    if extra:
        f.update(extra)
    return f

variants = {
    "V1 minimal": (base, "nf1", filt("nf1")),
    "V2 typed-col": (base, "nf2", filt("nf2", {"targets": [{"label": "streak_type", "column": {"name": "streak_type", "type": "STRING"}, "datasetId": 3}]})),
    "V3 ownState-full": (base, "nf3", filt("nf3", {"ownState": {"multiSelect": True, "defaultToFirstItem": False}})),
    "V4 filterType-on-wrapper": (base, "nf4", filt("nf4", {})),
}
for name, (b, fid, f) in variants.items():
    pos = dict(b)
    pos[fid] = {"id": fid, "key": "NATIVE_FILTER", "x": 0, "y": 4, "width": 1, "height": 1, "children": [], "filters": [f]}
    r = s.put(f"{BASE}/api/v1/dashboard/{DID}", json={"position_json": json.dumps(pos)}, timeout=60)
    ok = r.status_code == 200
    print(f"{name:20s} -> {r.status_code} {'OK' if ok else r.text[:140]}")
