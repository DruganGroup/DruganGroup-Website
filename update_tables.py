import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def update_tables():
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
        cur.execute("ALTER TABLE property_documents ADD COLUMN IF NOT EXISTS visible_to_client BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE quote_documents ADD COLUMN IF NOT EXISTS visible_to_client BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE job_evidence ADD COLUMN IF NOT EXISTS visible_to_client BOOLEAN DEFAULT FALSE")
        conn.commit()
        print("Columns added successfully.")
    except Exception as e:
        print(f"Error updating tables: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    update_tables()
