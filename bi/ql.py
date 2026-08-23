import re, json
import requests

BASE = "http://10.21.63.187:8088"
PW = open("/home/oc/.suppw").read().strip()
s = requests.Session()
r0 = s.get(BASE + "/login/", timeout=15)
csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text).group(1)
s.post(BASE + "/login/", data={"csrf_token": csrf, "username": "admin", "password": PW}, timeout=15)
H = {"Content-Type": "application/json", "X-CSRFToken": csrf}

body = {
    "queries": [{
        "time_range": "No filter",
        "metrics": ["SUM(parkrun_id)"],
        "granularity_sqla": None,
        "extras": {"time_grain_sqla": None},
        "order_by_columns": [],
        "groupby": [],
        "having": "",
        "where": "",
        "columns": [],
        "is_crossjoin": False,
    }],
    "result_format": "table"
}
H2 = dict(H)
r = s.post(BASE + "/api/v1/dataset/query", json=body, headers=H2, timeout=60)
print("dataset query:", r.status_code)
try:
    d = r.json()
    print("rows:", json.dumps(d.get("result"), default=str)[:400])
    print("errors:", d.get("errors"))
except Exception as e:
    print(r.text[:400])
