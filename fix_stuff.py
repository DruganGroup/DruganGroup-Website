from db import get_db
from app import app

def ultimate_schema_sync():
    print("🚀 STARTING ULTIMATE SCHEMA SYNC...")
    
    # Define the Target Schema: Table Name -> List of specific columns needed
    schema_map = {
        "vehicles": [
            ("reg_number", "TEXT"),
            ("make_model", "TEXT"),
            ("status", "TEXT DEFAULT 'Active'"),
            ("mot_expiry", "DATE"),
            ("tax_expiry", "DATE"),
            ("ins_expiry", "DATE"),
            ("driver_id", "INTEGER"),
            ("assigned_driver_id", "INTEGER"), # Sometimes used distinctly
            ("mileage", "INTEGER DEFAULT 0"),
            ("fuel_type", "TEXT"),
            ("daily_cost", "NUMERIC(10,2) DEFAULT 0.00"),
            ("vin", "TEXT"),
            ("tracker_url", "TEXT"),
            ("purchase_date", "DATE"),
            ("last_service_date", "DATE")
        ],
        "clients": [
            ("site_address", "TEXT"),
            ("billing_address", "TEXT"),
            ("gate_code", "TEXT"),
            ("key_info", "TEXT"),
            ("emergency_contact", "TEXT"),
            ("notes", "TEXT"),
            ("status", "TEXT DEFAULT 'Active'")
        ],
        "jobs": [
            ("site_address", "TEXT"),
            ("description", "TEXT"),
            ("title", "TEXT"),
            ("start_date", "DATE"),
            ("end_date", "DATE"),
            ("manager_id", "INTEGER"),
            ("team_id", "INTEGER"),
            ("staff_id", "INTEGER"),
            ("client_id", "INTEGER"),
            ("quote_total", "NUMERIC(10,2)"),
            ("cost_total", "NUMERIC(10,2)"),
            ("status", "TEXT DEFAULT 'Pending'")
        ],
        "staff": [
            ("pay_rate", "NUMERIC(10,2) DEFAULT 0.00"),
            ("pay_model", "TEXT DEFAULT 'Hour'"),
            ("tax_id", "TEXT"),
            ("access_level", "TEXT DEFAULT 'None'"),
            ("address", "TEXT"),
            ("phone", "TEXT"),
            ("dept", "TEXT"),
            ("employment_type", "TEXT"),
            ("position", "TEXT")
        ],
        "staff_timesheets": [
            ("staff_id", "INTEGER"),
            ("job_id", "INTEGER"),
            ("date", "DATE DEFAULT CURRENT_DATE"),
            ("clock_in", "TIMESTAMP"),
            ("clock_out", "TIMESTAMP"),
            ("total_hours", "NUMERIC(5,2) DEFAULT 0.00"),
            ("lat_in", "NUMERIC(10,8)"),
            ("lng_in", "NUMERIC(11,8)"),
            ("lat_out", "NUMERIC(10,8)"),
            ("lng_out", "NUMERIC(11,8)"),
            ("is_approved", "BOOLEAN DEFAULT FALSE")
        ],
        "team_members": [
            ("job_id", "INTEGER"), # The critical missing link for HR Profile
            ("team_id", "INTEGER"),
            ("staff_id", "INTEGER")
        ],
        "maintenance_logs": [
            ("litres", "NUMERIC(10,2)"),
            ("fuel_type", "TEXT"),
            ("odometer", "INTEGER"),
            ("cost", "NUMERIC(10,2)"),
            ("description", "TEXT"),
            ("type", "TEXT")
        ]
    }

    with app.app_context():
        conn = get_db()
        cur = conn.cursor()

        for table, columns in schema_map.items():
            print(f"📦 Checking table: {table}")
            
            # 1. Ensure Table Exists
            try:
                cur.execute(f"CREATE TABLE IF NOT EXISTS {table} (id SERIAL PRIMARY KEY, company_id INTEGER);")
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"   ⚠️ Could not create table {table}: {e}")

            # 2. Loop through every column and try to add it
            for col_name, col_type in columns:
                try:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type};")
                    conn.commit()
                    print(f"   ➕ Added column: {col_name}")
                except Exception:
                    # If error, it means column likely exists. We rollback and skip.
                    conn.rollback()
                    pass
        
        conn.close()
        print("\n✅ ULTIMATE SYNC COMPLETE. All tables and columns are now present.")

if __name__ == "__main__":
    ultimate_schema_sync()