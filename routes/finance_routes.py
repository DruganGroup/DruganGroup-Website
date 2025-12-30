from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from werkzeug.utils import secure_filename
import os
from datetime import datetime, date 
from db import get_db, get_site_config, allowed_file, UPLOAD_FOLDER

finance_bp = Blueprint('finance', __name__)

# --- 1. OVERVIEW ---
@finance_bp.route('/finance-dashboard')
def finance_dashboard():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"

    company_id = session.get('company_id')
    config = get_site_config(company_id)
    
    conn = get_db()
    cur = conn.cursor()

    # Ensure Transactions Table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY, company_id INTEGER, date DATE,
            type TEXT, category TEXT, description TEXT, amount DECIMAL(10,2), reference TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    # Financial Calcs
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,))
    income = cur.fetchone()[0] or 0.0
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Expense'", (company_id,))
    expense = cur.fetchone()[0] or 0.0
    balance = income - expense

    cur.execute("SELECT date, type, category, description, amount, reference FROM transactions WHERE company_id = %s ORDER BY date DESC LIMIT 20", (company_id,))
    transactions = cur.fetchall()
    
    conn.close()
    return render_template('finance/finance_dashboard.html', total_income=income, total_expense=expense, total_balance=balance, transactions=transactions, brand_color=config['color'], logo_url=config['logo'])


# --- 2. HR & STAFF ---
@finance_bp.route('/finance/hr')
def finance_hr():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    # Update DB Schema
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS staff (id SERIAL PRIMARY KEY, company_id INTEGER, name TEXT, position TEXT, dept TEXT, pay_rate DECIMAL(10,2), pay_model TEXT, access_level TEXT);")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS email TEXT;")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS phone TEXT;")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS address TEXT;")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS employment_type TEXT;")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS tax_id TEXT;")
        conn.commit()
    except:
        conn.rollback()

    cur.execute("""
        SELECT id, name, position, dept, pay_rate, pay_model, access_level, email, phone, employment_type, address, tax_id 
        FROM staff WHERE company_id = %s ORDER BY name
    """, (comp_id,))
    staff = cur.fetchall()
    conn.close()
    return render_template('finance/finance_hr.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

@finance_bp.route('/finance/hr/add', methods=['POST'])
def add_staff():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    name = request.form.get('name'); position = request.form.get('position')
    email = request.form.get('email'); phone = request.form.get('phone')
    address = request.form.get('address'); emp_type = request.form.get('employment_type')
    dept = request.form.get('dept'); rate = request.form.get('rate') or 0
    model = request.form.get('model'); tax_id = request.form.get('tax_id')
    access = request.form.get('access_level'); password = request.form.get('password')
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO staff (company_id, name, position, dept, pay_rate, pay_model, access_level, email, phone, address, employment_type, tax_id) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, name, position, dept, rate, model, access, email, phone, address, emp_type, tax_id))
        
        if access != "None" and email and password:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            if not cur.fetchone():
                cur.execute("INSERT INTO users (username, email, password_hash, role, company_id) VALUES (%s, %s, %s, %s, %s)", (email, email, password, access, comp_id))
                try:
                    from email_service import send_company_email
                    subject = "Welcome to TradeCore - Your Login Details"
                    body = f"<h3>Welcome, {name}!</h3><p>Login URL: https://www.drugangroup.co.uk/login</p><p>Username: {email}</p><p>Password: {password}</p>"
                    send_company_email(comp_id, email, subject, body)
                    flash(f"✅ Staff added and login emailed to {email}")
                except: flash("✅ Staff added. (Email Service not found)")
            else: flash("⚠️ Staff added, but user email already exists.")
        else: flash("✅ Staff member added successfully.")
        conn.commit()
    except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")
    finally: conn.close()
    return redirect(url_for('finance.finance_hr'))

# --- NEW: UPDATE STAFF ROUTE ---
@finance_bp.route('/finance/hr/update', methods=['POST'])
def update_staff():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    staff_id = request.form.get('staff_id')
    name = request.form.get('name'); position = request.form.get('position')
    email = request.form.get('email'); phone = request.form.get('phone')
    address = request.form.get('address'); emp_type = request.form.get('employment_type')
    dept = request.form.get('dept'); rate = request.form.get('rate') or 0
    model = request.form.get('model'); tax_id = request.form.get('tax_id')
    access = request.form.get('access_level')
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE staff SET name=%s, position=%s, email=%s, phone=%s, address=%s, employment_type=%s, dept=%s, pay_rate=%s, pay_model=%s, tax_id=%s, access_level=%s 
            WHERE id=%s AND company_id=%s
        """, (name, position, email, phone, address, emp_type, dept, rate, model, tax_id, access, staff_id, session.get('company_id')))
        conn.commit()
        flash("✅ Staff Details Updated")
    except Exception as e:
        conn.rollback(); flash(f"❌ Error updating staff: {e}")
    finally:
        conn.close()
    return redirect(url_for('finance.finance_hr'))

@finance_bp.route('/finance/hr/delete/<int:id>')
def delete_staff(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM staff WHERE id = %s AND company_id = %s", (id, session.get('company_id')))
    conn.commit(); conn.close()
    return redirect(url_for('finance.finance_hr'))


# --- 3. FINANCE FLEET (Cost Tracking Edition) ---
@finance_bp.route('/finance/fleet', methods=['GET', 'POST'])
def finance_fleet():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    # --- HANDLE ADDING COSTS (Fuel, Insurance, etc) ---
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_log':
            v_id = request.form.get('vehicle_id')
            l_type = request.form.get('log_type') # e.g. Insurance, Fuel, Repair
            desc = request.form.get('description')
            date = request.form.get('date')
            cost = request.form.get('cost') or 0
            
            try:
                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, type, description, date, cost)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (comp_id, v_id, l_type, desc, date, cost))
                conn.commit()
                flash("✅ Cost Recorded Successfully")
            except Exception as e:
                conn.rollback(); flash(f"❌ Error: {e}")
                
        elif action == 'update_vehicle':
             # (Keep your existing update logic here if you have it, or rely on the Office Hub for editing details)
             pass

    # --- FETCH VEHICLES WITH FINANCIAL TOTALS ---
    # We join with maintenance_logs to calculate total spend
    cur.execute("""
        SELECT 
            v.id, v.reg_plate, v.make_model, v.status, 
            v.mot_due, v.tax_due, v.insurance_due,
            s.name as driver_name,
            COALESCE(SUM(l.cost), 0) as total_spend
        FROM vehicles v 
        LEFT JOIN staff s ON v.assigned_driver_id = s.id 
        LEFT JOIN maintenance_logs l ON v.id = l.vehicle_id
        WHERE v.company_id = %s
        GROUP BY v.id, s.name
        ORDER BY v.reg_plate
    """, (comp_id,))
    
    raw_vehicles = cur.fetchall()
    vehicles = []
    
    from datetime import date
    today = date.today()

    for row in raw_vehicles:
        v_id = row[0]
        
        # Fetch Breakdown of Costs
        cur.execute("SELECT date, type, description, cost FROM maintenance_logs WHERE vehicle_id = %s ORDER BY date DESC", (v_id,))
        history = [{'date': r[0], 'type': r[1], 'desc': r[2], 'cost': r[3]} for r in cur.fetchall()]

        vehicles.append({
            'id': row[0],
            'reg_number': row[1],
            'make_model': row[2],
            'status': row[3],
            'mot_due': row[4],
            'tax_due': row[5],
            'ins_due': row[6],
            'driver': row[7],
            'total_spend': row[8],
            'history': history
        })

    conn.close()
    
    return render_template('finance/finance_fleet.html', vehicles=vehicles, today=today, brand_color=config['color'], logo_url=config['logo'])
    
@finance_bp.route('/finance/fleet/add', methods=['POST'])
def add_vehicle():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    reg = request.form.get('reg'); model = request.form.get('model')
    driver_id = request.form.get('driver_id')
    if driver_id == "None": driver_id = None
    mot = request.form.get('mot') or None; tax = request.form.get('tax') or None
    status = request.form.get('status'); tracker = request.form.get('tracker_url')
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO vehicles (company_id, reg_plate, make_model, assigned_driver_id, mot_due, tax_due, status, tracker_url) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, reg, model, driver_id, mot, tax, status, tracker))
        conn.commit(); flash("✅ Vehicle Added Successfully")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('finance.finance_fleet'))

# --- NEW: UPDATE VEHICLE ROUTE ---
@finance_bp.route('/finance/fleet/update', methods=['POST'])
def update_vehicle():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    vehicle_id = request.form.get('vehicle_id')
    reg = request.form.get('reg'); model = request.form.get('model')
    driver_id = request.form.get('driver_id')
    if driver_id == "None": driver_id = None
    mot = request.form.get('mot') or None; tax = request.form.get('tax') or None
    status = request.form.get('status'); tracker = request.form.get('tracker_url')
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE vehicles SET reg_plate=%s, make_model=%s, assigned_driver_id=%s, mot_due=%s, tax_due=%s, status=%s, tracker_url=%s
            WHERE id=%s AND company_id=%s
        """, (reg, model, driver_id, mot, tax, status, tracker, vehicle_id, session.get('company_id')))
        conn.commit(); flash("✅ Vehicle Details Updated")
    except Exception as e: conn.rollback(); flash(f"❌ Error updating vehicle: {e}")
    finally: conn.close()
    return redirect(url_for('finance.finance_fleet'))

@finance_bp.route('/finance/fleet/delete/<int:id>')
def delete_vehicle(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM vehicles WHERE id=%s AND company_id=%s", (id, session.get('company_id')))
    conn.commit(); conn.close()
    return redirect(url_for('finance.finance_fleet'))


# --- 4. MATERIALS ---
@finance_bp.route('/finance/materials')
def finance_materials():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS materials (id SERIAL PRIMARY KEY, company_id INTEGER, sku TEXT, name TEXT, category TEXT, unit TEXT, cost_price DECIMAL(10,2), supplier TEXT);")
    conn.commit()
    cur.execute("SELECT id, sku, name, category, unit, cost_price, supplier FROM materials WHERE company_id = %s ORDER BY name", (comp_id,))
    materials = cur.fetchall()
    conn.close()
    return render_template('finance/finance_materials.html', materials=materials, brand_color=config['color'], logo_url=config['logo'])

@finance_bp.route('/finance/materials/add', methods=['POST'])
def add_material():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    supplier = request.form.get('supplier'); sku = request.form.get('sku')
    name = request.form.get('name'); cat = request.form.get('category')
    unit = request.form.get('unit'); cost = request.form.get('cost') or 0
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO materials (company_id, sku, name, category, unit, cost_price, supplier) VALUES (%s, %s, %s, %s, %s, %s, %s)", (session.get('company_id'), sku, name, cat, unit, cost, supplier))
        conn.commit(); flash("Item Added")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('finance.finance_materials'))

@finance_bp.route('/finance/materials/delete/<int:id>')
def delete_material(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM materials WHERE id=%s AND company_id=%s", (id, session.get('company_id')))
    conn.commit(); conn.close()
    return redirect(url_for('finance.finance_materials'))


# --- 5. ANALYSIS ---
@finance_bp.route('/finance/analysis')
def finance_analysis():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT reference, description, amount FROM transactions WHERE company_id = %s AND type = 'Income' ORDER BY date DESC LIMIT 50", (comp_id,))
    raw_jobs = cur.fetchall()
    
    analyzed_jobs = []; total_rev = 0; total_cost = 0
    for j in raw_jobs:
        rev = float(j[2])
        est_cost = rev / 1.2 # Simple assumption for now
        profit = rev - est_cost
        margin = (profit / rev * 100) if rev > 0 else 0
        total_rev += rev; total_cost += est_cost
        analyzed_jobs.append({"ref": j[0], "client": j[1], "status": "Completed", "rev": rev, "cost": est_cost, "profit": profit, "margin": margin})
    conn.close()
    
    total_profit = total_rev - total_cost
    avg_margin = (total_profit / total_rev * 100) if total_rev > 0 else 0
    return render_template('finance/finance_analysis.html', jobs=analyzed_jobs, total_rev=total_rev, total_cost=total_cost, total_profit=total_profit, avg_margin=avg_margin, brand_color=config['color'], logo_url=config['logo'])


# --- 6. SETTINGS ---
@finance_bp.route('/finance/settings')
def finance_settings():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS settings (company_id INTEGER, key TEXT, value TEXT, PRIMARY KEY (company_id, key));")
    conn.commit()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    rows = cur.fetchall(); conn.close()
    settings_dict = {row[0]: row[1] for row in rows}
    return render_template('finance/finance_settings.html', settings=settings_dict, brand_color=config['color'], logo_url=config['logo'])

@finance_bp.route('/finance/settings/save', methods=['POST'])
def save_settings():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    try:
        # 1. Save All Text Fields
        for key, value in request.form.items():
            cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, %s, %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, key, value))
        
        # 2. Save Company LOGO
        if 'logo' in request.files:
            file = request.files['logo']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"logo_{comp_id}_{file.filename}")
                file_path = os.path.join(UPLOAD_FOLDER, filename)
                file.save(file_path)
                db_path = f"/static/uploads/logos/{filename}"
                cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'logo_url', %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, db_path))

        # 3. Save Payment QR CODE
        if 'payment_qr' in request.files:
            file = request.files['payment_qr']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"qr_{comp_id}_{file.filename}")
                file_path = os.path.join(UPLOAD_FOLDER, filename)
                file.save(file_path)
                db_path = f"/static/uploads/logos/{filename}"
                cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'payment_qr_url', %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, db_path))

        conn.commit(); flash("Configuration Saved Successfully!")
    except Exception as e: conn.rollback(); flash(f"Error saving settings: {e}")
    finally: conn.close()
    return redirect(url_for('finance.finance_settings'))

# --- TEMP FIX: JUMP COUNTERS TO 1000 (KEPT FOR SAFETY) ---
@finance_bp.route('/finance/fix-ids')
def fix_database_ids():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"
    conn = get_db(); cur = conn.cursor()
    tables = ['staff', 'vehicles', 'materials', 'users', 'transactions']
    messages = []
    try:
        for t in tables:
            cur.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), (SELECT GREATEST(MAX(id)+1, 1000) FROM {t}), false);")
            messages.append(f"✅ Fixed {t}: Next ID set to 1000+")
        conn.commit()
        return f"<h1>Database Repair Complete</h1><br>{'<br>'.join(messages)}<br><br><a href='/finance/hr'>Go Back to HR</a>"
    except Exception as e:
        conn.rollback(); return f"<h1>Error</h1><p>{e}</p>"
    finally: conn.close()
    
    # --- TEMP TOOL: GENERATE SUBDOMAINS FOR EXISTING COMPANIES ---
@finance_bp.route('/finance/fix-subdomains')
def fix_subdomains():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"
    
    conn = get_db()
    cur = conn.cursor()
    import re

    messages = []
    try:
        # 1. Add the Column if it doesn't exist
        cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS subdomain TEXT UNIQUE;")
        conn.commit()
        messages.append("✅ 'subdomain' column confirmed.")

        # 2. Fetch all companies that don't have a subdomain yet
        cur.execute("SELECT id, name FROM companies WHERE subdomain IS NULL OR subdomain = ''")
        companies = cur.fetchall()

        for comp in companies:
            c_id = comp[0]
            c_name = comp[1]
            
            # 3. Create "Slug" (Lowercase, remove special chars, spaces to hyphens)
            # e.g. "Nick's Construction Ltd." -> "nicks-construction-ltd"
            base_slug = re.sub(r'[^a-z0-9-]', '', c_name.lower().replace(' ', '-'))
            # Remove double hyphens caused by weird symbols
            base_slug = re.sub(r'-+', '-', base_slug).strip('-')
            
            # 4. Duplicate Defender
            # Check if this slug exists. If so, add -1, -2, etc.
            final_slug = base_slug
            counter = 1
            while True:
                cur.execute("SELECT id FROM companies WHERE subdomain = %s AND id != %s", (final_slug, c_id))
                if not cur.fetchone():
                    break # Unique!
                final_slug = f"{base_slug}-{counter}"
                counter += 1
            
            # 5. Save it
            cur.execute("UPDATE companies SET subdomain = %s WHERE id = %s", (final_slug, c_id))
            messages.append(f"✅ Generated subdomain for {c_name}: <strong>{final_slug}</strong>")

        conn.commit()
        return f"<h1>Subdomain Generation Complete</h1><br>{'<br>'.join(messages)}<br><br><a href='/finance-dashboard'>Back to Dashboard</a>"

    except Exception as e:
        conn.rollback()
        return f"<h1>Error</h1><p>{e}</p>"
    finally:
        conn.close()