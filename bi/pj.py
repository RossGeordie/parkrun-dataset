import re,json,requests
B="http://10.21.63.187:8088"
P=open("/home/oc/.suppw").read().strip()
s=requests.Session()
r0=s.get(B+"/login/",timeout=15)
m=re.search(r'name="csrf_token"[^>]*value="([^"]+)"',r0.text)
cs=m.group(1)
s.post(B+"/login/",data={"csrf_token":cs,"username":"admin","password":P},timeout=15)
H={"Content-Type":"application/json","X-CSRFToken":cs}
d=s.get(B+"/api/v1/dashboard/1",headers=H,timeout=15).json()["result"]
pj=d.get("position_json") or {}
if isinstance(pj,str): pj=json.loads(pj)
print("pos keys:",list(pj.keys()))
for k,v in list(pj.items())[:4]:
    print(k, json.dumps(v)[:120])
print("charts:",[(c.get("id"),c.get("name")) for c in d.get("charts",[])])