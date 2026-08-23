"""Probe Superset 6 dashboard endpoints + publish mechanisms for dashboard 1."""
import re, json
import requests

BASE = "http://10.21.63.187:8088"
PW = open("/home/oc/.suppw").read().strip()
s = requests.Session()
r0 = s.get(BASE + "/login/", timeout=15)
csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text).group(1)
r = s.post(BASE + "/login/", data={"username": "admin", "password": PW, "csrf_token": csrf}, timeout=15)
if not r.url.endswith("/"):
    raise SystemExit("login failed")
print("authed")

# 0) current state of dashboard 1
d = s.get(BASE + "/api/v1/dashboard/1", headers={"X-CSRFToken": csrf}, timeout=15)
cur = d.json()["result"]
print("d1:", {k: cur.get(k) for k in ("dashboard_title", "published", "status", "url")})

def try_call(method, path, **kw):
    try:
        resp = s.request(method, BASE + path, headers={"X-CSRFToken": csrf, "Content-Type": "application/json"}, timeout=20, **kw)
    except Exception as e:
        print(f"{method:6} {path:40} EXC {e}")
        return None
    snippet = resp.text[:160].replace("\n", " ")
    print(f"{method:6} {path:40} {resp.status_code} {snippet}")
    return resp

# 1) PATCH on dashboard root
try_call("PATCH", "/api/v1/dashboard/1", json={"published": True})
try_call("PATCH", "/api/v1/dashboard/1", json={"status": "published"})

# 2) common publish-ish subresources
for p in ["/api/v1/dashboard/1/publish", "/api/v1/dashboard/1/unpublish",
          "/api/v1/dashboard/1/release", "/api/v1/dashboard/1/deploy",
          "/api/v1/dashboard/1/lock", "/api/v1/dashboard/1/refresh"]:
    try_call("POST", p)
