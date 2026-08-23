import re, json, requests
B="http://10.21.63.187:8088"
P=open("/home/oc/.suppw").read().strip()
s=requests.Session()
r0=s.get(B+"/login/",timeout=15)
m=re.search(r'...(