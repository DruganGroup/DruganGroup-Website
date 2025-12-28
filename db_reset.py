import psycopg2
import os

# Load the secret directly from the server's secure vault
DB_URL = os.environ.get("DATABASE_URL")

def reset_settings_table():
    if not DB_URL:
        print("Error: No DATABASE_URL found. Environment variables are missing.")
        return

    print("Connecting to Database securely...")
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor()

        print("Dropping old settings table...")
        cur.execute("DROP TABLE IF EXISTS settings;")
        
        print("Recreating settings table with correct columns...")
        cur.execute("""
            CREATE TABLE settings (
                company_id INTEGER,
                key TEXT,
                value TEXT,
                PRIMARY KEY (company_id, key)
            );
        """)
        
        conn.commit()
        conn.close()
        print("SUCCESS: Database structure is fixed.")
        
    except Exception as e:
        print(f"Critical Error: {e}")

if __name__ == "__main__":
    reset_settings_table()