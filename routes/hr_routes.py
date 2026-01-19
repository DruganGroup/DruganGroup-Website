import os
from datetime import datetime, timedelta
from flask import Blueprint, render_template, session, redirect, url_for, request, current_app, flash
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from db import get_db, get_site_config
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
        conn.commit()
    except:
        conn.rollback()

    cur.execute("SELECT id, name, position, dept, pay_rate, pay_model, access_level, email, phone, employment_type, address, tax_id, driving_license, profile_photo FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
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
                SELECT id, ref, site_address FROM jobs 
                WHERE engineer_id = %s 
                AND start_date::DATE = %s
            """, (staff_id, r[0]))
            
            daily_jobs = [{'id': j[0], 'ref': j[1], 'site': j[2]} for j in cur.fetchall()]

            week_data['days'].append({
                'date': r[0].strftime('%a %d %b'),
                'clock_in': c_in,
                'clock_out': c_out,
                'hours': hours,
                'cost': cost,
                'linked_jobs': daily_jobs # <--- SENDING JOBS TO TEMPLATE
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
    
    nok_name = request.form.get('nok_name')
    nok_phone = request.form.get('nok_phone')
    nok_rel = request.form.get('nok_relationship')
    nok_addr = request.form.get('nok_address')

    conn = get_db(); cur = conn.cursor()

    try:
        # --- HANDLE FILES (License & Photo) ---
        license_path = None
        photo_path = None
        
        # 1. Driving License
        if 'driving_license' in request.files:
            f = request.files['driving_license']
            if f and f.filename != '':
                save_dir = os.path.join(current_app.static_folder, 'uploads', str(comp_id), 'licenses')
                os.makedirs(save_dir, exist_ok=True)
                filename = secure_filename(f"license_{int(datetime.now().timestamp())}_{f.filename}")
                f.save(os.path.join(save_dir, filename))
                license_path = f"uploads/{comp_id}/licenses/{filename}"

        # 2. Profile Photo (NEW)
        if 'profile_photo' in request.files:
            f = request.files['profile_photo']
            if f and f.filename != '':
                save_dir = os.path.join(current_app.static_folder, 'uploads', str(comp_id), 'profiles')
                os.makedirs(save_dir, exist_ok=True)
                filename = secure_filename(f"photo_{int(datetime.now().timestamp())}_{f.filename}")
                f.save(os.path.join(save_dir, filename))
                photo_path = f"uploads/{comp_id}/profiles/{filename}"

        if staff_id:
            # UPDATE
            sql = """
                UPDATE staff SET 
                name=%s, email=%s, phone=%s, position=%s, dept=%s, 
                pay_rate=%s, pay_model=%s, employment_type=%s, access_level=%s,
                nok_name=%s, nok_phone=%s, nok_relationship=%s, nok_address=%s,
                tax_id=%s, address=%s
            """
            params = [name, email, phone, position, dept, pay_rate, pay_model, emp_type, access, nok_name, nok_phone, nok_rel, nok_addr, tax_id, address]
            
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
                INSERT INTO staff (company_id, name, email, phone, position, dept, pay_rate, pay_model, employment_type, access_level, nok_name, nok_phone, nok_relationship, nok_address, driving_license, profile_photo, tax_id, address)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (comp_id, name, email, phone, position, dept, pay_rate, pay_model, emp_type, access, nok_name, nok_phone, nok_rel, nok_addr, license_path, photo_path, tax_id, address))
            
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
    
# --- UPDATE STAFF (ADMIN & SELF) ---
@hr_bp.route('/hr/update', methods=['POST'])
def update_staff():
    # Allow Admin, SuperAdmin, OR the user updating themselves
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # 1. Capture Data
        staff_id = request.form.get('staff_id')
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        address = request.form.get('address') # Staff Home Address
        
        # Next of Kin (The Missing Links)
        nok_name = request.form.get('nok_name')
        nok_relationship = request.form.get('nok_relationship')
        nok_phone = request.form.get('nok_phone')
        nok_address = request.form.get('nok_address')

        # 2. Security Check
        # If not Admin, ensure they are only updating their OWN record
        cur.execute("SELECT id FROM staff WHERE email = (SELECT email FROM users WHERE id = %s)", (session['user_id'],))
        my_staff_id = cur.fetchone()
        
        if session.get('role') not in ['Admin', 'SuperAdmin']:
            if not my_staff_id or str(my_staff_id[0]) != str(staff_id):
                flash("❌ You can only edit your own profile.", "error")
                return redirect(url_for('main.launcher'))

        # 3. Update Database
        cur.execute("""
            UPDATE staff 
            SET name=%s, email=%s, phone=%s, address=%s,
                nok_name=%s, nok_relationship=%s, nok_phone=%s, nok_address=%s
            WHERE id=%s
        """, (name, email, phone, address, nok_name, nok_relationship, nok_phone, nok_address, staff_id))
        
        # 4. If Admin, also update Admin-only fields (Role, Pay, Dept)
        if session.get('role') in ['Admin', 'SuperAdmin']:
            position = request.form.get('position')
            dept = request.form.get('dept')
            pay_rate = request.form.get('pay_rate')
            pay_model = request.form.get('pay_model')
            access_level = request.form.get('access_level')
            
            cur.execute("""
                UPDATE staff 
                SET position=%s, dept=%s, pay_rate=%s, pay_model=%s, access_level=%s
                WHERE id=%s
            """, (position, dept, pay_rate, pay_model, access_level, staff_id))

        conn.commit()
        flash("✅ Profile updated successfully.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"Error updating profile: {e}", "error")
    finally:
        conn.close()

    # Redirect back to where they came from
    if session.get('role') in ['Admin', 'SuperAdmin'] and 'hr' in request.referrer:
        return redirect(url_for('hr_bp.view_staff', id=staff_id))
    else:
        return redirect(url_for('main.launcher'))