from flask import Blueprint, render_template, request, session, redirect, url_for, flash, get_flashed_messages, send_file, Response, make_response, current_app, jsonify
from services.enforcement import check_limit
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
import secrets
import string
import os
import csv
from io import TextIOWrapper
from datetime import datetime, date, timedelta
from db import get_db, get_site_config, allowed_file, UPLOAD_FOLDER
from email_service import send_company_email
from email.mime.application import MIMEApplication
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from services.pdf_generator import generate_pdf
from flask import send_file
from telematics_engine import get_tracker_data

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

@finance_bp.route('/finance/invoices')
def finance_invoices():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: 
        return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    config = get_site_config(company_id)
    conn = get_db(); cur = conn.cursor()
    date_fmt = get_date_fmt_str(company_id)

    # 1. Get Currency
    cur.execute("SELECT value FROM settings WHERE key='currency_symbol' AND company_id=%s", (company_id,))
    res = cur.fetchone(); currency = res[0] if res else '£'

    # 2. Fetch Invoices (UPDATED to match DB: reference, date, total)
    cur.execute("""
        SELECT i.id, i.reference, c.name, i.date, i.due_date, i.total, i.status 
        FROM invoices i 
        JOIN clients c ON i.client_id = c.id 
        WHERE i.company_id = %s 
        ORDER BY i.date DESC
    """, (company_id,))
    
    invoices = []
    for r in cur.fetchall():
        invoices.append({
            'id': r[0], 
            'ref': r[1],          # Pulling from 'reference' column
            'client': r[2], 
            'date': format_date(r[3], date_fmt), 
            'due': format_date(r[4], date_fmt), 
            'total': r[5],        # Pulling from 'total' column
            'status': r[6]
        })
        
    conn.close()
    
    return render_template('finance/finance_invoices.html', 
                           invoices=invoices, 
                           brand_color=config['color'], 
                           logo_url=config['logo'],
                           currency=currency)
                           
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
    
    allowed, msg = check_limit(session['company_id'], 'max_users')
    if not allowed:
        flash(msg, "error")
        return redirect(url_for('finance.finance_hr'))
        
    form = request.form
    comp_id = session.get('company_id')
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # 1. Insert Staff Member
        cur.execute("""
            INSERT INTO staff (company_id, name, position, dept, pay_rate, pay_model, access_level, email, phone, address, employment_type, tax_id) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, form.get('name'), form.get('position'), form.get('dept'), form.get('rate') or 0, form.get('model'), form.get('access_level'), form.get('email'), form.get('phone'), form.get('address'), form.get('employment_type'), form.get('tax_id')))
        
        # 2. Create User Login (If Access Level is set)
        email = form.get('email')
        if form.get('access_level') != "None" and email:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            if not cur.fetchone():
                pw = ''.join(secrets.choice(string.ascii_letters + string.digits) for i in range(12))
                cur.execute("INSERT INTO users (username, email, password_hash, role, company_id) VALUES (%s, %s, %s, %s, %s)", (email, email, generate_password_hash(pw), form.get('access_level'), comp_id))
                
                # Send Welcome Email
                success, msg = send_company_email(comp_id, email, "Your Login Details", f"<p>Username: {email}</p><p>Password: {pw}</p>")
                flash("✅ Staff Added & Email Sent" if success else f"⚠️ Staff Added. Email failed: {msg}")
            else: 
                flash("⚠️ Staff added (User login already exists)")
        else: 
            flash("✅ Staff Added")

        # 3. AUDIT LOG (The Missing Piece)
        try:
            admin_name = session.get('user_name', 'Admin')
            cur.execute("""
                INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                VALUES (%s, 'STAFF_ADDED', %s, %s, %s, CURRENT_TIMESTAMP)
            """, (comp_id, form.get('name'), f"New Staff: {form.get('position')} ({form.get('dept')})", admin_name))
        except Exception as e:
            print(f"Audit Log Error: {e}")

        # 4. SAVE EVERYTHING
        conn.commit()

    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('finance.finance_hr'))

@finance_bp.route('/finance/hr/update', methods=['POST'])
def update_staff():
    if session.get('role') not in ['Admin', 'SuperAdmin']: 
        return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    form = request.form
    
    try:
        cur.execute("""
            UPDATE staff 
            SET name=%s, position=%s, email=%s, phone=%s, address=%s, 
                employment_type=%s, dept=%s, 
                pay_rate=%s, pay_model=%s, 
                tax_id=%s, access_level=%s 
            WHERE id=%s AND company_id=%s
        """, (
            form.get('name'), 
            form.get('position'), 
            form.get('email'), 
            form.get('phone'), 
            form.get('address'), 
            form.get('employment_type'), 
            form.get('dept'), 
            form.get('pay_rate') or 0,
            form.get('pay_model'),
            form.get('tax_id'), 
            form.get('access_level'), 
            form.get('staff_id'), 
            session.get('company_id')
        ))
        # --- AUDIT LOG (UPDATE) ---
        try:
            admin_name = session.get('user_name', 'Admin')
            cur.execute("""
                INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                VALUES (%s, 'STAFF_UPDATE', %s, 'HR Profile Updated', %s, CURRENT_TIMESTAMP)
            """, (session.get('company_id'), form.get('name'), admin_name))
        except Exception as e:
            print(f"Audit Log Error: {e}")
        # --------------------------        
        conn.commit()
        flash("✅ Staff Details & Wages Updated")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
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

@finance_bp.route('/finance/fleet', methods=['GET', 'POST'])
def finance_fleet():
    if session.get('role') not in ['Admin', 'SuperAdmin']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    # 1. Get Dynamic Format
    date_fmt_str = get_date_fmt_str(comp_id)

    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'assign_crew':
                v_id = request.form.get('vehicle_id')
                crew_ids = request.form.getlist('crew_ids')
                
                # 1. Update Crew
                cur.execute("DELETE FROM vehicle_crew WHERE vehicle_id = %s", (v_id,))
                for staff_id in crew_ids:
                    cur.execute("INSERT INTO vehicle_crew (vehicle_id, staff_id) VALUES (%s, %s)", (v_id, staff_id))
                
                # 2. Update Settings & Cost (The "Super Save")
                daily = request.form.get('daily_cost')
                tracker = request.form.get('tracker_url')
                provider = request.form.get('telematics_provider')
                dev_id = request.form.get('tracking_device_id')
                
                if daily is not None:
                     cur.execute("""
                        UPDATE vehicles 
                        SET daily_cost=%s, tracker_url=%s, telematics_provider=%s, tracking_device_id=%s 
                        WHERE id=%s AND company_id=%s
                    """, (daily, tracker, provider, dev_id, v_id, comp_id))

                flash("✅ Crew, Cost & Tracker Updated")

            elif action == 'add_log':
                cur.execute("INSERT INTO maintenance_logs (company_id, vehicle_id, type, description, date, cost) VALUES (%s, %s, %s, %s, %s, %s)", 
                           (comp_id, request.form.get('vehicle_id'), request.form.get('log_type'), request.form.get('description'), request.form.get('date'), request.form.get('cost') or 0))
                flash("✅ Log Added")

            elif action == 'update_settings':
                v_id = request.form.get('vehicle_id')
                cur.execute("""
                    UPDATE vehicles 
                    SET daily_cost=%s, tracker_url=%s, telematics_provider=%s, tracking_device_id=%s 
                    WHERE id=%s AND company_id=%s
                """, (
                    request.form.get('daily_cost'), 
                    request.form.get('tracker_url'),
                    request.form.get('telematics_provider'),
                    request.form.get('tracking_device_id'),
                    v_id, 
                    comp_id
                ))
                flash("✅ Vehicle Cost & Tracker Settings Updated")

            elif action == 'add_vehicle' or action == 'update_vehicle':
                reg = request.form.get('reg_number') or request.form.get('reg_plate')
                driver = request.form.get('driver_id')
                driver = None if driver in ['None', ''] else driver
                
                mot = request.form.get('mot_expiry') or None
                tax = request.form.get('tax_due') or None
                ins = request.form.get('insurance_due') or None
                serv = request.form.get('service_due') or None
                
                tracker = request.form.get('tracker_url')
                provider = request.form.get('telematics_provider')
                dev_id = request.form.get('tracking_device_id')
                daily = request.form.get('daily_cost') or 0
                model = request.form.get('make_model')
                status = request.form.get('status') or 'Active'
                
                if action == 'add_vehicle':
                    allowed, msg = check_limit(comp_id, 'max_vehicles')
                    if not allowed:
                        flash(msg, "error")
                        return redirect(url_for('finance.finance_fleet'))

                    cur.execute("""
                        INSERT INTO vehicles (company_id, reg_plate, make_model, assigned_driver_id, daily_cost, mot_due, tax_due, insurance_due, service_due, tracker_url, status, telematics_provider, tracking_device_id) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Active', %s, %s)
                    """, (comp_id, reg, model, driver, daily, mot, tax, ins, serv, tracker, provider, dev_id))
                    flash("✅ Vehicle Added")
                else:
                    v_id = request.form.get('vehicle_id')
                    cur.execute("""
                        UPDATE vehicles SET reg_plate=%s, make_model=%s, assigned_driver_id=%s, status=%s, mot_due=%s, tax_due=%s, insurance_due=%s, service_due=%s, tracker_url=%s, daily_cost=%s 
                        WHERE id=%s AND company_id=%s
                    """, (reg, model, driver, status, mot, tax, ins, serv, tracker, daily, v_id, comp_id))
                    flash("✅ Vehicle Updated")

            conn.commit()
        except Exception as e:
            conn.rollback()
            flash(f"Error: {e}")

    # FETCH VEHICLES
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.status, v.mot_due, v.tax_due, v.insurance_due,
            s.name, v.assigned_driver_id, v.tracker_url, v.service_due, COALESCE(v.daily_cost, 0),
            s.pay_rate, s.pay_model,
            v.telematics_provider, v.tracking_device_id
        FROM vehicles v LEFT JOIN staff s ON v.assigned_driver_id = s.id 
        WHERE v.company_id = %s ORDER BY v.reg_plate
    """, (comp_id,))
    
    raw_vehicles = cur.fetchall()
    vehicles = []
    cur2 = conn.cursor()

    for row in raw_vehicles:
        v_id = row[0]
        daily_van = float(row[11])
        driver_rate = float(row[12] or 0)
        driver_cost = driver_rate * 8 if row[13] == 'Hour' else driver_rate
        
        provider = row[14]
        device_id = row[15]
        
        # Telematics Fetch
        telematics_data = None
        if provider and device_id:
            try:
                # Placeholder for your real tracking call
                telematics_data = get_tracker_data(provider, "KEY", device_id)
                if telematics_data:
                    telematics_data['last_updated'] = datetime.now().strftime("%H:%M")
            except: pass

        cur2.execute("SELECT s.id, s.name, s.position, s.pay_rate, s.pay_model FROM vehicle_crew vc JOIN staff s ON vc.staff_id = s.id WHERE vc.vehicle_id = %s", (v_id,))
        crew = []
        crew_cost = 0
        for c in cur2.fetchall():
            c_cost = (float(c[3] or 0) * 8) if c[4] == 'Hour' else float(c[3] or 0)
            crew_cost += c_cost
            crew.append({'id': c[0], 'name': c[1], 'role': c[2]})
        
        cur2.execute("SELECT COALESCE(SUM(cost), 0) FROM maintenance_logs WHERE vehicle_id = %s", (v_id,))
        spend = cur2.fetchone()[0]
        
        cur2.execute("SELECT date, type, description, cost FROM maintenance_logs WHERE vehicle_id = %s ORDER BY date DESC", (v_id,))
        history = [{'date': format_date(r[0], date_fmt_str), 'type': r[1], 'desc': r[2], 'cost': r[3]} for r in cur2.fetchall()]

        vehicles.append({
            'id': row[0], 'reg_number': row[1], 'make_model': row[2], 'status': row[3],
            'mot_expiry': parse_date(row[4]),  
            'tax_expiry': parse_date(row[5]),  
            'ins_expiry': parse_date(row[6]),  
            'service_due': parse_date(row[10]),
            'driver_name': row[7], 'total_spend': spend, 'assigned_driver_id': row[8],
            'tracker_url': row[9], 'daily_cost': daily_van, 'total_gang_cost': daily_van + driver_cost + crew_cost,
            'crew': crew, 'history': history,
            'telematics_provider': provider,
            'tracking_device_id': device_id,
            'telematics_data': telematics_data
        })
        
    cur.execute("SELECT id, name FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    staff = [dict(zip(['id', 'name'], r)) for r in cur.fetchall()]
    
    cur2.close()
    conn.close()
    
    return render_template('finance/finance_fleet.html', vehicles=vehicles, staff=staff, today=date.today(), date_fmt=date_fmt_str, brand_color=config['color'], logo_url=config['logo'])

@finance_bp.route('/finance/fleet/delete/<int:id>')
def delete_vehicle(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # 1. Unlink from Active Jobs (Remove from schedule)
        cur.execute("UPDATE jobs SET vehicle_id = NULL WHERE vehicle_id = %s AND status != 'Completed'", (id,))
        
        # 2. Unlink from Quotes (Stop suggesting it for new work)
        cur.execute("UPDATE quotes SET preferred_vehicle_id = NULL WHERE preferred_vehicle_id = %s", (id,))
        
        # 3. Remove Driver & Crew (Free up staff)
        cur.execute("DELETE FROM vehicle_crew WHERE vehicle_id = %s", (id,))
        
        # 4. ARCHIVE (Soft Delete) - This keeps your Finance Logs safe!
        cur.execute("""
            UPDATE vehicles 
            SET status = 'Archived', 
                assigned_driver_id = NULL, 
                daily_cost = 0,
                reg_plate = reg_plate || ' (Archived)'
            WHERE id=%s AND company_id=%s
        """, (id, session.get('company_id')))
        
        conn.commit()
        flash("✅ Vehicle archived. Logs kept for finance records.", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"❌ Could not archive vehicle: {e}", "error")
        
    finally:
        conn.close()
        
    return redirect(url_for('finance.finance_fleet'))

# =========================================================
# 4. MATERIALS & SUPPLIERS (UPGRADED)
# =========================================================

@finance_bp.route('/finance/materials')
def finance_materials():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    # --- 1. DATABASE AUTO-FIX (The Magic Fix) ---
    try:
        # Create Suppliers Table
        cur.execute("CREATE TABLE IF NOT EXISTS suppliers (id SERIAL PRIMARY KEY, company_id INTEGER, name VARCHAR(100));")
        
        # Add 'supplier_id' column if it's missing
        cur.execute("ALTER TABLE materials ADD COLUMN IF NOT EXISTS supplier_id INTEGER;")
        conn.commit()

        # OPTIONAL: Convert old text 'supplier' to new 'supplier_id'
        # This checks if you have a 'supplier' text column and migrates data
        try:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='materials' AND column_name='supplier'")
            if cur.fetchone():
                cur.execute("SELECT id, supplier FROM materials WHERE supplier_id IS NULL AND supplier IS NOT NULL AND supplier != ''")
                old_items = cur.fetchall()
                
                for item in old_items:
                    m_id, s_name = item
                    # Find or Create Supplier
                    cur.execute("SELECT id FROM suppliers WHERE name = %s AND company_id = %s", (s_name, comp_id))
                    row = cur.fetchone()
                    if row:
                        s_id = row[0]
                    else:
                        cur.execute("INSERT INTO suppliers (company_id, name) VALUES (%s, %s) RETURNING id", (comp_id, s_name))
                        s_id = cur.fetchone()[0]
                    
                    # Update the material link
                    cur.execute("UPDATE materials SET supplier_id = %s WHERE id = %s", (s_id, m_id))
                conn.commit()
        except Exception as e:
            print(f"Migration warning (can ignore): {e}")
            conn.rollback()

    except Exception as e:
        conn.rollback()
        print(f"DB Setup Error: {e}")

    # --- 2. FETCH DATA (Now safe to run) ---
    cur.execute("SELECT id, name FROM suppliers WHERE company_id = %s ORDER BY name", (comp_id,))
    suppliers = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]

    # We select Supplier Name via JOIN now
    cur.execute("""
        SELECT m.id, m.sku, m.name, m.category, m.unit, m.cost_price, s.name 
        FROM materials m 
        LEFT JOIN suppliers s ON m.supplier_id = s.id 
        WHERE m.company_id = %s 
        ORDER BY m.name ASC
    """, (comp_id,))
    
    materials = [{
        'id': m[0], 'sku': m[1], 'name': m[2], 'category': m[3], 
        'unit': m[4], 'price': m[5], 'supplier': m[6] or 'General'
    } for m in cur.fetchall()]

    conn.close()
    return render_template('finance/finance_materials.html', 
                           materials=materials, 
                           suppliers=suppliers, 
                           brand_color=config['color'], 
                           logo_url=config['logo'])

@finance_bp.route('/finance/suppliers/add', methods=['POST'])
def add_supplier():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO suppliers (company_id, name) VALUES (%s, %s)", (session.get('company_id'), request.form.get('name')))
        conn.commit(); flash("✅ Supplier Added")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('finance.finance_materials'))
    
@finance_bp.route('/finance/suppliers/delete/<int:id>')
def delete_supplier(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Option A: Delete the supplier AND all their materials
        # cur.execute("DELETE FROM materials WHERE supplier_id = %s", (id,))
        
        # Option B: Delete supplier, but keep materials (they become 'General')
        cur.execute("UPDATE materials SET supplier_id = NULL WHERE supplier_id = %s", (id,))
        
        # Finally, delete the supplier
        cur.execute("DELETE FROM suppliers WHERE id = %s", (id,))
        conn.commit()
        flash("✅ Supplier deleted.")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
    finally:
        conn.close()

    return redirect(url_for('finance.finance_materials'))

@finance_bp.route('/finance/materials/import', methods=['POST'])
def import_materials():
    if 'file' in request.files:
        file = request.files['file']
        supplier_id = request.form.get('supplier_id') # The ID of the supplier selected in the dropdown
        
        if file and file.filename.endswith('.csv'):
            conn = get_db(); cur = conn.cursor()
            try:
                # Optional: Clear old items from this supplier first? 
                # cur.execute("DELETE FROM materials WHERE supplier_id = %s", (supplier_id,))
                
                csv_file = TextIOWrapper(file, encoding='utf-8')
                csv_reader = csv.reader(csv_file)
                next(csv_reader, None) # Skip Header
                
                count = 0
                for row in csv_reader:
                    # Expecting CSV: SKU, Name, Category, Unit, Cost
                    if len(row) >= 2: 
                        sku = row[0]
                        name = row[1]
                        cat = row[2] if len(row) > 2 else 'General'
                        unit = row[3] if len(row) > 3 else 'Each'
                        cost = row[4] if len(row) > 4 else 0.00
                        
                        cur.execute("""
                            INSERT INTO materials (company_id, sku, name, category, unit, cost_price, supplier_id) 
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (session.get('company_id'), sku, name, cat, unit, cost, supplier_id))
                        count += 1
                
                conn.commit()
                flash(f"✅ Imported {count} items successfully.")
            except Exception as e:
                conn.rollback()
                flash(f"❌ Import Error: {e}")
            finally:
                conn.close()
                
    return redirect(url_for('finance.finance_materials'))

@finance_bp.route('/finance/materials/delete/<int:id>')
def delete_material(id):
    conn = get_db(); cur = conn.cursor(); cur.execute("DELETE FROM materials WHERE id=%s", (id,)); conn.commit(); conn.close()
    return redirect(url_for('finance.finance_materials'))

# --- API: LIVE MATERIAL SEARCH (Robust Version) ---
@finance_bp.route('/api/materials/search')
def search_materials_api():
    # 1. Safety Checks
    if 'user_id' not in session: 
        return jsonify([])
    
    query = request.args.get('q', '').lower()
    if not query: 
        return jsonify([])

    comp_id = session.get('company_id')
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # 2. Determine if we should use 'cost_price' or 'price'
        # We try to select 'cost_price'. If it fails, we rollback and try 'price'.
        try:
            cur.execute("SELECT 1 FROM materials WHERE company_id=%s LIMIT 1", (comp_id,))
            # Check column names
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='materials'")
            columns = [row[0] for row in cur.fetchall()]
            
            price_col = 'cost_price' if 'cost_price' in columns else 'price'
            
        except:
            price_col = 'cost_price' # Default fallback
            conn.rollback()

        # 3. Run the Search Query (Safe Mode)
        # We use COALESCE to handle NULL prices (converts to 0)
        # We use LEFT JOIN so it works even if Supplier is missing
        sql = f"""
            SELECT m.name, s.name, COALESCE(m.{price_col}, 0), m.sku 
            FROM materials m 
            LEFT JOIN suppliers s ON m.supplier_id = s.id 
            WHERE m.company_id = %s AND LOWER(m.name) LIKE %s 
            ORDER BY m.name ASC 
            LIMIT 10
        """
        
        cur.execute(sql, (comp_id, f"%{query}%"))
        
        # 4. Format Results
        results = []
        for r in cur.fetchall():
            results.append({
                'name': r[0], 
                'supplier': r[1] or 'Generic', 
                'cost': float(r[2]), 
                'sku': r[3]
            })
            
        return jsonify(results)

    except Exception as e:
        # 5. Catch & Print Errors (Look at your console if this happens!)
        print(f"SEARCH API ERROR: {e}")
        conn.rollback()
        return jsonify([]) # Return empty list so page doesn't break
    finally:
        conn.close()

@finance_bp.route('/finance/analysis')
def finance_analysis():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    cur.execute("""
        SELECT j.id, j.ref, c.name, j.status FROM jobs j
        JOIN clients c ON j.client_id = c.id
        WHERE j.company_id = %s AND j.status IN ('Completed', 'In Progress')
        ORDER BY j.start_date DESC
    """, (comp_id,))
    jobs_raw = cur.fetchall()

    analyzed, total_rev, total_cost = [], 0, 0

    for job in jobs_raw:
        job_id, ref, client, status = job
        # UPDATED: Uses 'total' column
        cur.execute("SELECT COALESCE(SUM(total), 0) FROM invoices WHERE job_id=%s AND status!='Void'", (job_id,))
        revenue = float(cur.fetchone()[0])

        cur.execute("SELECT COALESCE(SUM(cost), 0) FROM job_expenses WHERE job_id=%s", (job_id,))
        expenses = float(cur.fetchone()[0])
        
        cur.execute("SELECT COALESCE(SUM(t.hours * s.pay_rate), 0) FROM staff_timesheets t JOIN staff s ON t.staff_id=s.id WHERE t.job_id=%s", (job_id,))
        labor = float(cur.fetchone()[0]) if cur.rowcount > 0 else 0.0

        actual_cost = expenses + labor; profit = revenue - actual_cost
        margin = (profit / revenue * 100) if revenue > 0 else 0.0
        total_rev += revenue; total_cost += actual_cost
        analyzed.append({"ref": ref, "client": client, "status": status, "rev": revenue, "cost": actual_cost, "profit": profit, "margin": margin})
    
    conn.close()
    total_profit = total_rev - total_cost
    avg_margin = (total_profit / total_rev * 100) if total_rev > 0 else 0
    return render_template('finance/finance_analysis.html', jobs=analyzed, total_rev=total_rev, total_cost=total_cost, total_profit=total_profit, avg_margin=avg_margin, brand_color=config['color'], logo_url=config['logo'])
    
@finance_bp.route('/finance/settings')
def settings_redirect(): return redirect(url_for('finance.settings_general'))

# --- SETTINGS: GENERAL TAB ---
@finance_bp.route('/finance/settings/general', methods=['GET', 'POST'])
def settings_general():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        try:
            # 1. Update Text Settings
            # ADD 'default_tax_rate' to this list so it saves!
            fields = [
                'company_name', 'company_website', 'company_email', 'company_phone', 
                'company_address', 'brand_color', 'smtp_host', 'smtp_port', 
                'smtp_email', 'smtp_password', 'pdf_theme',
                'country_code', 'currency_symbol', 'date_format',
                'company_reg_number', 'tax_id', 'default_tax_rate' 
            ]
            
            for field in fields:
                val = request.form.get(field)
                if val is not None:
                    cur.execute("""
                        INSERT INTO settings (company_id, key, value) 
                        VALUES (%s, %s, %s) 
                        ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value
                    """, (comp_id, field, val))

            # 2. HANDLE CHECKBOXES / TOGGLES (The Fix)
            # If unchecked, browsers send NOTHING. We must manually force it to 'no'.
            vat_val = 'yes' if request.form.get('vat_registered') else 'no'
            cur.execute("""
                INSERT INTO settings (company_id, key, value) 
                VALUES (%s, 'vat_registered', %s) 
                ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value
            """, (comp_id, vat_val))

            # [FIX] Update Session immediately so Sidebar doesn't stay blue
            new_color = request.form.get('brand_color')
            if new_color:
                session['brand_color'] = new_color

            # 3. Handle Logo Upload
            if 'logo' in request.files:
                f = request.files['logo']
                if f and f.filename != '':
                    save_dir = os.path.join(current_app.static_folder, 'uploads', str(comp_id))
                    os.makedirs(save_dir, exist_ok=True)
                    
                    filename = secure_filename(f"logo_{int(datetime.now().timestamp())}.png")
                    full_path = os.path.join(save_dir, filename)
                    f.save(full_path)
                    
                    web_path = f"/static/uploads/{comp_id}/{filename}"
                    cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'logo', %s) ON CONFLICT (company_id, key) DO UPDATE SET value=EXCLUDED.value", (comp_id, web_path))
                    
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
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'POST':
        # 1. Save Text Fields
        # We added 'payment_days' and 'quote_footer' to this list so they get saved.
        keys_to_save = [
            'bank_name', 'account_number', 'sort_code', 
            'payment_terms', 'payment_days', 'invoice_footer', 'quote_footer',
            'default_markup', 'default_profit_margin'
        ]
        
        for k in keys_to_save:
             cur.execute("""
                INSERT INTO settings (company_id, key, value) 
                VALUES (%s, %s, %s) 
                ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value
             """, (comp_id, k, request.form.get(k)))
             
        # 2. Save QR Code
        if 'payment_qr' in request.files:
             f = request.files['payment_qr']
             if f and allowed_file(f.filename):
                 fn = secure_filename(f"qr_{comp_id}_{f.filename}")
                 # Ensure upload folder exists
                 os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                 f.save(os.path.join(UPLOAD_FOLDER, fn))
                 
                 cur.execute("""
                    INSERT INTO settings (company_id, key, value) 
                    VALUES (%s, 'payment_qr_url', %s) 
                    ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value
                 """, (comp_id, f"/static/uploads/logos/{fn}"))
        
        conn.commit()
        flash("Saved")
        
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    
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
        # --- EMAIL INVOICE TO CLIENT ---
@finance_bp.route('/finance/invoice/<int:invoice_id>/email')
def email_invoice(invoice_id):
    # 1. Security Check
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']:
        return redirect(url_for('auth.login'))
        
    conn = get_db()
    cur = conn.cursor()
    company_id = session.get('company_id')

    # 2. Fetch Invoice & Client Data
    cur.execute("""
        SELECT i.id, i.reference, i.date, i.total, i.status, 
               c.name, c.email, c.address
        FROM invoices i
        JOIN clients c ON i.client_id = c.id
        WHERE i.id = %s AND i.company_id = %s
    """, (invoice_id, company_id))
    
    if not inv:
        conn.close()
        flash("❌ Invoice not found.", "error")
        return redirect(url_for('finance.finance_invoices'))

    client_email = inv[6]
    invoice_ref = inv[1]

    # 3. Check SMTP Settings
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    if 'smtp_host' not in settings or 'smtp_email' not in settings:
        conn.close()
        flash("⚠️ Cannot Email: SMTP settings missing. Go to Settings > General.", "warning")
        return redirect(url_for('finance.finance_invoices'))

    # 4. Generate the PDF (Server-side)
    # Fetch Items
    cur.execute("SELECT description, quantity, unit_price, total FROM invoice_items WHERE invoice_id = %s", (invoice_id,))
    items = [{'desc': r[0], 'qty': r[1], 'price': r[2], 'total': r[3]} for r in cur.fetchall()]
    
    # Calculate Tax/Net Logic (Reusing your PDF logic)
    total_val = float(inv[3]) if inv[3] else 0.0
    
    # Check VAT Status
    is_vat_registered = settings.get('vat_registered', settings.get('tax_enabled', '0'))
    country_code = settings.get('country', 'GB').upper()
    
    # Simple lookup for tax rate (matches pdf_routes)
    TAX_RATES = {'GB': 20.0, 'ES': 21.0, 'FR': 20.0, 'DE': 19.0, 'IE': 23.0, 'US': 0.0}
    
    if str(is_vat_registered).lower() in ['1', 'true', 'yes', 'on']:
        tax_rate = TAX_RATES.get(country_code, 20.0)
    else:
        tax_rate = 0.0

    divisor = 1 + (tax_rate / 100)
    subtotal = total_val / divisor if divisor > 1 else total_val
    tax = total_val - subtotal

    context = {
        'invoice': {
            'ref': inv[1], 'date': inv[2], 'due': inv[2],
            'client_name': inv[5], 'client_address': inv[7], 'client_email': inv[6],
            'subtotal': subtotal, 'tax': tax, 'total': total_val,
            'tax_rate_display': tax_rate, 'currency_symbol': settings.get('currency_symbol', '£')
        },
        'company': {'name': session.get('company_name')},
        'items': items, 'settings': settings, 'config': get_site_config(company_id)
    }

    filename = f"Invoice_{invoice_ref}.pdf"
    
    try:
        # Generate file path
        pdf_path = generate_pdf('office/pdf_quote.html', context, filename)
        
        # 5. Send Email
        msg = MIMEMultipart()
        msg['From'] = settings.get('smtp_email')
        msg['To'] = client_email
        msg['Subject'] = f"Invoice {invoice_ref} from {session.get('company_name')}"
        
        body = f"Dear {inv[5]},\n\nPlease find attached invoice {invoice_ref}.\n\nTotal Due: {settings.get('currency_symbol','£')}{total_val:.2f}\n\nKind regards,\n{session.get('company_name')}"
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach PDF
        with open(pdf_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            msg.attach(part)

        # Connect to SMTP Server
        server = smtplib.SMTP(settings['smtp_host'], int(settings.get('smtp_port', 587)))
        server.starttls()
        server.login(settings['smtp_email'], settings['smtp_password'])
        server.send_message(msg)
        server.quit()
        
        # 6. Update Status to 'Sent'
        cur.execute("UPDATE invoices SET status = 'Sent' WHERE id = %s", (invoice_id,))
        conn.commit()
        
        flash(f"✅ Invoice emailed to {client_email}!", "success")

    except Exception as e:
        flash(f"❌ Email Error: {e}", "error")
    
    conn.close()
    return redirect(url_for('finance.finance_invoices'))

# --- MANUAL MARK AS SENT ---
@finance_bp.route('/finance/invoice/<int:invoice_id>/mark-sent')
def mark_invoice_sent(invoice_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE invoices SET status = 'Sent' WHERE id = %s", (invoice_id,))
    conn.commit(); conn.close()
    
    flash("✅ Invoice manually marked as Sent.", "success")
    return redirect(url_for('finance.finance_invoices'))
    
@finance_bp.route('/finance/invoice/<int:invoice_id>/delete')
def delete_invoice(invoice_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']:
        return redirect(url_for('auth.login'))
        
    conn = get_db(); cur = conn.cursor()
    try:
        # 1. Delete Items first (Foreign Key constraint)
        cur.execute("DELETE FROM invoice_items WHERE invoice_id = %s", (invoice_id,))
        
        # 2. Delete the Header
        cur.execute("DELETE FROM invoices WHERE id = %s", (invoice_id,))
        
        conn.commit()
        flash("✅ Invoice deleted successfully.", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error deleting invoice: {e}", "error")
        
    finally:
        conn.close()
        
    return redirect(url_for('finance.finance_invoices'))
    
    # --- FINANCE DASHBOARD (The Permanent Fix) ---
@finance_bp.route('/finance-dashboard')
def finance_dashboard():
    # 1. Security Check
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    # 2. Get Settings
    cur.execute("SELECT value FROM settings WHERE key='currency_symbol' AND company_id=%s", (comp_id,))
    res = cur.fetchone()
    currency = res[0] if res else '£'

    # --- 3. LIVE CALCULATIONS ---
    
    # A. TOTAL INCOME (Sum Invoices using the NEW 'total' column)
    cur.execute("""
        SELECT COALESCE(SUM(total), 0) 
        FROM invoices 
        WHERE company_id = %s AND status != 'Void'
    """, (comp_id,))
    total_income = float(cur.fetchone()[0])

    # B. TOTAL EXPENSES (Sum Fleet + Overheads)
    # Fleet Maintenance
    cur.execute("SELECT COALESCE(SUM(cost), 0) FROM maintenance_logs WHERE company_id = %s", (comp_id,))
    fleet_cost = float(cur.fetchone()[0])
    
    # Monthly Overheads (Estimated)
    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM overhead_items JOIN overhead_categories c ON overhead_items.category_id = c.id WHERE c.company_id = %s", (comp_id,))
    monthly_overhead = float(cur.fetchone()[0])
    
    total_expense = fleet_cost + monthly_overhead

    # C. NET BALANCE
    total_balance = total_income - total_expense
    
    # D. BREAK EVEN (Daily)
    break_even = (monthly_overhead * 12) / 365 if monthly_overhead > 0 else 0

    # --- 4. GENERATE VIRTUAL TRANSACTION LIST ---
    # This guarantees the list ALWAYS matches your invoices and logs.
    query = """
        (
            SELECT 
                date_created as date, 
                'Income' as type, 
                'Sales' as category, 
                -- Safe Description: If client is deleted, show 'Unknown Client'
                ref || ' - ' || COALESCE((SELECT name FROM clients WHERE id = invoices.client_id), 'Unknown Client') as description, 
                COALESCE(total, 0) as amount,  -- <--- SHIELD: Forces NULL to 0
                job_id
            FROM invoices 
            WHERE company_id = %s AND status = 'Paid'
        )
        UNION ALL
        (
            SELECT 
                date, 
                'Expense' as type, 
                'Job Cost' as category, 
                COALESCE(description, 'Uncategorized Expense'), -- <--- SHIELD: Prevents empty text
                COALESCE(cost, 0) as amount,   -- <--- SHIELD: Forces NULL to 0
                job_id
            FROM job_expenses 
            WHERE company_id = %s
        )
        UNION ALL
        (
            SELECT 
                date_incurred as date, 
                'Expense' as type, 
                'Overhead' as category, 
                COALESCE(name, 'General Overhead'), 
                COALESCE(amount, 0) as amount, -- <--- SHIELD: Forces NULL to 0
                NULL as job_id
            FROM overhead_items 
            WHERE category_id IN (SELECT id FROM overhead_categories WHERE company_id = %s)
        )
        ORDER BY date DESC 
        LIMIT 15
    """
    cur.execute(query, (comp_id, comp_id, comp_id))
    transactions = cur.fetchall()

    # --- 5. CHART DATA (Last 6 Months) ---
    chart_labels = []
    chart_income = []
    chart_expense = []
    
    today = date.today()
    for i in range(5, -1, -1):
        d = today - timedelta(days=i*30)
        month_str = d.strftime("%B")
        chart_labels.append(month_str)
        
        # Monthly Income
        cur.execute("""
            SELECT COALESCE(SUM(total), 0) FROM invoices 
            WHERE company_id=%s AND EXTRACT(MONTH FROM date)=%s AND EXTRACT(YEAR FROM date)=%s
        """, (comp_id, d.month, d.year))
        chart_income.append(float(cur.fetchone()[0]))
        
        # Monthly Expense
        cur.execute("""
            SELECT COALESCE(SUM(cost), 0) FROM maintenance_logs 
            WHERE company_id=%s AND EXTRACT(MONTH FROM date)=%s AND EXTRACT(YEAR FROM date)=%s
        """, (comp_id, d.month, d.year))
        chart_expense.append(float(cur.fetchone()[0]) + monthly_overhead)

    # --- 6. AUDIT LOGS ---
    cur.execute("""
        SELECT created_at, admin_email, action, details 
        FROM audit_logs 
        WHERE company_id = %s OR company_id IS NULL
        ORDER BY created_at DESC LIMIT 5
    """, (comp_id,))
    raw_logs = cur.fetchall()
    logs = [{'time': format_date(r[0], "%d/%m %H:%M"), 'user': r[1], 'action': r[2], 'details': r[3]} for r in raw_logs]

    conn.close()

    return render_template('finance/finance_dashboard.html',
                           currency_symbol=currency,
                           total_income=total_income,
                           total_expense=total_expense,
                           total_balance=total_balance,
                           break_even=break_even,
                           transactions=transactions,
                           logs=logs,
                           chart_labels=chart_labels,
                           chart_income=chart_income,
                           chart_expense=chart_expense,
                           brand_color=config['color'],
                           logo_url=config['logo'])