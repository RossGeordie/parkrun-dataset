import re, json, requests
B="http://10.21.63.187:8088"
P=open("/home/oc/.suppw").read().strip()
s=requests.Session()
r0=s.get(B+"/login/",timeout=15)
m=re.search(r'name="csrf_token"[^>]*value="([^"]+)"',r0.text)
cs=m.group(1)
s.post(B+"/login/",data={"csrf_token":cs,"username":"admin","password":P},timeout=15)
H={"Content-Type":"application/json","X-CSRFToken":cs}
chs=s.get(B+"/api/v1/chart/",headers=H,timeout=15).json()["result"]
out={}
for c in chs:
    cid=c["id"]; name=c.get("slice_name")
    ch=s.get(B+"/api/v1/chart/%d"%cid,headers=H,timeout=15).json()["result"]
    fd=ch.get("params")
    if isinstance(fd,str): fd=json.loads(fd)
    if not isinstance(fd,dict): fd={}
    ds=ch.get("datasource") or {"id":1,"type":"table"}
    body={"datasource":ds,"queries":[],
          "form_data":{k:v for k,v in fd.items() if k not in ("where","having","extras")},"result_format":"json"}
    r=s.post(B+"/api/v1/chart/data",json=body,headers=H,timeout=90)
    j=r.json()
    if r.status_code==200:
        d=j.get("data")
        if isinstance(d,list): n=len(d)
        elif isinstance(d,dict): n=len(d.get("data") if isinstance(d.get("data"),list) else d)
        else: n="?"
        out[cid]="OK name=%s rows=%s"%(name,n)
    else:
        msg=(j.get("error") or {}).get("message") if isinstance(j.get("error"),dict) else (j.get("message") or j.get("error"))
        out[cid]="FAIL %s :: %s"%(name,msg)
print(json.dumps(out,indent=1))
