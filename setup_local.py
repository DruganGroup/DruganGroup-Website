import psycopg2

def fix_system_tables_v2():
    print("?? Fixing System Tables (Settings & Audit Logs)...")
    
    try:
        conn = psycopg2.connect(
            dbname="businessbetter", 
            user="postgres", 
            password="admin123", 
            host="localhost", 
            port="5432"
        )
        cur = conn.cursor()

        # 1. Ensure 'settings' table exists
        print(" -> Ensuring 'settings' table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id SERIAL PRIMARY KEY,
                key VARCHAR(50), 
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 2. Insert Global Alert (The Dumb/Safe Way)
        # We check if it exists first. If not, we insert. No errors possible.
        print(" -> Checking for global alert...")
        cur.execute("SELECT id FROM settings WHERE key = 'global_alert'")
        if not cur.fetchone():
            print(" -> Inserting default global alert...")
            cur.execute("INSERT INTO settings (key, value) VALUES ('global_alert', '')")
        else:
            print(" -> Global alert already exists. Skipping.")

        # 3. Create AUDIT_LOGS Table
        print(" -> Ensuring 'audit_logs' table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                action VARCHAR(100),
                details TEXT,
                ip_address VARCHAR(45),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        conn.commit()
        conn.close()
        print("? SUCCESS: System tables ready.")
        
    except Exception as e:
        print(f"? Error: {e}")

if __name__ == "__main__":
    fix_system_tables_v2()