import datetime, psycopg2
conn=psycopg2.connect(host="superset_db",port=5432,dbname="superset",user="superset",password="REPLACE_WITH_ENV")
cur=c