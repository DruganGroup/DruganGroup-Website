from db import get_db
conn = get_db()
cur = conn.cursor()
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'users'")
for row in cur.fetchall():
    print(row)
