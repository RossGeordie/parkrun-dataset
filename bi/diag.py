import re, json, requests
B="http://10.21.63.187:8088"
P=open("/home/oc/.suppw").read().strip()
s=requests.Session()
r0=s.get(B+"/login/",timeout=15)
m=re.search(r'name="csrf_token"[^>]*value="([^"]+)"',r0.text)
cs=m.group(1)
s.post(B+"/login/",data={"csrf_token":cs,"username":"admin","password":P},timeout=15)
H={"Content-Type":"application/json","X-CSRFToken":cs}
ch=s.get(B+"/api/v1/chart/4",headers=H,timeout=15).json()["result"]
print("chart4 keys:",list(ch.keys()))
print("viz_type:",ch.get("viz_type"))
ff=ch.get("form_data")
print("form_data type:",type(ff))
if isinstance(ff,str):
    ff2=json.loads(ff)
else:
    ff2=ff or {}
print("form_data keys:",list(ff2.keys()) if isinstance(ff2,dict) else ff2)
pp=ch.get("params")
if isinstance(pp,str): pp=json.loads(pp)
print("params keys:",list(pp.keys()) if isinstance(pp,dict) else pp)
print(json.dumps(pp)[:1200])
fd=ff2 if isinstance(ff2,dict) else {}
fd.pop("where",None); fd.pop("having",None); fd.pop("extras",None)
vtype=ch.get("viz_type") or fd.get("viz_type")

body={"datasource":{"id":1,"type":"table"},"queries":[],"form_data":fd,"result_format":"json"}
r=s.post(B+"/api/v1/chart/data",json=body,headers=H,timeout=90)
j=r.json()
if r.status_code==200:
    d=j.get("data")
    print("OK vtype=%s keys=%s"%(vtype,list(j.keys())))
else:
    print("FAIL",r.status_code)
    print(json.dumps(j)[:900])
