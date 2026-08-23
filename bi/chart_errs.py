import re, json
import requests

BASE = "http://10.21.63.187:8088"
PW = open("/home/oc/.suppw").read().strip()
s = requests.Session()
r0 = s.get(BASE + "/login/", timeout=15)
csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text).group(1)
s.post(BASE + "/login/", data={"csrf_token": csrf, "username": "admin", "password": PW}, timeout=15)
H = {"Content-Type": "application/json", "X-CSRFToken": csrf}

for ch in s.get(BASE + "/api/v1/chart/", headers=H, timeout=15).json()["result"]:
    cid = ch["id"]
    fd = {}
    try:
        fd = json.loads(ch.get("params") or "{}")
    except Exception:
        pass
    fd["chart_id"] = cid
    body = {"form_data": fd, "force": False}
    r = s.post(BASE + "/api/v1/chart/data", json=body, headers=H, timeout=90)
    if r.status_code == 200:
        try:
            d = r.json()
            print(cid, ch.get("slice_name"), "OK rows=%d" % (len(d.get("data") or [])))
            continue
        except Exception as e:
            print(cid, ch.get("slice_name"), "decode fail:", e)
    body_txt = (r.text or "")[:300]
    print(cid, ch.get("slice_name"), "FAIL", r.status_code, body_txt)
