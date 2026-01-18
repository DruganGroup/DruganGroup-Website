import os
from datetime import datetime
from flask import Blueprint, render_template, session, redirect, url_for, request, current_app, flash
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from db import get_db, get_site_config
from services.enforcement import check_limit
import secrets
import string
from email_service import send_company_email

hr_bp = Blueprint('hr_bp', __name__)

# --- 1. HR DASHBOARD (List All Staff) ---
@hr_bp.route('/hr/dashboard')
def hr_dashboard():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT id, name, position, dept, pay_rate, pay_model, access_level, email, phone, employment_type, address, tax_id, driving_license FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    cols = [desc[0] for desc in cur.description]
    staff = [dict(zip(cols, row)) for row in cur.fetchall()]
    
    conn.close()
    return render_template('finance/finance_hr.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

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
    
    # Get Staff Details
    cur.execute("SELECT * FROM staff WHERE id = %s", (staff_id,))
    staff_raw = cur.fetchone()
    
    if not staff_raw: 
        conn.close()
        return "Staff member not found", 404
        
    colnames = [desc[0] for desc in cur.description]
    staff = dict(zip(colnames, staff_raw))
    
    # Get History
    cur.execute("SELECT id, ref, status, start_date, site_address FROM jobs WHERE engineer_id = %s ORDER BY start_date DESC LIMIT 5", (staff_id,))
    jobs = [{'id': r[0], 'title': r[1], 'status': r[2], 'date': r[3], 'site': r[4]} for r in cur.fetchall()]

    cur.execute("SELECT date, clock_in, clock_out, total_hours FROM staff_timesheets WHERE staff_id = %s ORDER BY date DESC LIMIT 5", (staff_id,))
    timesheets = [{'date': r[0], 'in': r[1], 'out': r[2], 'hours': r[3]} for r in cur.fetchall()]
    
    cur.execute("SELECT date, type, description, cost FROM maintenance_logs WHERE description LIKE %s ORDER BY date DESC LIMIT 5", (f"%{staff['name']}%",))
    checks = [{'date': r[0], 'passed': 'Check' in r[1], 'notes': r[2], 'reg_number': 'Van Check'} for r in cur.fetchall()]

    conn.close()
    
    return render_template('hr/staff_profile.html', 
                           staff=staff, 
                           jobs=jobs, 
                           timesheets=timesheets,
                           checks=checks,
                           currency=currency)

# --- 3. ADD / UPDATE STAFF ---
@hr_bp.route('/hr/update', methods=['POST'])
@hr_bp.route('/hr/add', methods=['POST'])
def save_staff():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    staff_id = request.form.get('staff_id') # If empty, it's a NEW add
    
    # Check Limits for New Staff
    if not staff_id:
        allowed, msg = check_limit(comp_id, 'max_users')
        if not allowed:
            flash(msg, "error")
            return redirect(url_for('hr_bp.hr_dashboard'))

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
    tax_id = request.form.get('tax_id')
    address = request.form.get('address')
    
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
                nok_name=%s, nok_phone=%s, nok_relationship=%s, nok_address=%s,
                tax_id=%s, address=%s
            """
            params = [name, email, phone, position, dept, pay_rate, pay_model, emp_type, access, nok_name, nok_phone, nok_rel, nok_addr, tax_id, address]
            
            if license_path:
                sql += ", driving_license=%s"
                params.append(license_path)
            
            sql += " WHERE id=%s AND company_id=%s"
            params.append(staff_id)
            params.append(comp_id)
            
            cur.execute(sql, tuple(params))
            
            # Sync User Login Name
            cur.execute("UPDATE users SET name=%s WHERE email=%s AND company_id=%s", (name, email, comp_id))
            flash("✅ Staff record updated.")
            
        else:
            # INSERT NEW
            cur.execute("""
                INSERT INTO staff (company_id, name, email, phone, position, dept, pay_rate, pay_model, employment_type, access_level, nok_name, nok_phone, nok_relationship, nok_address, driving_license, tax_id, address)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (comp_id, name, email, phone, position, dept, pay_rate, pay_model, emp_type, access, nok_name, nok_phone, nok_rel, nok_addr, license_path, tax_id, address))
            
            # Auto-Create Login if Access Granted
            if access != "None" and email:
                cur.execute("SELECT id FROM users WHERE email=%s", (email,))
                if not cur.fetchone():
                    pw = ''.join(secrets.choice(string.ascii_letters + string.digits) for i in range(12))
                    cur.execute("INSERT INTO users (username, email, password_hash, role, company_id) VALUES (%s, %s, %s, %s, %s)", (email, email, generate_password_hash(pw), access, comp_id))
                    
                    try:
                        send_company_email(comp_id, email, "Your Login Details", f"<p>Username: {email}</p><p>Password: {pw}</p>")
                        flash(f"✅ Staff Added & Login Emailed to {email}")
                    except:
                        flash(f"✅ Staff Added. (Email failed to send, password is {pw})")
            else:
                flash("✅ New employee added.")

        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
    finally:
        conn.close()

    return redirect(url_for('hr_bp.hr_dashboard'))

# --- 4. DELETE STAFF ---
@hr_bp.route('/hr/delete/<int:id>')
def delete_staff(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    try:
        # Get Email to delete login too
        cur.execute("SELECT email FROM staff WHERE id = %s", (id,))
        row = cur.fetchone()
        
        cur.execute("DELETE FROM staff WHERE id = %s AND company_id = %s", (id, session.get('company_id')))
        
        if row and row[0]:
            cur.execute("DELETE FROM users WHERE email = %s AND company_id = %s", (row[0], session.get('company_id')))
            
        conn.commit()
        flash("🗑️ Staff member deleted.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('hr_bp.hr_dashboard'))