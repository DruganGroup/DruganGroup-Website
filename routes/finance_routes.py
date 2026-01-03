from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
import secrets
import string
import os
import csv
from io import TextIOWrapper
from datetime import datetime, date 
from db import get_db, get_site_config, allowed_file, UPLOAD_FOLDER
from email_service import send_company_email
from services.pdf_generator import generate_pdf
from flask import send_file

finance_bp = Blueprint('finance', __name__)

# --- CONFIG: DATE FORMATS BY COUNTRY ---
COUNTRY_FORMATS = {
    'United Kingdom': '%d/%m/%Y',
    'Ireland': '%d/%m/%Y',
    'United States': '%m/%d/%Y',
    'Canada': '%Y-%m-%d',
    'Australia': '%d/%m/%Y',
    'Germany': '%d.%m.%Y',
    'France': '%d/%m/%Y',
    'Spain': '%d/%m/%Y',
    'Italy': '%d/%m/%Y',
    'Netherlands': '%d-%m-%Y',
    'Default': '%d/%m/%Y' # Fallback
}

# --- HELPER: GET COMPANY DATE FORMAT ---
def get_date_fmt_str(company_id):
    """Fetches the company country and returns the python date format string"""
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'company_country'", (company_id,))
        row = cur.fetchone()
        conn.close()
        country = row[0] if row else 'Default'
        return COUNTRY_FORMATS.get(country, COUNTRY_FORMATS['Default'])
    except:
        return COUNTRY_FORMATS['Default']

# --- HELPER: FORMAT A DATE STRING (FOR DISPLAY) ---
def format_date(d, fmt_str):
    """Formats a DB date object or string into the company preference"""
    if not d: return ""
    try:
        if isinstance(d, str):
            try: d = datetime.strptime(d, '%Y-%m-%d')
            except: 
                try: d = datetime.strptime(d, '%Y-%m-%d %H:%M:%S')
                except: return d
        return d.strftime(fmt_str)
    except: return str(d)

# --- HELPER: PARSE DB DATE (FOR MATH) ---
def parse_date(d):
    """Ensures we have a real Date Object for math"""
    if isinstance(d, str):
        try: return datetime.strptime(d, '%Y-%m-%d').date()
        except: return None
    return d

# --- 1. OVERVIEW ---
@finance_bp.route('/finance-dashboard')
def finance_dashboard():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    company_id = session.get('company_id'); config = get_site_config(company_id)
    conn = get_db(); cur = conn.cursor()

    # Get User's Date Format
    date_fmt = get_date_fmt_str(company_id)

    cur.execute("CREATE TABLE IF NOT EXISTS transactions (id SERIAL PRIMARY KEY, company_id INTEGER, date DATE, type TEXT, category TEXT, description TEXT, amount DECIMAL(10,2), reference TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()

    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,))
    income = cur.fetchone()[0] or 0.0
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Expense'", (company_id,))
    expense = cur.fetchone()[0] or 0.0
    balance = income - expense

    cur.execute("SELECT date, type, category, description, amount, reference FROM transactions WHERE company_id = %s ORDER BY date DESC LIMIT 20", (company_id,))
    raw_transactions = cur.fetchall()
    
    # Format transactions dynamically
    transactions = [(format_date(t[0], date_fmt), t[1], t[2], t[3], t[4], t[5]) for t in raw_transactions]
    
    conn.close()
    return render_template('finance/finance_dashboard.html', total_income=income, total_expense=expense, total_balance=balance, transactions=transactions, brand_color=config['color'], logo_url=config['logo'])

# --- 1.5 SALES LEDGER ---
@finance_bp.route('/finance/invoices')
def finance_invoices():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    company_id = session.get('company_id'); config = get_site_config(company_id)
    conn = get_db(); cur = conn.cursor()
    
    date_fmt = get_date_fmt_str(company_id)
    
    cur.execute("SELECT i.id, i.reference, c.name, i.date, i.due_date, i.total, i.status FROM invoices i JOIN clients c ON i.client_id = c.id WHERE i.company_id = %s ORDER BY i.date DESC", (company_id,))
    invoices = []
    for r in cur.fetchall():
        invoices.append({
            'id': r[0], 'ref': r[1], 'client': r[2], 
            'date': format_date(r[3], date_fmt), 
            'due': format_date(r[4], date_fmt), 
            'total': r[5], 'status': r[6]
        })
        
    conn.close()
    return render_template('finance/finance_invoices.html', invoices=invoices, brand_color=config['color'], logo_url=config['logo'])
    
    # --- 1.6 GENERATE PDF INVOICE ---
@finance_bp.route('/finance/invoice/<int:invoice_id>/pdf')
def download_invoice_pdf(invoice_id):
    # Security Check
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office', 'Manager']: 
        return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    
    # 1. Fetch Invoice & Client Data
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT i.id, i.reference, i.date, i.due_date, i.total, i.status, 
               c.name, c.email, c.billing_address, c.phone, c.site_address
        FROM invoices i
        JOIN clients c ON i.client_id = c.id
        WHERE i.id = %s AND i.company_id = %s
    """, (invoice_id, company_id))
    inv = cur.fetchone()
    
    if not inv:
        conn.close()
        return "Invoice not found", 404
        
    invoice_data = {
        'id': inv[0], 'ref': inv[1], 'date': inv[2], 'due_date': inv[3],
        'total': inv[4], 'status': inv[5],
        'client_name': inv[6], 'client_email': inv[7], 
        'client_address': inv[8], 'client_phone': inv[9], 'site_address': inv[10]
    }

    # 2. Fetch Line Items
    cur.execute("SELECT description, quantity, unit_price, total FROM invoice_items WHERE invoice_id = %s", (invoice_id,))
    items = [{'desc': r[0], 'qty': r[1], 'price': r[2], 'total': r[3]} for r in cur.fetchall()]
    
    # 3. Fetch Company Settings (For Logo/Colors)
    config = get_site_config(company_id)
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    
    # 4. Generate PDF
    # We pass all the data to the HTML template
    context = {
        'invoice': invoice_data,
        'items': items,
        'settings': settings,
        'config': config,
        'company': {'name': session.get('company_name')}
    }
    
    filename = f"Invoice_{invoice_data['ref']}.pdf"
    
    try:
        # This calls the service to create the file in your uploads folder
        pdf_path = generate_pdf('finance/pdf_invoice_template.html', context, filename)
        
        # 5. Download the file to the user's computer
        return send_file(pdf_path, as_attachment=True, download_name=filename)
    except Exception as e:
        return f"Error generating PDF: {e}"

# --- 2. HR & STAFF ---
@finance_bp.route('/finance/hr')
def finance_hr():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, name, position, dept, pay_rate, pay_model, access_level, email, phone, employment_type, address, tax_id FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    cols = [desc[0] for desc in cur.description]; staff = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
    return render_template('finance/finance_hr.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

@finance_bp.route('/finance/hr/add', methods=['POST'])
def add_staff():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    form = request.form
    comp_id = session.get('company_id'); conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO staff (company_id, name, position, dept, pay_rate, pay_model, access_level, email, phone, address, employment_type, tax_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                   (comp_id, form.get('name'), form.get('position'), form.get('dept'), form.get('rate') or 0, form.get('model'), form.get('access_level'), form.get('email'), form.get('phone'), form.get('address'), form.get('employment_type'), form.get('tax_id')))
        
        email = form.get('email')
        if form.get('access_level') != "None" and email:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            if not cur.fetchone():
                pw = ''.join(secrets.choice(string.ascii_letters + string.digits) for i in range(12))
                cur.execute("INSERT INTO users (username, email, password_hash, role, company_id) VALUES (%s, %s, %s, %s, %s)", (email, email, generate_password_hash(pw), form.get('access_level'), comp_id))
                success, msg = send_company_email(comp_id, email, "Your Login Details", f"<p>Username: {email}</p><p>Password: {pw}</p>")
                flash("✅ Staff Added & Email Sent" if success else f"⚠️ Staff Added. Email failed: {msg}")
            else: flash("⚠️ Staff added (User exists)")
        else: flash("✅ Staff Added")
        conn.commit()
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('finance.finance_hr'))

@finance_bp.route('/finance/hr/update', methods=['POST'])
def update_staff():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor(); form = request.form
    try:
        cur.execute("UPDATE staff SET name=%s, position=%s, email=%s, phone=%s, address=%s, employment_type=%s, dept=%s, pay_rate=%s, pay_model=%s, tax_id=%s, access_level=%s WHERE id=%s AND company_id=%s", 
                   (form.get('name'), form.get('position'), form.get('email'), form.get('phone'), form.get('address'), form.get('employment_type'), form.get('dept'), form.get('rate') or 0, form.get('model'), form.get('tax_id'), form.get('access_level'), form.get('staff_id'), session.get('company_id')))
        conn.commit(); flash("✅ Staff Updated")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('finance.finance_hr'))

@finance_bp.route('/finance/hr/delete/<int:id>')
def delete_staff(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM staff WHERE id = %s AND company_id = %s", (id, session.get('company_id')))
    conn.commit(); conn.close()
    return redirect(url_for('finance.finance_hr'))

# --- 3. FINANCE FLEET (THE FULL VERSION) ---
@finance_bp.route('/finance/fleet', methods=['GET', 'POST'])
def finance_fleet():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    
    # 1. Get Dynamic Format
    date_fmt_str = get_date_fmt_str(comp_id)

    cur.execute("CREATE TABLE IF NOT EXISTS vehicle_crew (vehicle_id INTEGER, staff_id INTEGER, PRIMARY KEY(vehicle_id, staff_id))"); conn.commit()
    
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'assign_crew':
                v_id = request.form.get('vehicle_id'); crew_ids = request.form.getlist('crew_ids')
                cur.execute("DELETE FROM vehicle_crew WHERE vehicle_id = %s", (v_id,))
                for staff_id in crew_ids: cur.execute("INSERT INTO vehicle_crew (vehicle_id, staff_id) VALUES (%s, %s)", (v_id, staff_id))
                flash("✅ Crew Updated")
            elif action == 'add_log':
                cur.execute("INSERT INTO maintenance_logs (company_id, vehicle_id, type, description, date, cost) VALUES (%s, %s, %s, %s, %s, %s)", 
                           (comp_id, request.form.get('vehicle_id'), request.form.get('log_type'), request.form.get('description'), request.form.get('date'), request.form.get('cost') or 0))
                flash("✅ Log Added")
            elif action == 'add_vehicle' or action == 'update_vehicle':
                reg = request.form.get('reg_number') or request.form.get('reg_plate')
                driver = request.form.get('driver_id'); driver = None if driver in ['None', ''] else driver
                mot = request.form.get('mot_expiry') or None; tax = request.form.get('tax_due') or None
                ins = request.form.get('insurance_due') or None; serv = request.form.get('service_due') or None
                
                if action == 'add_vehicle':
                    cur.execute("INSERT INTO vehicles (company_id, reg_plate, make_model, assigned_driver_id, daily_cost, mot_due, tax_due, insurance_due, service_due, tracker_url, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Active')", 
                               (comp_id, reg, request.form.get('make_model'), driver, request.form.get('daily_cost') or 0, mot, tax, ins, serv, request.form.get('tracker_url')))
                    flash("✅ Vehicle Added")
                else:
                    cur.execute("UPDATE vehicles SET reg_plate=%s, make_model=%s, assigned_driver_id=%s, status=%s, mot_due=%s, tax_due=%s, insurance_due=%s, service_due=%s, tracker_url=%s, daily_cost=%s WHERE id=%s", 
                               (reg, request.form.get('make_model'), driver, request.form.get('status'), mot, tax, ins, serv, request.form.get('tracker_url'), request.form.get('daily_cost') or 0, request.form.get('vehicle_id')))
                    flash("✅ Vehicle Updated")
            conn.commit()
        except Exception as e: conn.rollback(); flash(f"Error: {e}")

    # FETCH VEHICLES - KEEP DATES AS OBJECTS for math
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.status, v.mot_due, v.tax_due, v.insurance_due,
            s.name, v.assigned_driver_id, v.tracker_url, v.service_due, COALESCE(v.daily_cost, 0),
            s.pay_rate, s.pay_model
        FROM vehicles v LEFT JOIN staff s ON v.assigned_driver_id = s.id 
        WHERE v.company_id = %s ORDER BY v.reg_plate
    """, (comp_id,))
    
    raw_vehicles = cur.fetchall(); vehicles = []; cur2 = conn.cursor()

    for row in raw_vehicles:
        v_id = row[0]; daily_van = float(row[11]); driver_rate = float(row[12] or 0)
        driver_cost = driver_rate * 8 if row[13] == 'Hour' else driver_rate
        
        cur2.execute("SELECT s.id, s.name, s.position, s.pay_rate, s.pay_model FROM vehicle_crew vc JOIN staff s ON vc.staff_id = s.id WHERE vc.vehicle_id = %s", (v_id,))
        crew = []; crew_cost = 0
        for c in cur2.fetchall():
            c_cost = (float(c[3] or 0) * 8) if c[4] == 'Hour' else float(c[3] or 0)
            crew_cost += c_cost; crew.append({'id': c[0], 'name': c[1], 'role': c[2]})
        
        cur2.execute("SELECT COALESCE(SUM(cost), 0) FROM maintenance_logs WHERE vehicle_id = %s", (v_id,))
        spend = cur2.fetchone()[0]
        
        # History Logs (Format string for display)
        cur2.execute("SELECT date, type, description, cost FROM maintenance_logs WHERE vehicle_id = %s ORDER BY date DESC", (v_id,))
        history = [{'date': format_date(r[0], date_fmt_str), 'type': r[1], 'desc': r[2], 'cost': r[3]} for r in cur2.fetchall()]

        vehicles.append({
            'id': row[0], 'reg_number': row[1], 'make_model': row[2], 'status': row[3],
            'mot_expiry': parse_date(row[4]),  # KEEP OBJECT for calculation
            'tax_expiry': parse_date(row[5]),  # KEEP OBJECT
            'ins_expiry': parse_date(row[6]),  # KEEP OBJECT
            'service_due': parse_date(row[10]),# KEEP OBJECT
            'driver_name': row[7], 'total_spend': spend, 'assigned_driver_id': row[8],
            'tracker_url': row[9], 'daily_cost': daily_van, 'total_gang_cost': daily_van + driver_cost + crew_cost,
            'crew': crew, 'history': history
        })
        
    cur.execute("SELECT id, name FROM staff WHERE company_id = %s ORDER BY name", (comp_id,)); staff = [dict(zip(['id', 'name'], r)) for r in cur.fetchall()]
    cur2.close(); conn.close()
    
    # PASS 'date_fmt' to template so it can format the Date Objects
    return render_template('finance/finance_fleet.html', vehicles=vehicles, staff=staff, today=date.today(), date_fmt=date_fmt_str, brand_color=config['color'], logo_url=config['logo'])

@finance_bp.route('/finance/fleet/delete/<int:id>')
def delete_vehicle(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM vehicles WHERE id=%s AND company_id=%s", (id, session.get('company_id')))
    conn.commit(); conn.close()
    return redirect(url_for('finance.finance_fleet'))

# --- 4. MATERIALS & 5. ANALYSIS & 6. SETTINGS ---
@finance_bp.route('/finance/materials')
def finance_materials():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS materials (id SERIAL PRIMARY KEY, company_id INTEGER, sku TEXT, name TEXT, category TEXT, unit TEXT, cost_price DECIMAL(10,2), supplier TEXT);"); conn.commit()
    cur.execute("SELECT id, sku, name, category, unit, cost_price, supplier FROM materials WHERE company_id = %s ORDER BY name", (comp_id,))
    materials = [{'id': m[0], 'sku': m[1], 'name': m[2], 'category': m[3], 'unit': m[4], 'price': m[5], 'supplier': m[6]} for m in cur.fetchall()]
    conn.close()
    return render_template('finance/finance_materials.html', materials=materials, brand_color=config['color'], logo_url=config['logo'])

@finance_bp.route('/finance/materials/add', methods=['POST'])
def add_material():
    conn = get_db(); cur = conn.cursor()
    try: cur.execute("INSERT INTO materials (company_id, sku, name, category, unit, cost_price, supplier) VALUES (%s, %s, %s, %s, %s, %s, %s)", (session.get('company_id'), request.form.get('sku'), request.form.get('name'), request.form.get('category'), request.form.get('unit'), request.form.get('price'), request.form.get('supplier'))); conn.commit(); flash("Item Added")
    except: conn.rollback()
    finally: conn.close()
    return redirect(url_for('finance.finance_materials'))

@finance_bp.route('/finance/materials/delete/<int:id>')
def delete_material(id):
    conn = get_db(); cur = conn.cursor(); cur.execute("DELETE FROM materials WHERE id=%s", (id,)); conn.commit(); conn.close()
    return redirect(url_for('finance.finance_materials'))

@finance_bp.route('/finance/materials/import', methods=['POST'])
def import_materials():
    if 'file' in request.files:
        file = request.files['file']
        if file and file.filename.endswith('.csv'):
            conn = get_db(); cur = conn.cursor(); csv_file = TextIOWrapper(file, encoding='utf-8'); csv_reader = csv.reader(csv_file); next(csv_reader, None)
            for row in csv_reader:
                if len(row) >= 3: cur.execute("INSERT INTO materials (company_id, sku, name, category, unit, cost_price, supplier) VALUES (%s, %s, %s, %s, %s, %s, %s)", (session.get('company_id'), row[0], row[1], row[2], row[3] if len(row)>3 else '', row[4] if len(row)>4 else 0, row[5] if len(row)>5 else ''))
            conn.commit(); conn.close(); flash("Imported")
    return redirect(url_for('finance.finance_materials'))

@finance_bp.route('/finance/analysis')
def finance_analysis():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT reference, description, amount FROM transactions WHERE company_id = %s AND type = 'Income' ORDER BY date DESC LIMIT 50", (comp_id,))
    analyzed_jobs = []; total_rev = 0; total_cost = 0
    for j in cur.fetchall():
        rev = float(j[2]); est_cost = rev / 1.2; profit = rev - est_cost
        total_rev += rev; total_cost += est_cost
        analyzed_jobs.append({"ref": j[0], "client": j[1], "status": "Completed", "rev": rev, "cost": est_cost, "profit": profit, "margin": (profit/rev*100) if rev>0 else 0})
    conn.close()
    return render_template('finance/finance_analysis.html', jobs=analyzed_jobs, total_rev=total_rev, total_cost=total_cost, total_profit=total_rev-total_cost, avg_margin=((total_rev-total_cost)/total_rev*100) if total_rev>0 else 0, brand_color=config['color'], logo_url=config['logo'])

@finance_bp.route('/finance/settings')
def settings_redirect(): return redirect(url_for('finance.settings_general'))

# --- SETTINGS: GENERAL TAB (Session Sync Fix) ---
@finance_bp.route('/finance/settings/general', methods=['GET', 'POST'])
def settings_general():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        try:
            # 1. Update Text Settings
            fields = [
                'company_name', 'company_website', 'company_email', 'company_phone', 
                'company_address', 'brand_color', 'smtp_host', 'smtp_port', 
                'smtp_email', 'smtp_password', 'pdf_theme',
                'country_code', 'currency_symbol', 'date_format',
                'company_reg_number', 'tax_id', 'vat_registered'
            ]
            
            for field in fields:
                val = request.form.get(field)
                if val is not None:
                    cur.execute("""
                        INSERT INTO settings (company_id, key, value) 
                        VALUES (%s, %s, %s) 
                        ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value
                    """, (comp_id, field, val))

            # [FIX] Update Session immediately so Sidebar doesn't stay blue
            new_color = request.form.get('brand_color')
            if new_color:
                session['brand_color'] = new_color

            # 2. Handle Logo Upload
            if 'logo' in request.files:
                f = request.files['logo']
                if f and f.filename != '':
                    # Ensure directory exists
                    save_dir = os.path.join(current_app.static_folder, 'uploads', str(comp_id))
                    os.makedirs(save_dir, exist_ok=True)
                    
                    # Save File
                    filename = secure_filename(f"logo_{int(datetime.now().timestamp())}.png")
                    full_path = os.path.join(save_dir, filename)
                    f.save(full_path)
                    
                    # Save to DB
                    web_path = f"/static/uploads/{comp_id}/{filename}"
                    cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'logo', %s) ON CONFLICT (company_id, key) DO UPDATE SET value=EXCLUDED.value", (comp_id, web_path))
                    
                    # [FIX] Update Session immediately
                    session['logo'] = web_path

            conn.commit()
            flash("✅ Settings Saved & Sidebar Updated")
            
        except Exception as e:
            conn.rollback()
            flash(f"Error saving settings: {e}")

    # GET REQUEST: Fetch settings
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()

    return render_template('finance/settings_general.html', 
                           settings=settings, 
                           active_tab='general')

@finance_bp.route('/finance/settings/banking', methods=['GET', 'POST'])
def settings_banking():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    if request.method == 'POST':
        for k in ['bank_name', 'account_number', 'sort_code', 'payment_terms', 'invoice_footer', 'quote_footer', 'default_markup', 'default_profit_margin']:
             cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, %s, %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, k, request.form.get(k)))
        if 'payment_qr' in request.files:
             f = request.files['payment_qr']
             if f and allowed_file(f.filename):
                 fn = secure_filename(f"qr_{comp_id}_{f.filename}"); f.save(os.path.join(UPLOAD_FOLDER, fn))
                 cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'payment_qr_url', %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, f"/static/uploads/logos/{fn}"))
        conn.commit(); flash("Saved")
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,)); settings = {row[0]: row[1] for row in cur.fetchall()}; conn.close()
    return render_template('finance/settings_banking.html', settings=settings, active_tab='banking', brand_color=config['color'], logo_url=config['logo'])

@finance_bp.route('/finance/settings/overheads', methods=['GET', 'POST'])
def settings_overheads():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    if request.method == 'POST':
        act = request.form.get('action')
        if act == 'add_category': cur.execute("INSERT INTO overhead_categories (company_id, name) VALUES (%s, %s)", (comp_id, request.form.get('category_name')))
        elif act == 'add_item': cur.execute("INSERT INTO overhead_items (category_id, name, amount) VALUES (%s, %s, %s)", (request.form.get('category_id'), request.form.get('item_name'), request.form.get('item_cost')))
        elif act == 'delete_item': cur.execute("DELETE FROM overhead_items WHERE id = %s", (request.form.get('item_id'),))
        elif act == 'delete_category': cur.execute("DELETE FROM overhead_categories WHERE id = %s AND company_id = %s", (request.form.get('category_id'), comp_id))
        conn.commit()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,)); settings = {row[0]: row[1] for row in cur.fetchall()}
    cur.execute("SELECT id, name FROM overhead_categories WHERE company_id = %s ORDER BY id ASC", (comp_id,)); cats = cur.fetchall()
    class CO:
        def __init__(self, i, n, it, t): self.id=i; self.name=n; self.items=it; self.total=t
    overheads = []; tot = 0
    for c in cats:
        cur.execute("SELECT id, name, amount FROM overhead_items WHERE category_id = %s", (c[0],)); items = cur.fetchall()
        ct = sum([float(i[2]) for i in items]); tot += ct; overheads.append(CO(c[0], c[1], items, ct))
    conn.close()
    return render_template('finance/settings_overheads.html', settings=settings, overheads=overheads, total_overhead=tot, active_tab='overheads', brand_color=config['color'], logo_url=config['logo'])
    
    # --- DATABASE MIGRATION: ADD TEMPLATE SUPPORT ---
@finance_bp.route('/finance/setup-templates')
def setup_invoice_templates():
    if session.get('role') != 'SuperAdmin': 
        return "Access Denied: SuperAdmin only", 403
    
    conn = get_db()
    cur = conn.cursor()
    try:
        # This adds the column to store the choice (modern vs classic)
        cur.execute("ALTER TABLE settings ADD COLUMN IF NOT EXISTS value TEXT;") # Ensure structure
        cur.execute("""
            INSERT INTO settings (company_id, key, value) 
            VALUES (%s, 'invoice_template', 'modern') 
            ON CONFLICT (company_id, key) DO NOTHING;
        """, (session.get('company_id'),))
        
        conn.commit()
        return "✅ Database Updated: Template support added. You can now use the settings page."
    except Exception as e:
        conn.rollback()
        return f"❌ Migration Error: {e}"
    finally:
        conn.close()