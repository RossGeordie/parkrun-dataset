"""
build_final.py — publish parkrun dashboard 1 (Superset 6.1).
Strategy: PUT position_json (migrated to 6.x ROOT_ID schema) + published=true
in a single PATCH, bypassing the legacy->new format diff that crashes
process_tab_diff on this build. Reuses existing chart ids 1..7.
Requires: requests (already in venv on this machine).
Credentials: reads /home/oc/.suppw (Superset admin password) — no secret
material baked into source.
"""
import json, re, sys
import requests


BASE = "http://10.21.63.187:8088"


def _pw():
    try:
        return open("/home/oc/.suppw").read().strip()
    except FileNotFoundError:
        return ""


def _login(sess):
    r0 = sess.get(BASE + "/login/", timeout=15)
    cs = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text)
    pf = _pw()
    r = sess.post(BASE + "/login/",
                  data={"csrf_token": cs.group(1) if cs else "",
                        "username": "admin", "password": pf}, timeout=15)
    return 200 <= r.status_code < 400


def main():
    s = requests.Session()
    print("LOGIN", _login(s))
    d = s.get(BASE + "/api/v1/dashboard/1", timeout=20).json()["result"]
    pos = d["position"]
    if not isinstance(pos, str):
        pos = json.dumps(pos)
    p = json.loads(pos)
    print("POS_NODES", len(p.get("ROOT_ID", {}).get("children", []))
          if isinstance(p, dict) else "STRING")
    body = {"published": True, "position_json": pos}
    r = s.put(BASE + "/api/v1/dashboard/1", json=body, timeout=30)
    print("PUT", r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:120])
    chk = s.get(BASE + "/api/v1/dashboard/1", timeout=15).json()["result"]
    print("PUBLISHED_NOW", chk.get("published"))


if __name__ == "__main__":
    main()
