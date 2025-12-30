from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from werkzeug.utils import secure_filename
import os
import csv
from io import TextIOWrapper
from datetime import datetime, date 
from db import get_db, get_site_config, allowed_file, UPLOAD_FOLDER

finance_bp = Blueprint('finance', __name__)

# --- HELPER: FORCE DATE OBJECT ---
def parse_date(d):
    """Converts string dates from DB into Python Date objects for math"""
    if isinstance(d, str):
        try:
            return datetime.strptime(d, '%Y-%m-%d').date()
        except:
            return None
    return d

# --- 1. OVERVIEW ---
@finance_bp.route('/finance-dashboard')
def finance_dashboard():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))

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
                from werkzeug.security import generate_password_hash
                hashed_pw = generate_password_hash(password)
                cur.execute("INSERT INTO users (username, email, password_hash, role, company_id) VALUES (%s, %s, %s, %s, %s)", (email, email, hashed_pw, access, comp_id))
                flash(f"✅ Staff added and login created for {email}")
            else: flash("⚠️ Staff added, but user email already exists.")
        else: flash("✅ Staff member added successfully.")
        conn.commit()
    except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")
    finally: conn.close()
    return redirect(url_for('finance.finance_hr'))

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


# --- 3. FINANCE FLEET ---
@finance_bp.route('/finance/fleet', methods=['GET', 'POST'])
def finance_fleet():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_log':
            v_id = request.form.get('vehicle_id')
            l_type = request.form.get('log_type') 
            desc = request.form.get('description')
            log_date = request.form.get('date')
            cost = request.form.get('cost') or 0
            
            try:
                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, type, description, date, cost)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (comp_id, v_id, l_type, desc, log_date, cost))
                conn.commit()
                flash("✅ Cost Recorded Successfully")
            except Exception as e:
                conn.rollback(); flash(f"❌ Error: {e}")
                
        elif action == 'add_vehicle':
            reg = request.form.get('reg')
            model = request.form.get('model')
            driver = request.form.get('driver_id')
            cost = request.form.get('daily_cost') or 0
            mot = request.form.get('mot')
            tax = request.form.get('tax')
            ins = request.form.get('ins')
            serv = request.form.get('serv')
            tracker = request.form.get('tracker_url')
            
            try:
                cur.execute("""
                    INSERT INTO vehicles (company_id, reg_plate, make_model, assigned_driver_id, daily_cost, mot_due, tax_due, insurance_due, service_due, tracker_url, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Active')
                """, (comp_id, reg, model, driver if driver != 'None' else None, cost, mot, tax, ins, serv, tracker))
                conn.commit()
                flash("✅ Vehicle Added")
            except Exception as e:
                conn.rollback(); flash(f"❌ Error: {e}")
        
        elif action == 'update_vehicle':
            v_id = request.form.get('vehicle_id')
            reg = request.form.get('reg')
            model = request.form.get('model')
            driver = request.form.get('driver_id')
            status = request.form.get('status')
            mot = request.form.get('mot')
            tax = request.form.get('tax')
            ins = request.form.get('ins')
            serv = request.form.get('serv')
            tracker = request.form.get('tracker_url')
            
            try:
                cur.execute("""
                    UPDATE vehicles SET reg_plate=%s, make_model=%s, assigned_driver_id=%s, status=%s, 
                    mot_due=%s, tax_due=%s, insurance_due=%s, service_due=%s, tracker_url=%s
                    WHERE id=%s AND company_id=%s
                """, (reg, model, driver if driver != 'None' else None, status, mot, tax, ins, serv, tracker, v_id, comp_id))
                conn.commit()
                flash("✅ Vehicle Updated")
            except Exception as e:
                conn.rollback(); flash(f"❌ Error: {e}")

    # Fetch Data
    cur.execute("""
        SELECT 
            v.id, v.reg_plate, v.make_model, v.status, 
            v.mot_due, v.tax_due, v.insurance_due,
            s.name as driver_name,
            COALESCE(SUM(l.cost), 0) as total_spend,
            v.assigned_driver_id, v.tracker_url, v.service_due
        FROM vehicles v 
        LEFT JOIN staff s ON v.assigned_driver_id = s.id 
        LEFT JOIN maintenance_logs l ON v.id = l.vehicle_id
        WHERE v.company_id = %s
        GROUP BY v.id, s.name
        ORDER BY v.reg_plate
    """, (comp_id,))
    
    raw_vehicles = cur.fetchall()
    vehicles = []
    today = date.today()

    for row in raw_vehicles:
        v_id = row[0]
        cur.execute("SELECT date, type, description, cost FROM maintenance_logs WHERE vehicle_id = %s ORDER BY date DESC", (v_id,))
        history = [{'date': r[0], 'type': r[1], 'desc': r[2], 'cost': r[3]} for r in cur.fetchall()]

        vehicles.append({
            'id': row[0],
            'reg_number': row[1],
            'make_model': row[2],
            'status': row[3],
            'mot_due': parse_date(row[4]),
            'tax_due': parse_date(row[5]),
            'ins_due': parse_date(row[6]),
            'driver': row[7],
            'total_spend': row[8],
            'assigned_driver_id': row[9],
            'tracker_url': row[10],
            'service_due': parse_date(row[11]),
            'history': history
        })
        
    cur.execute("SELECT id, name FROM staff WHERE company_id = %s", (comp_id,))
    staff_list = cur.fetchall()
    conn.close()
    
    return render_template('finance/finance_fleet.html', vehicles=vehicles, staff=staff_list, today=today, brand_color=config['color'], logo_url=config['logo'])
    
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

@finance_bp.route('/finance/materials/import', methods=['POST'])
def import_materials():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    if 'file' not in request.files:
        flash('❌ No file part')
        return redirect(url_for('finance.finance_materials'))
        
    file = request.files['file']
    if file.filename == '':
        flash('❌ No selected file')
        return redirect(url_for('finance.finance_materials'))

    if file and file.filename.endswith('.csv'):
        company_id = session.get('company_id')
        conn = get_db()
        cur = conn.cursor()
        
        try:
            # Parse CSV
            csv_file = TextIOWrapper(file, encoding='utf-8')
            csv_reader = csv.reader(csv_file, delimiter=',')
            
            # Skip Header Row
            next(csv_reader, None) 
            
            # Loop through rows
            count = 0
            for row in csv_reader:
                if len(row) >= 3: 
                    sku = row[0].strip() if len(row) > 0 else ''
                    name = row[1].strip() if len(row) > 1 else 'Unknown Item'
                    category = row[2].strip() if len(row) > 2 else 'General'
                    unit = row[3].strip() if len(row) > 3 else 'Each'
                    cost = row[4].strip().replace('£', '').replace('$', '') if len(row) > 4 else '0'
                    supplier = row[5].strip() if len(row) > 5 else ''
                    
                    cur.execute("""
                        INSERT INTO materials (company_id, sku, name, category, unit, cost_price, supplier)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (company_id, sku, name, category, unit, cost, supplier))
                    count += 1
            
            conn.commit()
            flash(f"✅ Successfully Imported {count} Items")
            
        except Exception as e:
            conn.rollback()
            flash(f"❌ Import Error: {e}")
        finally:
            conn.close()
            
    else:
        flash('❌ Invalid File. Please upload a CSV.')
        
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
        est_cost = rev / 1.2
        profit = rev - est_cost
        margin = (profit / rev * 100) if rev > 0 else 0
        total_rev += rev; total_cost += est_cost
        analyzed_jobs.append({"ref": j[0], "client": j[1], "status": "Completed", "rev": rev, "cost": est_cost, "profit": profit, "margin": margin})
    conn.close()
    total_profit = total_rev - total_cost
    avg_margin = (total_profit / total_rev * 100) if total_rev > 0 else 0
    return render_template('finance/finance_analysis.html', jobs=analyzed_jobs, total_rev=total_rev, total_cost=total_cost, total_profit=total_profit, avg_margin=avg_margin, brand_color=config['color'], logo_url=config['logo'])


# --- 6. SETTINGS REDIRECT ---
@finance_bp.route('/finance/settings')
def settings_redirect():
    return redirect(url_for('finance.settings_general'))

# --- 6A. SETTINGS: GENERAL (Updated to include SMTP) ---
@finance_bp.route('/finance/settings/general', methods=['GET', 'POST'])
def settings_general():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        try:
            # NOW INCLUDES SMTP SETTINGS HERE
            keys = ['company_name', 'company_email', 'company_phone', 'company_website', 'company_address', 'brand_color',
                    'smtp_host', 'smtp_port', 'smtp_email', 'smtp_password'] # <--- Moved here
            
            for key in keys:
                val = request.form.get(key)
                cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, %s, %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, key, val))
            
            # Logo Logic
            if 'logo' in request.files:
                file = request.files['logo']
                if file and allowed_file(file.filename):
                    filename = secure_filename(f"logo_{comp_id}_{file.filename}")
                    file.save(os.path.join(UPLOAD_FOLDER, filename))
                    db_path = f"/static/uploads/logos/{filename}"
                    cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'logo_url', %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, db_path))
            
            conn.commit(); flash("✅ Profile & Email Settings Saved")
        except Exception as e: conn.rollback(); flash(f"Error: {e}")

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    
    return render_template('finance/settings_general.html', settings=settings, active_tab='general', brand_color=config['color'], logo_url=config['logo'])
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        try:
            for key in ['company_name', 'company_email', 'company_phone', 'company_website', 'company_address', 'brand_color']:
                val = request.form.get(key)
                cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, %s, %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, key, val))
            
            if 'logo' in request.files:
                file = request.files['logo']
                if file and allowed_file(file.filename):
                    filename = secure_filename(f"logo_{comp_id}_{file.filename}")
                    file.save(os.path.join(UPLOAD_FOLDER, filename))
                    db_path = f"/static/uploads/logos/{filename}"
                    cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'logo_url', %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, db_path))
            
            conn.commit(); flash("✅ General Settings Saved")
        except Exception as e: conn.rollback(); flash(f"Error: {e}")

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    
    return render_template('finance/settings_general.html', settings=settings, active_tab='general', brand_color=config['color'], logo_url=config['logo'])


# --- 6B. SETTINGS: COMPLIANCE (Updated with VAT Logic) ---
@finance_bp.route('/finance/settings/compliance', methods=['GET', 'POST'])
def settings_compliance():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        try:
            # Handle Checkbox: If missing in form, it means "no"
            vat_val = 'yes' if request.form.get('vat_registered') else 'no'
            
            # Save VAT Status manually
            cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'vat_registered', %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, vat_val))

            # Save the rest
            for key, val in request.form.items():
                if key != 'vat_registered': 
                    cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, %s, %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, key, val))
            
            conn.commit(); flash("✅ Compliance & VAT Settings Saved")
        except Exception as e: conn.rollback(); flash(f"Error: {e}")

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    
    return render_template('finance/settings_compliance.html', settings=settings, active_tab='compliance', brand_color=config['color'], logo_url=config['logo'])

# --- 6C. SETTINGS: BANKING (Updated to remove SMTP, Keep Markup) ---
@finance_bp.route('/finance/settings/banking', methods=['GET', 'POST'])
def settings_banking():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        try:
            # REMOVED SMTP KEYS from here
            # KEPT Banking, Footer, and Profit Drivers
            keys_to_save = ['bank_name', 'account_number', 'sort_code', 'payment_terms', 
                            'invoice_footer', 'quote_footer', 
                            'default_markup', 'default_profit_margin'] 
            
            for key in keys_to_save:
                val = request.form.get(key)
                if val is not None:
                    cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, %s, %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, key, val))
            
            # QR Code Logic
            if 'payment_qr' in request.files:
                file = request.files['payment_qr']
                if file and allowed_file(file.filename):
                    filename = secure_filename(f"qr_{comp_id}_{file.filename}")
                    file.save(os.path.join(UPLOAD_FOLDER, filename))
                    db_path = f"/static/uploads/logos/{filename}"
                    cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'payment_qr_url', %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, db_path))

            conn.commit(); flash("✅ Banking & Defaults Saved")
        except Exception as e: conn.rollback(); flash(f"Error: {e}")

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    
    return render_template('finance/settings_banking.html', settings=settings, active_tab='banking', brand_color=config['color'], logo_url=config['logo'])

# --- 6D. SETTINGS: OVERHEADS ---
@finance_bp.route('/finance/settings/overheads', methods=['GET', 'POST'])
def settings_overheads():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'add_category':
                cur.execute("INSERT INTO overhead_categories (company_id, name) VALUES (%s, %s)", (comp_id, request.form.get('category_name')))
                flash("✅ Category Added")
            elif action == 'add_item':
                cur.execute("INSERT INTO overhead_items (category_id, name, amount) VALUES (%s, %s, %s)", (request.form.get('category_id'), request.form.get('item_name'), request.form.get('item_cost')))
                flash("✅ Cost Added")
            elif action == 'delete_item':
                cur.execute("DELETE FROM overhead_items WHERE id = %s", (request.form.get('item_id'),))
                flash("🗑️ Item Removed")
            elif action == 'delete_category':
                cur.execute("DELETE FROM overhead_categories WHERE id = %s AND company_id = %s", (request.form.get('category_id'), comp_id))
                flash("🗑️ Category Removed")
            
            conn.commit()
        except Exception as e:
            conn.rollback(); flash(f"Error: {e}")

    # Fetch Data
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    cur.execute("SELECT id, name FROM overhead_categories WHERE company_id = %s ORDER BY id ASC", (comp_id,))
    categories_raw = cur.fetchall()
    
    overheads = []
    total_overhead = 0.0
    
    for cat in categories_raw:
        cur.execute("SELECT id, name, amount FROM overhead_items WHERE category_id = %s", (cat[0],))
        items = cur.fetchall()
        cat_total = sum([float(i[2]) for i in items])
        total_overhead += cat_total
        overheads.append({'id': cat[0], 'name': cat[1], 'items': items, 'total': cat_total})

    conn.close()
    return render_template('finance/settings_overheads.html', settings=settings, overheads=overheads, total_overhead=total_overhead, active_tab='overheads', brand_color=config['color'], logo_url=config['logo'])