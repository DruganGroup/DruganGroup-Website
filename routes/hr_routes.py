from flask import Blueprint, render_template, session, redirect, url_for
from db import get_db

hr_bp = Blueprint('hr_bp', __name__)

@hr_bp.route('/hr/staff/<int:staff_id>')
def staff_profile(staff_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    # --- A. GET CURRENCY ---
    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'currency_symbol'", (session.get('company_id'),))
    result = cur.fetchone()
    currency = result[0] if result else '£'
    
    # --- B. BASIC DETAILS ---
    cur.execute("SELECT * FROM staff WHERE id = %s", (staff_id,))
    staff_raw = cur.fetchone()
    if not staff_raw: return "Staff member not found", 404
    colnames = [desc[0] for desc in cur.description]
    staff = dict(zip(colnames, staff_raw))
    
    # --- C. JOB HISTORY (FIXED: Using 'jobs' table instead of 'team_members') ---
    # We look for jobs where they are the Lead Engineer
    cur.execute("""
        SELECT id, ref as title, status, start_date, site_address 
        FROM jobs 
        WHERE engineer_id = %s
        ORDER BY start_date DESC LIMIT 10
    """, (staff_id,))
    jobs_raw = cur.fetchall()
    # Simple mapping since we selected specific columns
    jobs = [{'id': r[0], 'title': r[1], 'status': r[2], 'start_date': r[3], 'site_address': r[4]} for r in jobs_raw]

    # --- D. VEHICLE CHECK HISTORY (FIXED: Using 'maintenance_logs') ---
    # We look for logs created by the user (linked via vehicle or just general logs if we tracked user_id there)
    # Note: maintenance_logs doesn't store 'who' did it in a column, but we can filter by type
    # For now, we show checks for the vehicle currently assigned to them
    cur.execute("SELECT id, reg_plate FROM vehicles WHERE assigned_driver_id = %s", (staff_id,))
    vehicle = cur.fetchone()
    
    checks = []
    if vehicle:
        v_id, v_reg = vehicle
        cur.execute("""
            SELECT date, description 
            FROM maintenance_logs 
            WHERE vehicle_id = %s AND (type LIKE '%%Check%%' OR type = 'Defect')
            ORDER BY date DESC LIMIT 10
        """, (v_id,))
        for r in cur.fetchall():
            # Parse the description to see if it passed
            passed = False if "Defect" in r[1] or "Failed" in r[1] else True
            checks.append({'date': r[0], 'reg_number': v_reg, 'passed': passed, 'notes': r[1]})

    # --- E. RECENT TIMESHEETS (FIXED: Using 'total_hours') ---
    cur.execute("""
        SELECT date, clock_in, clock_out, total_hours 
        FROM staff_timesheets 
        WHERE staff_id = %s 
        ORDER BY date DESC LIMIT 7
    """, (staff_id,))
    sheets_raw = cur.fetchall()
    
    # Custom mapping for timesheets
    timesheets = []
    for r in sheets_raw:
        c_in = r[1].strftime('%H:%M') if r[1] else '--:--'
        c_out = r[2].strftime('%H:%M') if r[2] else '--:--'
        timesheets.append({'date': r[0], 'clock_in': c_in, 'clock_out': c_out, 'total_hours': r[3]})

    conn.close()
    
    return render_template('hr/staff_profile.html', 
                           staff=staff, 
                           jobs=jobs, 
                           checks=checks, 
                           timesheets=timesheets,
                           currency=currency)