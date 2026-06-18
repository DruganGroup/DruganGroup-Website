import psycopg2
import re

with open('.env') as f:
    content = f.read()

match = re.search(r'DATABASE_URL=(.+)', content)
if match:
    db_url = match.group(1).strip()
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='quotes'")
    print("quotes:", [r[0] for r in cur.fetchall()])
    
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='vehicles'")
    print("vehicles:", [r[0] for r in cur.fetchall()])
