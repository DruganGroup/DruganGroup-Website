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
# Safe import for telematics
try:
    from telematics_engine import get_tracker_data
except ImportError:
    get_tracker_data = None

finance_bp = Blueprint('finance', __name__)

# --- CONFIG: DATE FORMATS BY COUNTRY ---
COUNTRY_FORMATS = {
    'United Kingdom': '%d/%m/%Y',
    'United States': '%m/%d/%Y',
    'Default': '%d/%m/%Y'
}

# --- HELPER: GET COMPANY DATE FORMAT ---
def get_date_fmt_str(company_id):
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

    # 2. Fetch Invoices
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
            'ref': r[1], 
            'client': r[2], 
            'date': format_date(r[3], date_fmt), 
            'due': format_date(r[4], date_fmt), 
            'total': r[5], 
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
        cur.execute("""
            INSERT INTO staff (company_id, name, position, dept, pay_rate, pay_model, access_level, email, phone, address, employment_type, tax_id) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, form.get('name'), form.get('position'), form.get('dept'), form.get('rate') or 0, form.get('model'), form.get('access_level'), form.get('email'), form.get('phone'), form.get('address'), form.get('employment_type'), form.get('tax_id')))
        
        email = form.get('email')
        if form.get('access_level') != "None" and email:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            if not cur.fetchone():
                pw = ''.join(secrets.choice(string.ascii_letters + string.digits) for i in range(12))
                cur.execute("INSERT INTO users (username, email, password_hash, role, company_id) VALUES (%s, %s, %s, %s, %s)", (email, email, generate_password_hash(pw), form.get('access_level'), comp_id))
                
                success, msg = send_company_email(comp_id, email, "Your Login Details", f"<p>Username: {email}</p><p>Password: {pw}</p>")
                flash("✅ Staff Added & Email Sent" if success else f"⚠️ Staff Added. Email failed: {msg}")
            else: 
                flash("⚠️ Staff added (User login already exists)")
        else: 
            flash("✅ Staff Added")

        try:
            admin_name = session.get('user_name', 'Admin')
            cur.execute("""
                INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                VALUES (%s, 'STAFF_ADDED', %s, %s, %s, CURRENT_TIMESTAMP)
            """, (comp_id, form.get('name'), f"New Staff: {form.get('position')} ({form.get('dept')})", admin_name))
        except Exception as e:
            print(f"Audit Log Error: {e}")

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
        
        try:
            admin_name = session.get('user_name', 'Admin')
            cur.execute("""
                INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                VALUES (%s, 'STAFF_UPDATE', %s, 'HR Profile Updated', %s, CURRENT_TIMESTAMP)
            """, (session.get('company_id'), form.get('name'), admin_name))
        except: pass

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

# --- FINANCE: FLEET MANAGER ---
@finance_bp.route('/finance/fleet', methods=['GET', 'POST'])
def finance_fleet():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        
        try:
            if action == 'add_vehicle':
                reg = request.form.get('reg_number').upper() 
                model = request.form.get('make_model')
                daily = request.form.get('daily_cost') or 0.00
                tracker = request.form.get('tracker_url')
                
                mot = request.form.get('mot_expiry') or None
                tax = request.form.get('tax_expiry') or None
                ins = request.form.get('ins_expiry') or None

                cur.execute("""
                    INSERT INTO vehicles (company_id, reg_plate, make_model, daily_cost, tracker_url, status, mot_expiry, tax_expiry, ins_expiry)
                    VALUES (%s, %s, %s, %s, %s, 'Active', %s, %s, %s)
                """, (comp_id, reg, model, daily, tracker, mot, tax, ins))
                flash("✅ Vehicle added successfully.")

            elif action == 'assign_crew':
                veh_id = request.form.get('vehicle_id')
                daily = request.form.get('daily_cost')
                
                mot = request.form.get('mot_expiry') or None
                tax = request.form.get('tax_expiry') or None
                ins = request.form.get('ins_expiry') or None
                tracker_url = request.form.get('tracker_url')

                cur.execute("""
                    UPDATE vehicles 
                    SET daily_cost = %s, mot_expiry = %s, tax_expiry = %s, ins_expiry = %s,
                        tracker_url = %s
                    WHERE id = %s AND company_id = %s
                """, (daily, mot, tax, ins, tracker_url, veh_id, comp_id))

                crew_ids = request.form.getlist('crew_ids')
                cur.execute("DELETE FROM vehicle_crew WHERE vehicle_id = %s", (veh_id,))
                for staff_id in crew_ids:
                    cur.execute("INSERT INTO vehicle_crew (vehicle_id, staff_id) VALUES (%s, %s)", (veh_id, staff_id))
                
                flash("✅ Vehicle updated successfully.")

            conn.commit()
            
        except Exception as e:
            conn.rollback()
            flash(f"Error: {e}")

    # --- GET REQUEST ---
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.daily_cost, v.status, 
               v.assigned_driver_id, s.name as driver_name, 
               v.tracker_url, 
               v.mot_expiry, v.tax_expiry, v.ins_expiry
        FROM vehicles v
        LEFT JOIN staff s ON v.assigned_driver_id = s.id
        WHERE v.company_id = %s
        ORDER BY v.reg_plate
    """, (comp_id,))
    
    vehicles_raw = cur.fetchall()
    vehicles = []
    
    for r in vehicles_raw:
        v_id = r[0]
        daily_cost = r[3] or 0.0

        cur.execute("""
            SELECT s.name, s.pay_rate, s.pay_model 
            FROM vehicle_crew vc
            JOIN staff s ON vc.staff_id = s.id
            WHERE vc.vehicle_id = %s
        """, (v_id,))
        crew = cur.fetchall()
        
        total_wages = 0
        crew_list = []
        for c in crew:
            name, rate, model = c
            if model == 'Hour': total_wages += (rate * 8)
            elif model == 'Day': total_wages += rate
            elif model == 'Year': total_wages += (rate / 260)
            crew_list.append({'name': name})
            
        total_daily_run = float(daily_cost) + float(total_wages)

        vehicles.append({
            'id': v_id,
            'reg_number': r[1],
            'make_model': r[2],
            'daily_cost': daily_cost,
            'status': r[4],
            'assigned_driver_id': r[5],
            'driver_name': r[6],
            'tracker_url': r[7],
            'mot_expiry': r[8],
            'tax_expiry': r[9],
            'ins_expiry': r[10],
            'crew': crew_list,
            'total_gang_cost': total_daily_run
        })

    conn.close()
    
    return render_template('finance/finance_fleet.html', 
                           vehicles=vehicles, 
                           today=datetime.now().date(),
                           date_fmt='%d/%m/%Y')
                           
@finance_bp.route('/finance/fleet/delete/<int:id>')
def delete_vehicle(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        cur.execute("UPDATE jobs SET vehicle_id = NULL WHERE vehicle_id = %s AND status != 'Completed'", (id,))
        cur.execute("UPDATE quotes SET preferred_vehicle_id = NULL WHERE preferred_vehicle_id = %s", (id,))
        cur.execute("DELETE FROM vehicle_crew WHERE vehicle_id = %s", (id,))
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

    try:
        cur.execute("CREATE TABLE IF NOT EXISTS suppliers (id SERIAL PRIMARY KEY, company_id INTEGER, name VARCHAR(100));")
        cur.execute("ALTER TABLE materials ADD COLUMN IF NOT EXISTS supplier_id INTEGER;")
        conn.commit()
    except Exception as e:
        conn.rollback()

    cur.execute("SELECT id, name FROM suppliers WHERE company_id = %s ORDER BY name", (comp_id,))
    suppliers = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]

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
        cur.execute("UPDATE materials SET supplier_id = NULL WHERE supplier_id = %s", (id,))
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
        supplier_id = request.form.get('supplier_id')
        
        if file and file.filename.endswith('.csv'):
            conn = get_db(); cur = conn.cursor()
            try:
                csv_file = TextIOWrapper(file, encoding='utf-8')
                csv_reader = csv.reader(csv_file)
                next(csv_reader, None) # Skip Header
                
                count = 0
                for row in csv_reader:
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

@finance_bp.route('/api/materials/search')
def search_materials_api():
    if 'user_id' not in session: return jsonify([])
    
    query = request.args.get('q', '').lower()
    if not query: return jsonify([])

    comp_id = session.get('company_id')
    conn = get_db()
    cur = conn.cursor()
    
    try:
        try:
            cur.execute("SELECT 1 FROM materials WHERE company_id=%s LIMIT 1", (comp_id,))
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='materials'")
            columns = [row[0] for row in cur.fetchall()]
            price_col = 'cost_price' if 'cost_price' in columns else 'price'
        except:
            price_col = 'cost_price' 
            conn.rollback()

        sql = f"""
            SELECT m.name, s.name, COALESCE(m.{price_col}, 0), m.sku 
            FROM materials m 
            LEFT JOIN suppliers s ON m.supplier_id = s.id 
            WHERE m.company_id = %s AND LOWER(m.name) LIKE %s 
            ORDER BY m.name ASC 
            LIMIT 10
        """
        cur.execute(sql, (comp_id, f"%{query}%"))
        
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
        conn.rollback()
        return jsonify([])
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
        cur.execute("SELECT COALESCE(SUM(total), 0) FROM invoices WHERE job_id=%s AND status!='Void'", (job_id,))
        revenue = float(cur.fetchone()[0])

        cur.execute("SELECT COALESCE(SUM(cost), 0) FROM job_expenses WHERE job_id=%s", (job_id,))
        expenses = float(cur.fetchone()[0])
        
        cur.execute("SELECT COALESCE(SUM(t.total_hours * s.pay_rate), 0) FROM staff_timesheets t JOIN staff s ON t.staff_id=s.id WHERE t.job_id=%s", (job_id,))
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

            new_name = request.form.get('company_name')
            if new_name: session['company_name'] = new_name

            vat_val = 'yes' if request.form.get('vat_registered') else 'no'
            cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'vat_registered', %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, vat_val))

            new_color = request.form.get('brand_color')
            if new_color: session['brand_color'] = new_color

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

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()

    return render_template('finance/settings_general.html', settings=settings, active_tab='general')

@finance_bp.route('/finance/settings/banking', methods=['GET', 'POST'])
def settings_banking():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'POST':
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
             
        if 'payment_qr' in request.files:
             f = request.files['payment_qr']
             if f and allowed_file(f.filename):
                 fn = secure_filename(f"qr_{comp_id}_{f.filename}")
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
    
@finance_bp.route('/finance/setup-templates')
def setup_invoice_templates():
    if session.get('role') != 'SuperAdmin': 
        return "Access Denied: SuperAdmin only", 403
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE settings ADD COLUMN IF NOT EXISTS value TEXT;") 
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

@finance_bp.route('/finance/invoice/<int:invoice_id>/email')
def email_invoice(invoice_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']:
        return redirect(url_for('auth.login'))
        
    conn = get_db(); cur = conn.cursor()
    company_id = session.get('company_id')

    cur.execute("""
        SELECT i.id, i.reference, i.date, i.total, i.status, 
               c.name, c.email, c.address
        FROM invoices i
        JOIN clients c ON i.client_id = c.id
        WHERE i.id = %s AND i.company_id = %s
    """, (invoice_id, company_id))
    
    inv = cur.fetchone()
    
    if not inv:
        conn.close(); flash("❌ Invoice not found.", "error")
        return redirect(url_for('finance.finance_invoices'))

    client_email = inv[6]
    invoice_ref = inv[1]

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    if 'smtp_host' not in settings:
        conn.close(); flash("⚠️ SMTP Settings missing.", "warning")
        return redirect(url_for('finance.finance_invoices'))

    cur.execute("SELECT description, quantity, unit_price, total FROM invoice_items WHERE invoice_id = %s", (invoice_id,))
    items = [{'desc': r[0], 'qty': r[1], 'price': r[2], 'total': r[3]} for r in cur.fetchall()]
    
    config = get_site_config(company_id)
    
    if config.get('logo') and config['logo'].startswith('/'):
        clean_path = config['logo'].lstrip('/')
        local_path = os.path.join(current_app.root_path, clean_path)
        if os.path.exists(local_path):
            config['logo'] = local_path

    total_val = float(inv[3]) if inv[3] else 0.0
    
    context = {
        'invoice': {
            'ref': inv[1], 'date': inv[2], 'due': inv[2],
            'client_name': inv[5], 'client_address': inv[7], 'client_email': inv[6],
            'total': total_val, 'subtotal': total_val, 'tax': 0.0,
            'currency_symbol': settings.get('currency_symbol', '£')
        },
        'company': {'name': session.get('company_name')},
        'items': items, 
        'settings': settings, 
        'config': config 
    }

    filename = f"Invoice_{invoice_ref}.pdf"
    
    try:
        pdf_path = generate_pdf('finance/pdf_invoice_template.html', context, filename)
        
        msg = MIMEMultipart()
        msg['From'] = settings.get('smtp_email')
        msg['To'] = client_email
        msg['Subject'] = f"Invoice {invoice_ref} from {session.get('company_name')}"
        
        body = f"Dear {inv[5]},\n\nPlease find attached invoice {invoice_ref}.\n\nTotal Due: {settings.get('currency_symbol','£')}{total_val:.2f}\n\nKind regards,\n{session.get('company_name')}"
        msg.attach(MIMEText(body, 'plain'))
        
        with open(pdf_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            msg.attach(part)

        server = smtplib.SMTP(settings['smtp_host'], int(settings.get('smtp_port', 587)))
        server.starttls()
        server.login(settings['smtp_email'], settings['smtp_password'])
        server.send_message(msg)
        server.quit()
        
        cur.execute("UPDATE invoices SET status = 'Sent' WHERE id = %s", (invoice_id,))
        conn.commit()
        flash(f"✅ Invoice emailed to {client_email}!", "success")

    except Exception as e:
        flash(f"❌ Email Error: {e}", "error")
    
    conn.close()
    return redirect(url_for('finance.finance_invoices'))

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
        cur.execute("DELETE FROM invoice_items WHERE invoice_id = %s", (invoice_id,))
        cur.execute("DELETE FROM invoices WHERE id = %s", (invoice_id,))
        conn.commit()
        flash("✅ Invoice deleted successfully.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error deleting invoice: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('finance.finance_invoices'))
    
@finance_bp.route('/finance-dashboard')
def finance_dashboard():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT value FROM settings WHERE key='currency_symbol' AND company_id=%s", (comp_id,))
    res = cur.fetchone()
    currency = res[0] if res else '£'

    cur.execute("""
        SELECT COALESCE(SUM(total), 0) 
        FROM invoices 
        WHERE company_id = %s AND status != 'Void'
    """, (comp_id,))
    total_income = float(cur.fetchone()[0])

    cur.execute("SELECT COALESCE(SUM(cost), 0) FROM maintenance_logs WHERE company_id = %s", (comp_id,))
    fleet_cost = float(cur.fetchone()[0])
    
    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM overhead_items JOIN overhead_categories c ON overhead_items.category_id = c.id WHERE c.company_id = %s", (comp_id,))
    monthly_overhead = float(cur.fetchone()[0])
    
    total_expense = fleet_cost + monthly_overhead
    total_balance = total_income - total_expense
    break_even = (monthly_overhead * 12) / 365 if monthly_overhead > 0 else 0

    query = """
        (
            SELECT 
                date_created as date, 
                'Income' as type, 
                'Sales' as category, 
                ref || ' - ' || COALESCE((SELECT name FROM clients WHERE id = invoices.client_id), 'Unknown Client') as description, 
                COALESCE(total, 0) as amount, 
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
                COALESCE(description, 'Uncategorized Expense'), 
                COALESCE(cost, 0) as amount, 
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
                COALESCE(amount, 0) as amount,
                NULL as job_id
            FROM overhead_items 
            WHERE category_id IN (SELECT id FROM overhead_categories WHERE company_id = %s)
        )
        ORDER BY date DESC 
        LIMIT 15
    """
    cur.execute(query, (comp_id, comp_id, comp_id))
    transactions = cur.fetchall()

    chart_labels = []
    chart_income = []
    chart_expense = []
    
    today = date.today()
    for i in range(5, -1, -1):
        d = today - timedelta(days=i*30)
        month_str = d.strftime("%B")
        chart_labels.append(month_str)
        
        cur.execute("""
            SELECT COALESCE(SUM(total), 0) FROM invoices 
            WHERE company_id=%s AND EXTRACT(MONTH FROM date)=%s AND EXTRACT(YEAR FROM date)=%s
        """, (comp_id, d.month, d.year))
        chart_income.append(float(cur.fetchone()[0]))
        
        cur.execute("""
            SELECT COALESCE(SUM(cost), 0) FROM maintenance_logs 
            WHERE company_id=%s AND EXTRACT(MONTH FROM date)=%s AND EXTRACT(YEAR FROM date)=%s
        """, (comp_id, d.month, d.year))
        chart_expense.append(float(cur.fetchone()[0]) + monthly_overhead)

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