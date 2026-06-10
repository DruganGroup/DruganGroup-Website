from db import get_db

conn = get_db()
cur = conn.cursor()
try:
    cur.execute("ALTER TABLE staff_attendance ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'Pending';")
    conn.commit()
    print("Successfully added status column.")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
