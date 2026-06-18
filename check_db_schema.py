import psycopg2, os
from dotenv import load_dotenv

load_dotenv('.env')

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

# Check quotes columns
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='quotes'")
print("quotes:", [row[0] for row in cur.fetchall()])

# Check vehicles columns
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='vehicles'")
print("vehicles:", [row[0] for row in cur.fetchall()])
