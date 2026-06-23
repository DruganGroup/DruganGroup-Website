import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def alter_db():
    try:
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            db_url = "postgresql://postgres:@localhost:5432/businessbetter"
        conn = psycopg2.connect(db_url, sslmode='require' if 'render.com' in db_url else None)
        cur = conn.cursor()
        
        # Add service_request_id to jobs if missing
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS service_request_id INTEGER;")
        
        conn.commit()
        print("Database migration successful.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    alter_db()
