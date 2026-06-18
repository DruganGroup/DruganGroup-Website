import sys
from app import app
from db import get_db

with app.app_context():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT message, traceback FROM system_logs ORDER BY created_at DESC LIMIT 5")
    for row in cur.fetchall():
        print("MESSAGE:", row[0])
        print("TRACEBACK:", row[1])
        print("-" * 50)
