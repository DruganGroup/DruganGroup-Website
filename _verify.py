from db import get_db

c = get_db()
cur = c.cursor()

cur.execute("""
    SELECT table_name FROM information_schema.tables
    WHERE table_schema='public'
    AND table_name IN ('banned_ips','modules','plugin_licenses','client_notifications','site_diary')
""")
print("Target tables still present:", [r[0] for r in cur.fetchall()])

cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='maintenance_logs' AND column_name='mileage'")
print("maintenance_logs.mileage:", "YES" if cur.fetchall() else "MISSING")

cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='staff_timesheets' AND column_name='status'")
print("staff_timesheets.status:", "YES" if cur.fetchall() else "MISSING")

c.close()
