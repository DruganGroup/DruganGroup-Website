"""
Database maintenance migration.
Run once:  python db_fix_columns.py
Safe to re-run (idempotent). Backs up dropped tables to JSON first.

What it does:
  1. ADD missing columns the app code expects:
       - maintenance_logs.mileage  (van check / fuel logging)
       - staff_timesheets.status   (job clock / timesheet approval)
  2. KEEP + ensure site_diary table exists (now used by the new Site Diary feature).
  3. BACK UP then DROP 4 confirmed-unused tables:
       - banned_ips           (security feature never wired up)
       - modules              (replaced by 'modules' column on subscriptions/plans)
       - plugin_licenses       (never implemented; Stripe handles licensing)
       - client_notifications  (replaced by request_updates + email)
"""
import json
import datetime
from db import get_db

# Tables we are removing (confirmed unused across all .py + templates).
DROP_TABLES = ["banned_ips", "modules", "plugin_licenses", "client_notifications"]


def _json_default(o):
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    return str(o)


def backup_table(conn, cur, table):
    """Dump a table's rows to a timestamped JSON file before dropping.
    Rolls back on failure so the aborted transaction doesn't block the DROP."""
    try:
        cur.execute(f"SELECT * FROM {table}")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"static/backups/{table}_{stamp}.json"
        with open(fname, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, default=_json_default)
        print(f"  Backed up {len(rows)} row(s) -> {fname}")
        return True
    except Exception as e:
        conn.rollback()  # clear the aborted transaction (e.g. table already gone)
        print(f"  WARN: could not back up {table}: {e}")
        return False



def run():
    conn = get_db()
    if not conn:
        print("DB connection failed.")
        return
    cur = conn.cursor()

    # 1. ADD MISSING COLUMNS
    add_cols = [
        "ALTER TABLE maintenance_logs ADD COLUMN IF NOT EXISTS mileage INTEGER;",
        "ALTER TABLE staff_timesheets ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'Approved';",
    ]
    for sql in add_cols:
        try:
            cur.execute(sql); conn.commit()
            print(f"OK: {sql}")
        except Exception as e:
            conn.rollback(); print(f"FAIL: {sql} -> {e}")

    # 2. ENSURE site_diary EXISTS (we are keeping & using this)
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS site_diary (
                id SERIAL PRIMARY KEY,
                job_id INTEGER,
                staff_name TEXT,
                entry_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        print("OK: site_diary table present (kept for Site Diary feature).")
    except Exception as e:
        conn.rollback(); print(f"FAIL: site_diary ensure -> {e}")

    # 3. BACK UP + DROP UNUSED TABLES
    for table in DROP_TABLES:
        print(f"Removing unused table: {table}")
        backup_table(conn, cur, table)

        try:
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
            conn.commit()
            print(f"  DROPPED: {table}")
        except Exception as e:
            conn.rollback(); print(f"  FAIL drop {table}: {e}")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    run()
