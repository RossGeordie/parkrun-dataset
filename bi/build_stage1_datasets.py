"""Stage 1: create analytics datasets in Superset (rollup_event, v_person_streaks)."""
import requests, re, json, sys
sys.path.insert(0, "/home/oc/Documents/AI/parkrun-dataset/bi")

BASE = "http://10.21.63.187:8088"

def login():
    s = requests.Session()
    r0 = s.get(f"{BASE}/login/", timeout=15)
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text).group(1)
    s.headers["X-CSRFToken"] = csrf
    r = s.post(f"{BASE}/login/", data={"csrf_token": csrf,
                                       "username": "admin",
                                       "password": open("/home/oc/.suppw").read().strip()}, timeout=15)
    assert r.status_code in (200, 302), f"login {r.status_code}: {r.text[:200]}"
    return s

s = login()

want = [
    ("analytics", "rollup_event"),
    ("analytics", "v_person_streaks"),
]

created = {}
for schema, table in want:
    r = s.post(f"{BASE}/api/v1/dataset/", json={"database": 1, "schema": schema, "table_name": table}, timeout=60)
    print(f"create {schema}.{table} -> {r.status_code}")
    if r.status_code not in (200, 201):
        print(r.text[:400])
        continue
    ds = r.json()
    created[f"{schema}.{table}"] = ds["id"]
    cols = [c["name"] for c in ds.get("columns", [])]
    mets = [m["name"] for m in ds.get("metrics", [])]
    print(f"  id={ds['id']} cols={cols}")
    print(f"  metrics={mets}")

print("CREATED=" + json.dumps(created))
