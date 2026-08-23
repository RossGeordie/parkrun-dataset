"""Add native streak_type filter (columnId-style targets)."""
import requests, re, json

BASE = "http://21.63.187:8088" if False else "http://10.21.63.187:8088"
U, P = "admin", open("/home/oc/.suppw").read().strip()

s = requests.Session()
r0 = s.get(BASE + "/login/", timeout=15)
csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text).group(1)
s.headers["X-CSRFToken"] = csrf
s.post(BASE + "/login/", data={"csrf_token": csrf, "username": U, "password": P}, timeout=15)

# column id of streak_type in dataset 3
ds = s.get(BASE + "/api/v1/dataset/3", timeout=15).json().get("result")
print("dataset:", ds.get("table_name"))
CID = None
for c in (ds.get("columns") or []):
    if c.get("column_name") == "streak_type":
        CID = c.get("id")
print("streak_type column id =", CID)

DID = 1
d = s.get(BASE + "/api/v1/dashboard/%s" % DID, timeout=15).json()["result"]
pos = json.loads(d.get("position_json") or "{}")

own = {"multiSelect": True, "defaultToFirstItem": False, "renderValues": True,
       "renderTruncatedTags": True, "showSearch": True, "ignoreCase": False,
       "labelOverride": "", "expandable": True, "displayConfiguration": {}}

def target(**kw):
    t = {"label": "Streak type", "datasetId": 3}
    t.update(kw)
    return t

variants = {
    "columnId": target(columnId=CID),
    "column-name": target(column={"name": "streak_type", "type": "STRING"}),
    "both": target(columnId=CID, column={"name": "streak_type", "type": "STRING"}),
    "col-id-only": target(column={"id": CID}),
}

for label, tgt in variants.items():
    fid = "native_select_" + label.replace("-", "_")
    pos[fid] = {"key": "NATIVE_FILTER", "id": fid, "x": 0, "y": 4, "width": 1, "height": 1,
                "children": [],
                "filters": [{"name": "Streak type", "controlType": "filter_select",
                             "ownState": dict(own), "targets": [tgt]}]}
    r = s.put(BASE + "/api/v1/dashboard/%s" % DID, json={"position_json": json.dumps(pos)}, timeout=60)
    print(label, "->", r.status_code, r.text[:160])
    if r.status_code == 200:
        d2 = s.get(BASE + "/api/v1/dashboard/%s" % DID, timeout=15).json()["result"]
        p2 = json.loads(d2.get("position_json") or "{}")
        print("PERSISTED FILTER:", json.dumps(p2.get(fid))[:400])
        break
