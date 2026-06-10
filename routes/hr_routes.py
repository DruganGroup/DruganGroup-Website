import os
from datetime import datetime, timedelta
from flask import Blueprint, render_template, session, redirect, url_for, request, current_app, flash
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from db import get_db, get_site_config, allowed_file, ALLOWED_EXTENSIONS
from services.enforcement import check_limit
import secrets
import string
from email_service import send_company_email
from itertools import groupby

hr_bp = Blueprint('hr_bp', __name__)

# --- HELPER: CALCULATE WAGE ---
def calculate_wage(hours, rate, model):
    if not hours or not rate: return 0.00
    hours = float(hours)
    rate = float(rate)
    
    if model == 'Hour':
        return round(hours * rate, 2)
    elif model == 'Day':
        # Assuming 8 hour standard day for "Day Rate" calc, or 1 full day if worked > 4 hours
        # Simple method: (Rate / 8) * Hours
        return round((rate / 8) * hours, 2)
    return 0.00 # Salary/Yearly usually doesn't track per-hour costs here

# --- 1. HR DASHBOARD ---
@hr_bp.route('/hr/timesheets', methods=['GET'])
def review_timesheets():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db()
    cur = conn.cursor()
    
    # We fetch daily attendance to approve the day
    cur.execute("""
        SELECT a.id, s.name, a.date, a.total_hours, a.status, a.staff_id
        FROM staff_attendance a
        JOIN staff s ON a.staff_id = s.id
        WHERE s.company_id = %s
        ORDER BY a.date DESC
    """, (comp_id,))
    
    timesheets = []
    for r in cur.fetchall():
        day_hours = float(r[3] or 0)
        staff_id = r[5]
        date = r[2]
        
        # Fetch Job Hours and Details for that day
        cur.execute("""
            SELECT j.ref, t.total_hours, t.clock_in, t.clock_out, j.id
            FROM staff_timesheets t 
            JOIN jobs j ON t.job_id = j.id
            WHERE t.staff_id = %s AND t.date = %s
        """, (staff_id, date))
        
        jobs_worked = []
        job_hours = 0.0
        for jt in cur.fetchall():
            hours = float(jt[1] or 0)
            job_hours += hours
            c_in = jt[2].strftime('%H:%M') if jt[2] else '-'
            c_out = jt[3].strftime('%H:%M') if jt[3] else '-'
            jobs_worked.append({
                'ref': jt[0],
                'hours': hours,
                'clock_in': c_in,
                'clock_out': c_out,
                'id': jt[4]
            })
            
        unallocated = max(0, day_hours - job_hours)
        
        timesheets.append({
            'id': r[0], 'staff_name': r[1], 'date': date, 
            'hours': day_hours, 'job_hours': job_hours, 'unallocated': unallocated,
            'status': r[4] or 'Pending',
            'jobs_worked': jobs_worked
        })
        
    conn.close()
    return render_template('hr/timesheets.html', timesheets=timesheets)

@hr_bp.route('/hr/timesheets/approve', methods=['POST'])
def approve_timesheet():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    att_id = request.form.get('attendance_id')
    action = request.form.get('action') # 'approve' or 'reject'
    
    conn = get_db()
    cur = conn.cursor()
    try:
        new_status = 'Approved' if action == 'approve' else 'Rejected'
        # Approve the Day
        cur.execute("UPDATE staff_attendance SET status = %s WHERE id = %s", (new_status, att_id))
        
        # Also auto-approve all underlying job timesheets for that day
        if new_status == 'Approved':
            cur.execute("SELECT staff_id, date FROM staff_attendance WHERE id = %s", (att_id,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE staff_timesheets SET status = 'Approved' WHERE staff_id = %s AND date = %s", (row[0], row[1]))
                
        conn.commit()
        flash(f"Day Shift marked as {new_status}.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error updating timesheet: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('hr_bp.review_timesheets'))

@hr_bp.route('/hr/leave', methods=['GET', 'POST'])
def manage_leave():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    comp_id = session.get('company_id')
    
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS staff_leave (
                id SERIAL PRIMARY KEY,
                company_id INTEGER,
                staff_id INTEGER,
                start_date DATE,
                end_date DATE,
                reason VARCHAR(100),
                status VARCHAR(50) DEFAULT 'Approved',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    except:
        conn.rollback()

    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        reason = request.form.get('reason')
        try:
            # 1. Insert into staff_leave
            cur.execute("""
                INSERT INTO staff_leave (company_id, staff_id, start_date, end_date, reason, status)
                VALUES (%s, %s, %s, %s, %s, 'Approved')
            """, (comp_id, staff_id, start_date, end_date, reason))
            
            # 2. Automated Holiday Payroll & Auto-Cap Protection
            if reason in ['Annual Leave', 'Holiday']:
                # Calculate exactly how much holiday they have currently banked
                cur.execute("""
                    SELECT COALESCE(SUM(total_hours), 0) FROM staff_attendance 
                    WHERE staff_id = %s AND status = 'Approved' AND EXTRACT(YEAR FROM date) = EXTRACT(YEAR FROM CURRENT_DATE) AND notes != 'Annual Leave'
                """, (staff_id,))
                worked_hours_ytd = float(cur.fetchone()[0] or 0)
                
                cur.execute("""
                    SELECT COALESCE(SUM(total_hours), 0) FROM staff_attendance 
                    WHERE staff_id = %s AND notes = 'Annual Leave' AND status = 'Approved' AND EXTRACT(YEAR FROM date) = EXTRACT(YEAR FROM CURRENT_DATE)
                """, (staff_id,))
                holiday_taken_ytd = float(cur.fetchone()[0] or 0)
                
                # Accrued is 12.07% of worked hours
                holiday_balance = (worked_hours_ytd * 0.1207) - holiday_taken_ytd
                
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                delta = end_dt - start_dt
                
                # Loop through each day of the leave
                for i in range(delta.days + 1):
                    current_day = start_dt + timedelta(days=i)
                    # Skip weekends (5=Sat, 6=Sun)
                    if current_day.weekday() < 5:
                        if holiday_balance > 0:
                            pay_hours = min(8.0, holiday_balance)
                            cur.execute("""
                                INSERT INTO staff_attendance (staff_id, date, total_hours, notes, status, clock_in)
                                VALUES (%s, %s, %s, 'Annual Leave', 'Approved', CURRENT_TIMESTAMP)
                            """, (staff_id, current_day.strftime('%Y-%m-%d'), pay_hours))
                            holiday_balance -= pay_hours
                            
            conn.commit()
            flash("✅ Leave recorded successfully.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"Error recording leave: {e}", "error")
        return redirect(url_for('hr_bp.manage_leave'))

    cur.execute("SELECT id, name FROM staff WHERE company_id = %s AND status = 'Active'", (comp_id,))
    staff = cur.fetchall()
    
    cur.execute("""
        SELECT l.id, s.name, l.start_date, l.end_date, l.reason, l.status 
        FROM staff_leave l
        JOIN staff s ON l.staff_id = s.id
        WHERE l.company_id = %s
        ORDER BY l.start_date DESC
    """, (comp_id,))
    leaves = cur.fetchall()
    
    conn.close()
    return render_template('hr/leave.html', staff=staff, leaves=leaves)

@hr_bp.route('/hr/dashboard')
def hr_dashboard():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    # SMART MIGRATION: Check if profile_photo exists, if not add it
    try:
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS profile_photo TEXT;")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS tax_limit NUMERIC DEFAULT 0;")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS ni_limit NUMERIC DEFAULT 0;")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS holiday_entitled BOOLEAN DEFAULT TRUE;")
        conn.commit()
    except:
        conn.rollback()

    cur.execute("SELECT id, name, position, dept, pay_rate, pay_model, access_level, email, phone, employment_type, address, tax_id, driving_license, profile_photo, tax_limit, ni_limit, holiday_entitled FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    cols = [desc[0] for desc in cur.description]
    staff = [dict(zip(cols, row)) for row in cur.fetchall()]
    
    conn.close()
    return render_template('finance/finance_hr.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

@hr_bp.route('/hr/staff/<int:staff_id>')
def staff_profile(staff_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get Currency
    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'currency_symbol'", (session.get('company_id'),))
    res = cur.fetchone()
    currency = res[0] if res else '£'
    
    # Get Staff Details
    cur.execute("SELECT * FROM staff WHERE id = %s", (staff_id,))
    staff_raw = cur.fetchone()
    if not staff_raw: 
        conn.close()
        return "Staff member not found", 404
        
    colnames = [desc[0] for desc in cur.description]
    staff = dict(zip(colnames, staff_raw))
    
    # --- HOLIDAY CALCULATION ---
    # Total hours worked this year
    cur.execute("""
        SELECT COALESCE(SUM(total_hours), 0) FROM staff_attendance 
        WHERE staff_id = %s AND status = 'Approved' AND EXTRACT(YEAR FROM date) = EXTRACT(YEAR FROM CURRENT_DATE) AND notes != 'Annual Leave'
    """, (staff_id,))
    worked_hours_ytd = float(cur.fetchone()[0] or 0)
    
    # Total holiday taken this year
    cur.execute("""
        SELECT COALESCE(SUM(total_hours), 0) FROM staff_attendance 
        WHERE staff_id = %s AND notes = 'Annual Leave' AND status = 'Approved' AND EXTRACT(YEAR FROM date) = EXTRACT(YEAR FROM CURRENT_DATE)
    """, (staff_id,))
    holiday_taken_ytd = float(cur.fetchone()[0] or 0)
    
    holiday_accrued = 0.0
    holiday_balance = 0.0
    
    if staff.get('holiday_entitled'):
        holiday_accrued = worked_hours_ytd * 0.1207
        holiday_balance = holiday_accrued - holiday_taken_ytd
        
    staff['holiday_accrued'] = round(holiday_accrued, 2)
    staff['holiday_taken'] = round(holiday_taken_ytd, 2)
    staff['holiday_balance'] = round(holiday_balance, 2)

    # --- 1. JOBS HISTORY ---
    cur.execute("""
        SELECT id, ref, status, start_date, site_address 
        FROM jobs 
        WHERE engineer_id = %s 
        ORDER BY start_date DESC LIMIT 10
    """, (staff_id,))
    
    jobs = []
    for r in cur.fetchall():
        jobs.append({
            'id': r[0], 'title': r[1], 'status': r[2], 
            'start_date': r[3], 'site_address': r[4]
        })

    # --- 2. WEEKLY TIMESHEETS (With Job Linking) ---
    cur.execute("""
        SELECT date, clock_in, clock_out, total_hours 
        FROM staff_attendance 
        WHERE staff_id = %s 
        ORDER BY date DESC LIMIT 10
    """, (staff_id,))
    
    raw_times = cur.fetchall()
    grouped_weeks = []
    
    for key, group in groupby(raw_times, key=lambda x: x[0].isocalendar()[1]):
        week_data = {'week_num': key, 'days': [], 'total_hours': 0, 'total_cost': 0}
        
        for r in group:
            c_in = r[1].strftime('%H:%M') if r[1] else '-'
            c_out = r[2].strftime('%H:%M') if r[2] else '-'
            hours = float(r[3] or 0)
            cost = calculate_wage(hours, staff['pay_rate'], staff['pay_model'])

            cur.execute("""
                SELECT j.id, j.ref, t.total_hours 
                FROM staff_timesheets t
                JOIN jobs j ON t.job_id = j.id
                WHERE t.staff_id = %s 
                AND t.date = %s
            """, (staff_id, r[0]))
            
            job_hours_sum = 0
            daily_jobs = []
            for j in cur.fetchall():
                j_hours = float(j[2] or 0)
                job_hours_sum += j_hours
                daily_jobs.append({'id': j[0], 'ref': j[1], 'hours': j_hours})

            unallocated_hours = max(0, hours - job_hours_sum)

            week_data['days'].append({
                'date': r[0].strftime('%a %d %b'),
                'clock_in': c_in,
                'clock_out': c_out,
                'hours': hours,
                'job_hours': job_hours_sum,
                'unallocated_hours': unallocated_hours,
                'cost': cost,
                'linked_jobs': daily_jobs 
            })
            
            week_data['total_hours'] += hours
            week_data['total_cost'] += cost
            
        grouped_weeks.append(week_data)

    # 3. Vehicle Checks
    cur.execute("SELECT date, type, description, cost FROM maintenance_logs WHERE description LIKE %s ORDER BY date DESC LIMIT 5", (f"%{staff['name']}%",))
    checks = [{'date': r[0], 'passed': 'Check' in r[1], 'notes': r[2], 'reg_number': 'Van Check'} for r in cur.fetchall()]

    conn.close()
    
    return render_template('hr/staff_profile.html', 
                           staff=staff, 
                           jobs=jobs, 
                           weeks=grouped_weeks, 
                           checks=checks,
                           currency=currency)

# --- 3. ADD / UPDATE STAFF (WITH PHOTO UPLOAD) ---
@hr_bp.route('/hr/update', methods=['POST'])
@hr_bp.route('/hr/add', methods=['POST'])
def save_staff():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    staff_id = request.form.get('staff_id') 
    
    if not staff_id:
        allowed, msg = check_limit(comp_id, 'max_users')
        if not allowed:
            flash(msg, "error")
            return redirect(url_for('hr_bp.hr_dashboard'))

    # Collect Data
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    position = request.form.get('position')
    dept = request.form.get('dept')
    pay_rate = request.form.get('pay_rate') or 0
    pay_model = request.form.get('pay_model')
    emp_type = request.form.get('employment_type')
    access = request.form.get('access_level')
    tax_id = request.form.get('tax_id')
    address = request.form.get('address')
    
    # New limits and flags
    tax_limit = request.form.get('tax_limit') or 0
    ni_limit = request.form.get('ni_limit') or 0
    holiday_entitled = request.form.get('holiday_entitled') == 'on'
    
    nok_name = request.form.get('nok_name')
    nok_phone = request.form.get('nok_phone')
    nok_rel = request.form.get('nok_relationship')
    nok_addr = request.form.get('nok_address')

    conn = get_db(); cur = conn.cursor()

    try:
        # --- HANDLE FILES (License & Photo) WITH VALIDATION ---
        license_path = None
        photo_path = None
        
        # 1. Driving License
        if 'driving_license' in request.files:
            f = request.files['driving_license']
            if f and f.filename != '':
                # ✅ SECURITY FIX: Validate file extension
                if not allowed_file(f.filename):
                    flash(f"❌ Invalid file type for license. Allowed: {', '.join(ALLOWED_EXTENSIONS)}", "error")
                    return redirect(url_for('hr_bp.hr_dashboard'))
                
                save_dir = os.path.join(current_app.static_folder, 'uploads', f"company_{comp_id}", 'licenses')
                os.makedirs(save_dir, exist_ok=True)
                filename = secure_filename(f"license_{int(datetime.now().timestamp())}_{f.filename}")
                f.save(os.path.join(save_dir, filename))
                license_path = f"/uploads/company_{comp_id}/licenses/{filename}"

        # 2. Profile Photo (NEW)
        if 'profile_photo' in request.files:
            f = request.files['profile_photo']
            if f and f.filename != '':
                # ✅ SECURITY FIX: Validate file extension
                if not allowed_file(f.filename):
                    flash(f"❌ Invalid file type for photo. Allowed: {', '.join(ALLOWED_EXTENSIONS)}", "error")
                    return redirect(url_for('hr_bp.hr_dashboard'))
                
                save_dir = os.path.join(current_app.static_folder, 'uploads', f"company_{comp_id}", 'profiles')
                os.makedirs(save_dir, exist_ok=True)
                filename = secure_filename(f"photo_{int(datetime.now().timestamp())}_{f.filename}")
                f.save(os.path.join(save_dir, filename))
                photo_path = f"/uploads/company_{comp_id}/profiles/{filename}"

        if staff_id:
            # UPDATE
            sql = """
                UPDATE staff SET 
                name=%s, email=%s, phone=%s, position=%s, dept=%s, 
                pay_rate=%s, pay_model=%s, employment_type=%s, access_level=%s,
                nok_name=%s, nok_phone=%s, nok_relationship=%s, nok_address=%s,
                tax_id=%s, address=%s, tax_limit=%s, ni_limit=%s, holiday_entitled=%s
            """
            params = [name, email, phone, position, dept, pay_rate, pay_model, emp_type, access, nok_name, nok_phone, nok_rel, nok_addr, tax_id, address, tax_limit, ni_limit, holiday_entitled]
            
            if license_path:
                sql += ", driving_license=%s"
                params.append(license_path)
            if photo_path:
                sql += ", profile_photo=%s"
                params.append(photo_path)
            
            sql += " WHERE id=%s AND company_id=%s"
            params.append(staff_id)
            params.append(comp_id)
            
            cur.execute(sql, tuple(params))
            cur.execute("UPDATE users SET name=%s WHERE email=%s AND company_id=%s", (name, email, comp_id))
            flash("✅ Staff record updated.")
            
        else:
            # INSERT
            cur.execute("""
                INSERT INTO staff (company_id, name, email, phone, position, dept, pay_rate, pay_model, employment_type, access_level, nok_name, nok_phone, nok_relationship, nok_address, driving_license, profile_photo, tax_id, address, tax_limit, ni_limit, holiday_entitled)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (comp_id, name, email, phone, position, dept, pay_rate, pay_model, emp_type, access, nok_name, nok_phone, nok_rel, nok_addr, license_path, photo_path, tax_id, address, tax_limit, ni_limit, holiday_entitled))
            
            if access != "None" and email:
                cur.execute("SELECT id FROM users WHERE email=%s", (email,))
                if not cur.fetchone():
                    pw = ''.join(secrets.choice(string.ascii_letters + string.digits) for i in range(12))
                    cur.execute("INSERT INTO users (username, email, password_hash, role, company_id) VALUES (%s, %s, %s, %s, %s)", (email, email, generate_password_hash(pw), access, comp_id))
                    try: send_company_email(comp_id, email, "Your Login Details", f"<p>Username: {email}</p><p>Password: {pw}</p>")
                    except: pass
            
            flash("✅ New employee added.")

        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
    finally:
        conn.close()

    return redirect(url_for('hr_bp.hr_dashboard'))

# --- DELETE (Unchanged) ---
@hr_bp.route('/hr/delete/<int:id>')
def delete_staff(id):
    # (Same code as before - no changes needed)
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT email FROM staff WHERE id = %s", (id,))
        row = cur.fetchone()
        cur.execute("DELETE FROM staff WHERE id = %s AND company_id = %s", (id, session.get('company_id')))
        if row and row[0]: cur.execute("DELETE FROM users WHERE email = %s AND company_id = %s", (row[0], session.get('company_id')))
        conn.commit()
        flash("🗑️ Staff member deleted.", "success")
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error")
    finally:
        conn.close()
    return redirect(url_for('hr_bp.hr_dashboard'))
    
# --- DUPLICATE ROUTE REMOVED ---
# Note: /hr/update was defined twice - consolidated into save_staff() function above
# The save_staff() function handles both ADD (when staff_id is None) and UPDATE (when staff_id is provided)