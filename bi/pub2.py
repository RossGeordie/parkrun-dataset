import re, json, requests
B="http://10.21.63.187:8088"
P=open("/home/oc/.suppw").read().strip()
s=requests.Session()
r0=s.get(B+"/login/",timeout=15)
m=re.search(r'name="csrf_token"[^>]*value="([^"]+)"',r0.text)
cs=m.group(1)
s.post(B+"/login/",data={"csrf_token":cs,"username":"admin","password":P},timeout=15)
H={"Content-Type":"application/json","X-CSRFToken":cs}
d=s.get(B+"/api/v1/dashboard/1",headers=H,timeout=15).json()["result"]
drop={"changed_by","changed_by_name","changed_on","created_by","created_on_delta_humanized",
"changed_on_delta_humanized","charts","uuid","owner","owner_name","published_dttm",
"id","owners","theme","thumbnail_url","url"}
body={k:v for k,v in d.items() if k not in drop}
body["published"]=True
r=s.put(B+"/api/v1/dashboard/1",json=body,headers=H,timeout=60)
print("PUT:",r.status_code,r.text[:300])
d2=s.get(B+"/api/v1/dashboard/1",headers=H,timeout=15).json()["result"]
print("published now:",d2.get("published"))
for c in d2.get("charts",[]): print(" chart",c.get("id"),c.get("name"))
