import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

db_url = os.environ.get("DATABASE_URL")
if not db_url:
    conn = psycopg2.connect(
        dbname=os.environ.get("DB_NAME", "businessbetter"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432")
    )
else:
    conn = psycopg2.connect(db_url, sslmode='require')

cur = conn.cursor()
try:
    print("Truncating clients cascade...")
    cur.execute("TRUNCATE TABLE clients CASCADE;")
    conn.commit()
    print("Success!")
except Exception as e:
    conn.rollback()
    print(f"Error: {e}")
finally:
    conn.close()
