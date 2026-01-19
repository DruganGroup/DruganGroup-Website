from db import get_db

def xray_vision():
    print("🔍 SCANNING TIMESHEETS TABLE...")
    conn = get_db()
    cur = conn.cursor()

    # 1. Get your Staff ID
    # Assuming you are logged in as the user with ID 1 (or change the email to match yours)
    cur.execute("SELECT id, name FROM staff LIMIT 1") 
    staff = cur.fetchone()
    
    if not staff:
        print("❌ Error: No staff found in database.")
        return
        
    staff_id, staff_name = staff
    print(f"👤 Staff Identified: {staff_name} (ID: {staff_id})")

    # 2. Check the raw timesheet data
    print("\n📋 LATEST 5 TIMESHEET ENTRIES:")
    print(f"{'ID':<5} | {'Job ID':<8} | {'Clock In':<25} | {'Clock Out':<25} | {'Status'}")
    print("-" * 80)
    
    cur.execute("""
        SELECT id, job_id, clock_in, clock_out 
        FROM staff_timesheets 
        ORDER BY id DESC LIMIT 5
    """)
    
    rows = cur.fetchall()
    if not rows:
        print("   (No records found)")
    
    for r in rows:
        tid, jid, cin, cout = r
        status = "🔴 CLOSED" if cout else "🟢 OPEN (Active)"
        print(f"{tid:<5} | {jid:<8} | {str(cin):<25} | {str(cout) if cout else 'None':<25} | {status}")

    print("-" * 80)
    print("ANALYSIS:")
    
    # Check for the specific problem
    open_sessions = [r for r in rows if r[3] is None]
    if open_sessions:
        print(f"✅ GOOD NEWS: There is an OPEN session (ID: {open_sessions[0][0]}).")
        print("   The issue is in the Python code (route) not seeing it.")
    else:
        print("⚠️ BAD NEWS: All sessions are CLOSED.")
        print("   The database is auto-filling the 'Clock Out' time immediately.")
        print("   We need to fix the INSERT statement.")

    conn.close()

if __name__ == "__main__":
    xray_vision()