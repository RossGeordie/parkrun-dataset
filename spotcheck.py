#!/usr/bin/env python3
import os

import psycopg2

c = psycopg2.connect(host=os.environ["PG_HOST"], port=int(os.environ.get("PG_PORT", "5432")),
                     dbname=os.environ["PG_DATABASE"], user=os.environ["PG_USER"],
                     password=os.environ["PG_PASSWORD"])
cur = c.cursor()
for park, no in [("townmoor", 715), ("leazes", 257), ("dentondene", 157)]:
    cur.execute(
        "SELECT position,name,gender,age_group,time_raw,time_s,club "
        "FROM parkrun.finishers WHERE park=%s AND event_no=%s ORDER BY position LIMIT 2", (park, no))
    rows = cur.fetchall()
    print(f"--- {park} #{no} (top 2 finishers) ---")
    for r in rows:
        print("   ", r)
    cur.execute("SELECT count(*), count(roles) FROM parkrun.volunteers WHERE park=%s AND event_no=%s", (park, no))
    print("    volunteers:", cur.fetchone())
c.close()
