"""Publish dashboard 1: PUT its own persisted position_json + published:true."""
import os, re, json
import requests

BASE = "http://10.21.63.187:8088"
PW = os.environ["SUPPW"]
s = requests.Session()
r0 = s.get(BASE + "/login/", timeout=15)
csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text).group(1)
r = s.post(BASE + "/login/", data={"username": "admin", "password": PW, "csrf_token": csrf}, timeout=15)
assert r.status_code in (200, 302), f"login {r.status_code}"
H = {"X-CSRFToken": csrf, "Accept": "application/json"}

d = s.get(BASE + "/api/v1/dashboard/1", headers=H, timeout=30).json()["result"]
pos = d.get("position_json")
if isinstance(pos, str):
    pos = json.loads(pos)

body = {
    "dashboard_title": d["dashboard_title"],
    "published": True,
    "position_json": json.dumps(pos),
    "certification_details": d.get("certification_details") or "",
}
resp = s.put(BASE + "/api/v1/dashboard/1", json=body, headers=H, timeout=60)
print("PUT:", resp.status_code, resp.text[:300])
if resp.ok:
    d2 = s.get(BASE + "/api/v1/dashboard/1", headers=H, timeout=30).json()["result"]
    print("now published:", d2.get("published"))
