import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def migrate():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        conn = psycopg2.connect(db_url, sslmode='require')
    else:
        conn = psycopg2.connect(
            dbname=os.environ.get("DB_NAME", "businessbetter"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", ""),
            host=os.environ.get("DB_HOST", "localhost"),
            port=os.environ.get("DB_PORT", "5432")
        )
    
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE job_materials ADD COLUMN IF NOT EXISTS cost_price NUMERIC DEFAULT 0;")
        conn.commit()
        print("Successfully added cost_price to job_materials")
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    migrate()
