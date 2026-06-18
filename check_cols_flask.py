import sys
from app import app
from db import get_db

with app.app_context():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='bb_support_tickets'")
    print(cur.fetchall())
