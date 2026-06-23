import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def alter_db():
    try:
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            db_url = "postgresql://postgres:@localhost:5432/businessbetter" # Adjust if needed
        conn = psycopg2.connect(db_url, sslmode='require' if 'render.com' in db_url else None)
        cur = conn.cursor()
        
        # Add columns to quotes
        cur.execute("ALTER TABLE quotes ADD COLUMN IF NOT EXISTS needs_followup BOOLEAN DEFAULT FALSE;")
        cur.execute("ALTER TABLE quotes ADD COLUMN IF NOT EXISTS client_response TEXT;")
        
        # Add columns to invoices
        cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS needs_followup BOOLEAN DEFAULT FALSE;")
        cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS client_response TEXT;")
        
        conn.commit()
        print("Database migration successful.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    alter_db()
