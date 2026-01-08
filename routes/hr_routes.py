from flask import Blueprint, render_template, session, redirect, url_for
from db import get_db

# 1. Define the Blueprint
hr_bp = Blueprint('hr_bp', __name__)

# 2. Use @hr_bp.route instead of @app.route
@hr_bp.route('/hr/staff/<int:staff_id>')
def staff_profile(staff_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    # --- A. GET CURRENCY SETTING ---
    cur.execute("""
        SELECT value FROM settings 
        WHERE company_id = %s AND key = 'currency_symbol'
    """, (session.get('company_id'),))
    result = cur.fetchone()
    currency = result[0] if result else '£' # Default to £ if not found
    # -------------------------------
    
    # --- B. BASIC DETAILS (Fixed: Tuple -> Dict) ---
    cur.execute("SELECT * FROM staff WHERE id = %s", (staff_id,))
    staff_raw = cur.fetchone()
    
    if not staff_raw: return "Staff member not found", 404

    # Convert raw data to a dictionary so 'staff.pay_rate' works
    colnames = [desc[0] for desc in cur.description]
    staff = dict(zip(colnames, staff_raw))
    
    # --- C. JOB HISTORY (Fixed: Tuple -> Dict) ---
    cur.execute("""
        SELECT j.id, j.title, j.status, j.start_date, j.site_address 
        FROM jobs j
        JOIN team_members tm ON tm.job_id = j.id 
        WHERE tm.staff_id = %s
        ORDER BY j.start_date DESC LIMIT 10
    """, (staff_id,))
    jobs_raw = cur.fetchall()
    
    job_cols = [desc[0] for desc in cur.description]
    jobs = [dict(zip(job_cols, row)) for row in jobs_raw]

    # --- D. VEHICLE CHECK HISTORY (Fixed: Tuple -> Dict) ---
    cur.execute("""
        SELECT c.date, v.reg_number, c.passed, c.notes 
        FROM vehicle_checks c
        JOIN vehicles v ON c.vehicle_id = v.id
        WHERE c.driver_id = %s
        ORDER BY c.date DESC LIMIT 10
    """, (staff_id,))
    checks_raw = cur.fetchall()
    
    check_cols = [desc[0] for desc in cur.description]
    checks = [dict(zip(check_cols, row)) for row in checks_raw]

    # --- E. RECENT TIMESHEETS (Fixed: Tuple -> Dict) ---
    cur.execute("""
        SELECT date, clock_in, clock_out, total_hours 
        FROM staff_timesheets 
        WHERE staff_id = %s 
        ORDER BY date DESC LIMIT 7
    """, (staff_id,))
    sheets_raw = cur.fetchall()
    
    sheet_cols = [desc[0] for desc in cur.description]
    timesheets = [dict(zip(sheet_cols, row)) for row in sheets_raw]

    conn.close()
    
    return render_template('hr/staff_profile.html', 
                           staff=staff, 
                           jobs=jobs, 
                           checks=checks, 
                           timesheets=timesheets,
                           currency=currency)