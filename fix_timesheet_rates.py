import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def migrate_timesheets():
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
        # Add columns
        cur.execute("ALTER TABLE staff_timesheets ADD COLUMN IF NOT EXISTS pay_rate REAL;")
        cur.execute("ALTER TABLE staff_timesheets ADD COLUMN IF NOT EXISTS pay_model VARCHAR(50);")
        
        cur.execute("ALTER TABLE staff_attendance ADD COLUMN IF NOT EXISTS pay_rate REAL;")
        cur.execute("ALTER TABLE staff_attendance ADD COLUMN IF NOT EXISTS pay_model VARCHAR(50);")

        # Update existing timesheets with current staff rates
        cur.execute("""
            UPDATE staff_timesheets t
            SET pay_rate = s.pay_rate, pay_model = s.pay_model
            FROM staff s
            WHERE t.staff_id = s.id AND t.pay_rate IS NULL;
        """)

        # Update existing attendance with current staff rates
        cur.execute("""
            UPDATE staff_attendance a
            SET pay_rate = s.pay_rate, pay_model = s.pay_model
            FROM staff s
            WHERE a.staff_id = s.id AND a.pay_rate IS NULL;
        """)

        # Create trigger function
        cur.execute("""
            CREATE OR REPLACE FUNCTION snapshot_staff_rate()
            RETURNS TRIGGER AS $$
            BEGIN
                IF NEW.pay_rate IS NULL THEN
                    SELECT pay_rate, pay_model INTO NEW.pay_rate, NEW.pay_model
                    FROM staff WHERE id = NEW.staff_id;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # Create triggers
        cur.execute("""
            DROP TRIGGER IF EXISTS trg_snapshot_timesheet_rate ON staff_timesheets;
            CREATE TRIGGER trg_snapshot_timesheet_rate
            BEFORE INSERT ON staff_timesheets
            FOR EACH ROW
            EXECUTE FUNCTION snapshot_staff_rate();
        """)

        cur.execute("""
            DROP TRIGGER IF EXISTS trg_snapshot_attendance_rate ON staff_attendance;
            CREATE TRIGGER trg_snapshot_attendance_rate
            BEFORE INSERT ON staff_attendance
            FOR EACH ROW
            EXECUTE FUNCTION snapshot_staff_rate();
        """)

        conn.commit()
        print("Successfully migrated timesheets and attendance rates.")
    except Exception as e:
        print(f"Error migrating: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    migrate_timesheets()
