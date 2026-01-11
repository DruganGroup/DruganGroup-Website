from db import get_db

def wipe_jobs_and_quotes():
    print("💥 STARTING: Wiping all Quotes, Jobs, and Invoices...")
    conn = get_db()
    cur = conn.cursor()
    try:
        # TRUNCATE removes all data from the table. 
        # CASCADE automatically removes linked data (like quote_items, job_notes).
        tables = ['invoices', 'jobs', 'quotes', 'service_requests', 'staff_timesheets']
        
        for table in tables:
            # Check if table exists first to avoid errors
            cur.execute(f"SELECT to_regclass('public.{table}')")
            if cur.fetchone()[0]:
                print(f"   - Wiping {table}...")
                cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE;")
        
        conn.commit()
        print("\n✅ SUCCESS: All Jobs, Quotes, and Invoices are GONE.")
        print("   Your Dashboard and Calendar should now be empty.")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    wipe_jobs_and_quotes()