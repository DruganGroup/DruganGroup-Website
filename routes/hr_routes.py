import os
from datetime import datetime
from flask import Blueprint, render_template, session, redirect, url_for, request, current_app, flash
from werkzeug.utils import secure_filename
from db import get_db

hr_bp = Blueprint('hr_bp', __name__)

# --- 1. DATABASE FIX (Run once then ignore) ---
@hr_bp.route('/fix-license-column')
def fix_license_column():
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS driving_license TEXT;")
        conn.commit()
        return "✅ Success: 'driving_license' column added to Staff table."
    except Exception as e:
        return f"❌ Error: {e}"
    finally:
        conn.close()

# --- 2. STAFF PROFILE ---
@hr_bp.route('/hr/staff/<int:staff_id>')
def staff_profile(staff_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get Currency
    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'currency_symbol'", (session.get('company_id'),))
    res = cur.fetchone()
    currency = res[0] if res else '£'
    
    # Get Staff Details (Includes new driving_license column)
    cur.execute("SELECT * FROM staff WHERE id = %s", (staff_id,))
    staff_raw = cur.fetchone()
    
    if not staff_raw: 
        conn.close()
        return "Staff member not found", 404
        
    colnames = [desc[0] for desc in cur.description]
    staff = dict(zip(colnames, staff_raw))
    
    # Get History (Jobs, Vehicles, Timesheets)
    # ... (Same logic as before, abbreviated for clarity) ...
    cur.execute("SELECT id, ref, status, start_date, site_address FROM jobs WHERE engineer_id = %s ORDER BY start_date DESC LIMIT 5", (staff_id,))
    jobs = [{'id': r[0], 'title': r[1], 'status': r[2], 'date': r[3], 'site': r[4]} for r in cur.fetchall()]

    cur.execute("SELECT date, clock_in, clock_out, total_hours FROM staff_timesheets WHERE staff_id = %s ORDER BY date DESC LIMIT 5", (staff_id,))
    timesheets = [{'date': r[0], 'in': r[1], 'out': r[2], 'hours': r[3]} for r in cur.fetchall()]
    
    conn.close()
    
    return render_template('hr/staff_profile.html', 
                           staff=staff, 
                           jobs=jobs, 
                           timesheets=timesheets,
                           currency=currency)

# --- 3. ADD / UPDATE STAFF (With File Upload) ---
@hr_bp.route('/finance/hr/update', methods=['POST'])
@hr_bp.route('/finance/hr/add', methods=['POST'])
def save_staff():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    staff_id = request.form.get('staff_id') # If empty, it's a NEW add
    
    # Collect Form Data
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    position = request.form.get('position')
    dept = request.form.get('dept')
    pay_rate = request.form.get('pay_rate') or 0
    pay_model = request.form.get('pay_model')
    emp_type = request.form.get('employment_type')
    access = request.form.get('access_level')
    
    # NOK Data
    nok_name = request.form.get('nok_name')
    nok_phone = request.form.get('nok_phone')
    nok_rel = request.form.get('nok_relationship')
    nok_addr = request.form.get('nok_address')

    conn = get_db()
    cur = conn.cursor()

    try:
        # --- HANDLE FILE UPLOAD (Driving License) ---
        license_path = None
        if 'driving_license' in request.files:
            f = request.files['driving_license']
            if f and f.filename != '':
                # Save to: /static/uploads/{comp_id}/licenses/
                save_dir = os.path.join(current_app.static_folder, 'uploads', str(comp_id), 'licenses')
                os.makedirs(save_dir, exist_ok=True)
                
                filename = secure_filename(f"license_{int(datetime.now().timestamp())}_{f.filename}")
                full_path = os.path.join(save_dir, filename)
                f.save(full_path)
                
                license_path = f"uploads/{comp_id}/licenses/{filename}"

        if staff_id:
            # UPDATE EXISTING
            sql = """
                UPDATE staff SET 
                name=%s, email=%s, phone=%s, position=%s, dept=%s, 
                pay_rate=%s, pay_model=%s, employment_type=%s, access_level=%s,
                nok_name=%s, nok_phone=%s, nok_relationship=%s, nok_address=%s
            """
            params = [name, email, phone, position, dept, pay_rate, pay_model, emp_type, access, nok_name, nok_phone, nok_rel, nok_addr]
            
            # Only update license if a new one was uploaded
            if license_path:
                sql += ", driving_license=%s"
                params.append(license_path)
            
            sql += " WHERE id=%s AND company_id=%s"
            params.append(staff_id)
            params.append(comp_id)
            
            cur.execute(sql, tuple(params))
            flash("✅ Staff record updated.")
        else:
            # INSERT NEW
            cur.execute("""
                INSERT INTO staff (company_id, name, email, phone, position, dept, pay_rate, pay_model, employment_type, access_level, nok_name, nok_phone, nok_relationship, nok_address, driving_license)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (comp_id, name, email, phone, position, dept, pay_rate, pay_model, emp_type, access, nok_name, nok_phone, nok_rel, nok_addr, license_path))
            flash("✅ New employee added.")

        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
    finally:
        conn.close()

    return redirect(url_for('finance.finance_hr'))