import psycopg2
import os

# Render automatically provides this variable in the Shell
DB_URL = os.environ.get(DATABASE_URL)

def reset_settings_table()
    if not DB_URL
        print(❌ Error No DATABASE_URL found. Are you running this in the Render Shell)
        return

    print(🔌 Connecting to Database...)
    try
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor()

        # 1. Drop the old table (The one causing the error)
        print(⚠️  Dropping old 'settings' table...)
        cur.execute(DROP TABLE IF EXISTS settings;)
        
        # 2. Create the new table (With the correct company_id column)
        print(🛠️  Recreating 'settings' table...)
        cur.execute(
            CREATE TABLE settings (
                company_id INTEGER,
                key TEXT,
                value TEXT,
                PRIMARY KEY (company_id, key)
            );
        )
        
        conn.commit()
        conn.close()
        print(✅ SUCCESS Database structure is now correct.)
        
    except Exception as e
        print(f❌ Critical Error {e})

if __name__ == __main__
    reset_settings_table()