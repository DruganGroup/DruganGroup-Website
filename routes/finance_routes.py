from flask import Blueprint, render_template, request, session, redirect, url_for, flash, get_flashed_messages, send_file, Response, make_response, current_app, jsonify
from services.enforcement import check_limit
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
import secrets
import string
from utils.encryption import get_encryptor
import os
import csv
import shutil
from services.tax_engine import TaxEngine
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
try:
    from telematics_engine import get_tracker_data
except ImportError:
    get_tracker_data = None

finance_bp = Blueprint('finance', __name__)

from utils.date_utils import get_date_fmt_str, format_date, parse_date

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
        
    pass
    
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
    pass
    return render_template('finance/finance_hr.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])
    
@finance_bp.route('/finance/hr/delete/<int:id>')
def delete_staff(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM staff WHERE id = %s AND company_id = %s", (id, session.get('company_id')))
    conn.commit(); pass
    return redirect(url_for('finance.finance_hr'))

@finance_bp.route('/finance/fleet', methods=['GET', 'POST'])
def finance_fleet():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        
        from utils.db_utils import db_transaction
        with db_transaction() as t_cur:
            if action == 'add_vehicle':
                reg = request.form.get('reg_number').upper() 
                model = request.form.get('make_model')
                daily = request.form.get('daily_cost') or 0.00
                tracker = request.form.get('tracker_url')
                driver = request.form.get('driver_id') or None
                
                t_cur.execute("""
                    INSERT INTO vehicles (company_id, reg_plate, make_model, daily_cost, tracker_url, assigned_driver_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'Active')
                """, (comp_id, reg, model, daily, tracker, driver))
                flash("✅ Vehicle added successfully.")

            elif action == 'assign_crew': 
                veh_id = request.form.get('vehicle_id')
                daily = request.form.get('daily_cost')
                tracker_url = request.form.get('tracker_url')
                driver_id = request.form.get('driver_id') or None
                if driver_id == 'None': driver_id = None
                
                # Capture the 4 Dates
                mot = request.form.get('mot_expiry') or None
                tax = request.form.get('tax_expiry') or None
                ins = request.form.get('ins_expiry') or None
                serv = request.form.get('service_expiry') or None

                # 1. Update Vehicle Details
                t_cur.execute("""
                    UPDATE vehicles 
                    SET daily_cost = %s, tracker_url = %s, assigned_driver_id = %s,
                        mot_expiry = %s, tax_expiry = %s, ins_expiry = %s, service_expiry = %s
                    WHERE id = %s AND company_id = %s
                """, (daily, tracker_url, driver_id, mot, tax, ins, serv, veh_id, comp_id))

                # 2. Update Crew (Using the correct plural table: vehicle_crews)
                crew_ids = request.form.getlist('crew_ids')
                
                # Clear existing crew
                t_cur.execute("DELETE FROM vehicle_crews WHERE vehicle_id = %s", (veh_id,))
                
                # Insert new crew
                for staff_id in crew_ids:
                    if str(staff_id) != str(driver_id):
                        t_cur.execute("""
                            INSERT INTO vehicle_crews (company_id, vehicle_id, staff_id) 
                            VALUES (%s, %s, %s)
                        """, (comp_id, veh_id, staff_id))
                
                flash("✅ Vehicle & Crew updated.")

    # --- GET REQUEST (DISPLAY DATA) ---
    
    # Fetch API Key for Telematics
    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'samsara_api_key'", (comp_id,))
    row = cur.fetchone()
    company_api_key = row[0] if row else None

    # Fetch Vehicles
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.daily_cost, v.status, 
               v.assigned_driver_id, s.name as driver_name, 
               v.tracker_url, 
               v.mot_expiry, v.tax_expiry, v.ins_expiry, v.service_expiry
        FROM vehicles v
        LEFT JOIN staff s ON v.assigned_driver_id = s.id
        WHERE v.company_id = %s
        ORDER BY v.reg_plate
    """, (comp_id,))
    
    vehicles_raw = cur.fetchall()
    vehicles = []
    
    # Fetch All Staff (For Dropdowns)
    cur.execute("SELECT id, name FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    all_staff = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]
    
    for r in vehicles_raw:
        v_id = r[0]
        daily_cost = r[3] or 0.0
        tracker_url = r[7]

        # 1. Calculate Crew Costs (Using correct plural table: vehicle_crews)
        cur.execute("""
            SELECT s.name, s.pay_rate, s.pay_model 
            FROM vehicle_crews vc
            JOIN staff s ON vc.staff_id = s.id
            WHERE vc.vehicle_id = %s
        """, (v_id,))
        crew = cur.fetchall()
        
        total_wages = 0
        crew_list = []
        for c in crew:
            name, rate, model = c
            if model == 'Hour': total_wages += (float(rate or 0) * 8)
            elif model == 'Day': total_wages += float(rate or 0)
            elif model == 'Year': total_wages += (float(rate or 0) / 260)
            crew_list.append({'name': name})
            
        # Add Driver Cost
        if r[5]: # If assigned_driver_id exists
            cur.execute("SELECT pay_rate, pay_model FROM staff WHERE id = %s", (r[5],))
            d_row = cur.fetchone()
            if d_row:
                d_rate, d_model = d_row
                if d_model == 'Hour': total_wages += (float(d_rate or 0) * 8)
                elif d_model == 'Day': total_wages += float(d_rate or 0)
                elif d_model == 'Year': total_wages += (float(d_rate or 0) / 260)

        total_daily_run = float(daily_cost) + float(total_wages)

        # Telematics Logic
        telematics_data = None
        if tracker_url and get_tracker_data:
            telematics_data = get_tracker_data(tracker_url, api_key=company_api_key)

        vehicles.append({
            'id': v_id,
            'reg_plate': r[1],      # Corrected key
            'make_model': r[2],
            'daily_cost': daily_cost,
            'status': r[4],
            'assigned_driver_id': r[5],
            'driver_name': r[6],
            'tracker_url': tracker_url,
            'mot_expiry': r[8], 
            'tax_expiry': r[9], 
            'ins_expiry': r[10], 
            'service_expiry': r[11], # Added Service Date
            'crew': crew_list,
            'total_gang_cost': total_daily_run,
            'telematics': telematics_data
        })

    pass
    
    return render_template('finance/finance_fleet.html', 
                           vehicles=vehicles, 
                           all_staff=all_staff, 
                           today=date.today(),
                           date_fmt='%d/%m/%Y')
                           
@finance_bp.route('/finance/fleet/delete/<int:id>')
def delete_vehicle(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        cur.execute("UPDATE jobs SET vehicle_id = NULL WHERE vehicle_id = %s AND status != 'Completed'", (id,))
        cur.execute("UPDATE quotes SET preferred_vehicle_id = NULL WHERE preferred_vehicle_id = %s", (id,))
        cur.execute("DELETE FROM vehicle_crews WHERE vehicle_id = %s", (id,))
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
        pass
        
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

    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'default_markup'", (comp_id,))
    markup_row = cur.fetchone()
    if markup_row and markup_row[0]:
        try:
            default_markup = float(markup_row[0])
            markup_missing = False
        except:
            default_markup = 0.0
            markup_missing = True
    else:
        default_markup = 0.0
        markup_missing = True

    pass
    return render_template('finance/finance_materials.html', 
                           materials=materials, 
                           suppliers=suppliers, 
                           brand_color=config['color'], 
                           logo_url=config['logo'],
                           default_markup=default_markup,
                           markup_missing=markup_missing)

@finance_bp.route('/finance/suppliers/add', methods=['POST'])
def add_supplier():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"
    from utils.db_utils import db_transaction
    with db_transaction() as cur:
        cur.execute("INSERT INTO suppliers (company_id, name) VALUES (%s, %s)", (session.get('company_id'), request.form.get('name')))
        flash("✅ Supplier Added")
    return redirect(url_for('finance.finance_materials'))
    
@finance_bp.route('/finance/suppliers/delete/<int:id>')
def delete_supplier(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"
    
    from utils.db_utils import db_transaction
    with db_transaction() as cur:
        cur.execute("UPDATE materials SET supplier_id = NULL WHERE supplier_id = %s", (id,))
        cur.execute("DELETE FROM suppliers WHERE id = %s", (id,))
        flash("✅ Supplier deleted.")

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
                pass
                
    return redirect(url_for('finance.finance_materials'))

@finance_bp.route('/finance/materials/delete/<int:id>')
def delete_material(id):
    from utils.db_utils import db_transaction
    with db_transaction() as cur:
        cur.execute("DELETE FROM materials WHERE id=%s", (id,))
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
        pass

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
        
        cur.execute("""
            SELECT COALESCE(SUM(
                t.total_hours * 
                CASE 
                    WHEN s.pay_model = 'Day' THEN (COALESCE(s.pay_rate, 0) / 8.0)
                    WHEN s.pay_model = 'Year' THEN (COALESCE(s.pay_rate, 0) / (260.0 * 8.0))
                    ELSE COALESCE(s.pay_rate, 0)
                END
            ), 0)
            FROM staff_timesheets t JOIN staff s ON t.staff_id=s.id WHERE t.job_id=%s
        """, (job_id,))
        labor = float(cur.fetchone()[0]) if cur.rowcount > 0 else 0.0

        actual_cost = expenses + labor; profit = revenue - actual_cost
        margin = (profit / revenue * 100) if revenue > 0 else 0.0
        total_rev += revenue; total_cost += actual_cost
        analyzed.append({"ref": ref, "client": client, "status": status, "rev": revenue, "cost": actual_cost, "profit": profit, "margin": margin})
    
    pass
    total_profit = total_rev - total_cost
    avg_margin = (total_profit / total_rev * 100) if total_rev > 0 else 0
    return render_template('finance/finance_analysis.html', jobs=analyzed, total_rev=total_rev, total_cost=total_cost, total_profit=total_profit, avg_margin=avg_margin, brand_color=config['color'], logo_url=config['logo'])
    
@finance_bp.route('/finance/audit-logs')
def finance_audit_logs():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']:
        return redirect(url_for('auth.login'))
        
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT action, target, details, created_at, admin_email 
        FROM audit_logs 
        WHERE company_id = %s 
        ORDER BY created_at DESC LIMIT 100
    """, (comp_id,))
    
    raw_logs = cur.fetchall()
    audit_logs = [{'action': r[0], 'target': r[1], 'details': r[2], 'time': r[3].strftime('%d/%m/%Y %H:%M'), 'user': r[4]} for r in raw_logs]
    pass
    
    return render_template('finance/finance_audit_logs.html', logs=audit_logs, brand_color=config['color'], logo_url=config['logo'])

@finance_bp.route('/finance/settings')
def settings_redirect(): return redirect(url_for('finance.settings_general'))

# --- SETTINGS: GENERAL TAB ---
@finance_bp.route('/finance/settings/general', methods=['GET', 'POST'])
def settings_general():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    encryptor = get_encryptor()

    if request.method == 'POST':
        try:
            fields = [
                'company_name', 'company_website', 'company_email', 'company_phone',
                'company_address', 'brand_color',
                'pdf_theme', 'country_code', 'currency_symbol', 'date_format',
                'company_reg_number', 'tax_id', 'default_tax_rate', 'system_language'
            ]
            
            for field in fields:
                val = request.form.get(field)
                if val is not None:
                    # Encrypt sensitive fields before saving
                    if encryptor.is_encrypted_key(field) and val:
                        val = encryptor.encrypt(val)
                    
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
            
            new_lang = request.form.get('system_language')
            if new_lang: session['lang_code'] = new_lang

            if 'logo' in request.files:
                f = request.files['logo']
                if f and f.filename != '':
                    save_dir = os.path.join(current_app.static_folder, 'uploads', f"company_{comp_id}", 'logos')
                    os.makedirs(save_dir, exist_ok=True)
                    
                    filename = secure_filename(f"logo_{int(datetime.now().timestamp())}.png")
                    full_path = os.path.join(save_dir, filename)
                    f.save(full_path)
                    
                    web_path = f"/uploads/company_{comp_id}/logos/{filename}"
                    cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'logo', %s) ON CONFLICT (company_id, key) DO UPDATE SET value=EXCLUDED.value", (comp_id, web_path))
                    session['logo'] = web_path

            conn.commit()
            flash("✅ Settings Saved & Sidebar Updated")
            
        except Exception as e:
            conn.rollback()
            flash(f"Error saving settings: {e}")

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    raw_settings = cur.fetchall()
    
    # Decrypt sensitive settings before displaying
    settings = {}
    for key, value in raw_settings:
        if encryptor.is_encrypted_key(key) and value:
            settings[key] = encryptor.decrypt(value) or ''
        else:
            settings[key] = value
            
    cur.execute("SELECT sub_domain FROM companies WHERE id = %s", (comp_id,))
    comp_row = cur.fetchone()
    sub_domain = comp_row[0] if comp_row else ''
    
    config = get_site_config(comp_id)
    pass

    return render_template('finance/settings_general.html', settings=settings, active_tab='general', sub_domain=sub_domain, brand_color=config['color'], logo_url=config['logo'])

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
    pass
    
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
    pass
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
        pass

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
        pass; flash("❌ Invoice not found.", "error")
        return redirect(url_for('finance.finance_invoices'))

    client_email = inv[6]
    invoice_ref = inv[1]

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    # Decrypt sensitive fields for email sending
    from utils.encryption import get_encryptor
    encryptor = get_encryptor()
    raw_pass = settings.get('smtp_password')
    settings['smtp_password'] = encryptor.decrypt(raw_pass) if raw_pass else None

    if 'smtp_host' not in settings:
        pass; flash("⚠️ SMTP Settings missing.", "warning")
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
    
    payment_link = None
    if settings.get('stripe_secret_key'):
        payment_link = f"{request.host_url.rstrip('/')}/pay/invoice/{invoice_id}"

    context = {
        'invoice': {
            'ref': inv[1], 'date': inv[2], 'due': inv[2],
            'client_name': inv[5], 'client_address': inv[7], 'client_email': inv[6],
            'total': total_val, 'subtotal': total_val, 'tax': 0.0,
            'currency_symbol': settings.get('currency_symbol', '£')
        },
        'payment_link': payment_link,
        'company': {'name': session.get('company_name')},
        'items': items, 
        'settings': settings, 
        'config': config 
    }

    filename = f"Invoice_{invoice_ref}.pdf"
    
    try:
        pdf_path = generate_pdf('finance/pdf_invoice_template.html', context, filename)

        import base64
        attachment_b64 = None
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as pdf_file:
                attachment_b64 = base64.b64encode(pdf_file.read()).decode('utf-8')

        # 6. Send Email (via Celery)
        from tasks import send_tenant_email_task

        subject = f"Invoice {invoice_ref} from {session.get('company_name')}"
        body_html = f"Dear {inv[5]},<br><br>Please find attached invoice {invoice_ref}.<br><br>Total Due: {settings.get('currency_symbol','£')}{total_val:.2f}<br><br>"
        
        # Add Stripe Payment Link if configured
        if payment_link:
            body_html += f"<a href='{payment_link}' style='background-color: {settings.get('brand_color', '#0d6efd')}; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block; margin-bottom: 20px;'>Pay Securely via Stripe</a><br><br>"
            
        body_html += f"Kind regards,<br>{session.get('company_name')}"

        send_tenant_email_task.delay(
            company_id=company_id,
            recipient_email=client_email,
            subject=subject,
            body_html=body_html,
            attachment_path=pdf_path,
            attachment_b64=attachment_b64,
            attachment_name=filename
        )
        
        cur.execute("UPDATE invoices SET status = 'Sent' WHERE id = %s", (invoice_id,))
        conn.commit()
        flash(f"✅ Invoice is being emailed to {client_email} in the background!", "success")

    except Exception as e:
        flash(f"❌ Email task failed: {e}", "error")
    
    pass
    return redirect(url_for('finance.finance_invoices'))

@finance_bp.route('/finance/invoice/<int:invoice_id>/mark-sent')
def mark_invoice_sent(invoice_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE invoices SET status = 'Sent' WHERE id = %s", (invoice_id,))
    conn.commit(); pass
    
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
        pass
        
    return redirect(url_for('finance.finance_invoices'))
    
@finance_bp.route('/finance-dashboard')
def finance_dashboard():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    
    from services.dashboard_service import get_finance_dashboard_data
    data = get_finance_dashboard_data(comp_id)

    return render_template('finance/finance_dashboard.html',
                           currency_symbol=data.get('currency_symbol', '£'),
                           total_income=data.get('total_income', 0),
                           total_expense=data.get('total_expense', 0),
                           total_balance=data.get('total_balance', 0),
                           break_even=data.get('break_even', 0),
                           transactions=data.get('transactions', []),
                           logs=data.get('logs', []),
                           chart_labels=data.get('chart_labels', []),
                           chart_income=data.get('chart_income', []),
                           chart_expense=data.get('chart_expense', []),
                           brand_color=config['color'],
                           logo_url=config['logo'])
                           
@finance_bp.route('/finance/settings/integrations', methods=['GET', 'POST'])
def settings_integrations():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    encryptor = get_encryptor()

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'request_partner':
            partner_code = request.form.get('partner_code', '').strip().upper()
            if partner_code:
                # Find partner company
                cur.execute("SELECT id FROM companies WHERE partner_code = %s", (partner_code,))
                row = cur.fetchone()
                if row:
                    partner_id = row[0]
                    if partner_id == comp_id:
                        flash("❌ You cannot partner with yourself.", "error")
                    else:
                        try:
                            # Insert pending request (we are the company_id, they are the partner_id)
                            # The receiving company will see it and accept.
                            cur.execute("""
                                INSERT INTO company_partners (company_id, partner_id, status)
                                VALUES (%s, %s, 'Pending')
                                ON CONFLICT (company_id, partner_id) DO NOTHING
                            """, (comp_id, partner_id))
                            conn.commit()
                            flash("✅ Partner request sent!", "success")
                        except Exception as e:
                            conn.rollback()
                            flash(f"Error sending request: {e}", "error")
                else:
                    flash("❌ Invalid Partner Code.", "error")
                    
        elif action == 'accept_partner':
            request_id = request.form.get('request_id')
            cur.execute("UPDATE company_partners SET status = 'Active' WHERE id = %s AND partner_id = %s", (request_id, comp_id))
            conn.commit()
            flash("✅ Partner request accepted!", "success")
            
        elif action == 'remove_partner':
            request_id = request.form.get('request_id')
            # Either we initiated it or they did
            cur.execute("DELETE FROM company_partners WHERE id = %s AND (company_id = %s OR partner_id = %s)", (request_id, comp_id, comp_id))
            conn.commit()
            flash("❌ Partner connection removed.", "info")
            
        elif action == 'save_keys':
            plaintext_keys = [
                'geotab_database', 'smtp_host', 'smtp_port', 'smtp_email', 
                'imap_server', 'imap_port', 'imap_user'
            ]
            
            encrypted_keys = [
                'samsara_api_key', 'geotab_user', 'geotab_password',
                'verizon_connect_api_key', 'tomtom_api_key',
                'stripe_secret_key',
                'google_ai_key', 'openai_api_key', 'anthropic_api_key',
                'smtp_password', 'imap_password'
            ]
            
            # 1. Update standard text fields
            for k in plaintext_keys:
                val = request.form.get(k)
                if val is not None:
                    cur.execute("""
                        INSERT INTO settings (company_id, key, value) VALUES (%s, %s, %s)
                        ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value
                    """, (comp_id, k, val))

            # 2. Handle Encrypted Keys SEPARATELY (Only if they are not empty or masked)
            for k in encrypted_keys:
                raw_val = request.form.get(k)
                if raw_val and raw_val.strip() != "" and raw_val != "********":
                    encrypted_val = encryptor.encrypt(raw_val)
                    cur.execute("""
                        INSERT INTO settings (company_id, key, value) VALUES (%s, %s, %s)
                        ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value
                    """, (comp_id, k, encrypted_val))

            conn.commit()
            flash("✅ Keys saved!", "success")
    # --- PARTNER NETWORK DATA FETCH ---
    # 1. Ensure this company has a partner code
    cur.execute("SELECT partner_code FROM companies WHERE id = %s", (comp_id,))
    row = cur.fetchone()
    my_code = row[0] if row else None
    
    if not my_code:
        import secrets
        import string
        my_code = 'BB-' + ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        cur.execute("UPDATE companies SET partner_code = %s WHERE id = %s", (my_code, comp_id))
        conn.commit()

    # 2. Fetch Active Partners
    # They could be the initiator (company_id) or the receiver (partner_id)
    cur.execute("""
        SELECT cp.id, c.name, cp.created_at
        FROM company_partners cp
        JOIN companies c ON c.id = cp.partner_id
        WHERE cp.company_id = %s AND cp.status = 'Active'
        UNION
        SELECT cp.id, c.name, cp.created_at
        FROM company_partners cp
        JOIN companies c ON c.id = cp.company_id
        WHERE cp.partner_id = %s AND cp.status = 'Active'
    """, (comp_id, comp_id))
    active_partners = [{'id': r[0], 'name': r[1], 'date': r[2]} for r in cur.fetchall()]

    # 3. Fetch Incoming Requests (I am the partner_id, waiting for my approval)
    cur.execute("""
        SELECT cp.id, c.name, cp.created_at
        FROM company_partners cp
        JOIN companies c ON c.id = cp.company_id
        WHERE cp.partner_id = %s AND cp.status = 'Pending'
    """, (comp_id,))
    incoming_requests = [{'id': r[0], 'name': r[1], 'date': r[2]} for r in cur.fetchall()]

    # Load Settings with decryption
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    raw_settings = cur.fetchall()

    settings = {}
    for key, value in raw_settings:
        if encryptor.is_encrypted_key(key) and value:
            settings[key] = '********'  # Mask the password to prevent HTML leak
        else:
            settings[key] = value

    pass

    return render_template('finance/settings_integrations.html',
                           settings=settings, 
                           my_code=my_code,
                           active_partners=active_partners,
                           incoming_requests=incoming_requests,
                           active_tab='integrations')
    
# --- IN routes/finance_routes.py ---

@finance_bp.route('/finance/payroll')
def finance_payroll():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    
    # 1. Fetch Config
    conn = get_db(); cur = conn.cursor()
    
    # SMART MIGRATION: Ensure HR columns exist if they jumped straight to Payroll
    try:
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS tax_limit NUMERIC DEFAULT 0;")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS ni_limit NUMERIC DEFAULT 0;")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS holiday_entitled BOOLEAN DEFAULT TRUE;")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS bank_name VARCHAR(100);")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS account_number VARCHAR(20);")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS sort_code VARCHAR(20);")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS tax_code VARCHAR(20) DEFAULT '1257L';")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS utr_number VARCHAR(20);")
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS cis_rate NUMERIC DEFAULT 20.0;")
        conn.commit()
    except:
        conn.rollback()
        
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    country = settings.get('country_code', 'UK') 
    currency = settings.get('currency_symbol', '£')
    brand_color = settings.get('brand_color', '#333')
    logo = settings.get('logo')

    # 2. Date Range
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    if start_date_str and end_date_str:
        start_of_week = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_of_week = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        # Default to Current Week: Mon - Sun
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday()) 
        end_of_week = start_of_week + timedelta(days=6)         
    
    # 3. FETCH DATA (FIXED: NOW READING FROM staff_attendance)
    from services.tax_engine import TaxEngine
    cur.execute("""
        SELECT 
            s.id, s.name, s.position, s.employment_type, s.pay_rate, s.pay_model,
            COALESCE(SUM(a.total_hours), 0) as total_hours,
            COUNT(DISTINCT a.date) as days_worked,
            s.tax_limit, s.ni_limit, s.holiday_entitled,
            s.tax_code, s.utr_number, s.cis_rate
        FROM staff s
        LEFT JOIN staff_attendance a ON s.id = a.staff_id 
            AND a.date >= %s AND a.date <= %s
        WHERE s.company_id = %s
        GROUP BY s.id
        ORDER BY s.name ASC
    """, (start_of_week, end_of_week, comp_id))
    
    payroll = []
    totals = {'gross': 0, 'tax': 0, 'holiday': 0, 'net': 0}
    
    for r in cur.fetchall():
        hours = float(r[6])
        days = int(r[7])
        rate = float(r[4] or 0)
        model = r[5]
        role_type = r[3]
        tax_limit = float(r[8] or 0)
        ni_limit = float(r[9] or 0)
        holiday_entitled = r[10]
        tax_code = r[11]
        utr_number = r[12]
        cis_rate = float(r[13] or 20.0)
        
        # A. Gross Pay Calculation
        gross = 0
        if model == 'Hour': 
            gross = hours * rate
        elif model == 'Day': 
            gross = days * rate
        elif model == 'Year': 
            gross = (rate / 52)
        
        # B. Tax Calculation using TaxEngine
        tax = 0.0
        social = 0.0
        holiday_accrued = 0.0
        
        if role_type == 'Sub-Contractor':
            # Sub-contractor logic: flat CIS deduction
            tax = gross * (cis_rate / 100.0)
        else:
            # PAYE logic
            est_tax, est_social = TaxEngine.calculate(gross, country)
            tax = est_tax if tax_limit == 0 else min(est_tax, tax_limit)
            social = est_social if ni_limit == 0 else min(est_social, ni_limit)
            
            # Holiday Accrual Calculation
            if holiday_entitled:
                holiday_accrued = round(gross * 0.1207, 2)
                
        deductions = tax + social
        net = gross - deductions
        
        payroll.append({
            'id': r[0], 'name': r[1], 'role': r[2], 'type': role_type,
            'hours': hours, 'days': days, 'rate': rate, 'model': model,
            'gross': gross, 'tax': tax, 'social': social, 'holiday': holiday_accrued, 'net': net
        })
        
        totals['gross'] += gross
        totals['tax'] += deductions
        totals['holiday'] += holiday_accrued
        totals['net'] += net

    pass
    
    return render_template('finance/finance_payroll.html', 
                           payroll=payroll,
                           totals=totals,
                           week_start=start_of_week,
                           week_end=end_of_week,
                           settings=settings,
                           currency=currency,
                           brand_color=brand_color,
                           logo_url=logo)

@finance_bp.route('/finance/payroll/export', methods=['POST'])
def export_payroll():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    # Decrypt sensitive fields for email sending
    from utils.encryption import get_encryptor
    encryptor = get_encryptor()
    raw_pass = settings.get('smtp_password')
    settings['smtp_password'] = encryptor.decrypt(raw_pass) if raw_pass else None

    country = settings.get('country_code', 'UK') 

    today = date.today()
    start_of_week = today - timedelta(days=today.weekday()) 
    end_of_week = start_of_week + timedelta(days=6)         
    
    from services.tax_engine import TaxEngine
    import io
    import csv
    
    cur.execute("""
        SELECT 
            s.id, s.name, s.position, s.employment_type, s.pay_rate, s.pay_model,
            COALESCE(SUM(a.total_hours), 0) as total_hours,
            COUNT(DISTINCT a.date) as days_worked,
            s.tax_limit, s.ni_limit, s.holiday_entitled,
            s.account_number, s.sort_code, s.bank_name,
            s.tax_code, s.utr_number, s.cis_rate, s.email
        FROM staff s
        LEFT JOIN staff_attendance a ON s.id = a.staff_id 
            AND a.date >= %s AND a.date <= %s
            AND a.status = 'Approved'
        WHERE s.company_id = %s
        GROUP BY s.id
        ORDER BY s.name ASC
    """, (start_of_week, end_of_week, comp_id))
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Standard Bank CSV Format
    writer.writerow(['Account Name', 'Account Number', 'Sort Code', 'Bank Name', 'Amount', 'Reference'])
    
    for r in cur.fetchall():
        name = r[1]
        role_type = r[3]
        rate = float(r[4] or 0)
        model = r[5]
        hours = float(r[6])
        days = int(r[7])
        tax_limit = float(r[8] or 0)
        ni_limit = float(r[9] or 0)
        holiday_entitled = r[10]
        acc_num = r[11] or ''
        sort_code = r[12] or ''
        bank = r[13] or ''
        tax_code = r[14]
        utr_number = r[15]
        cis_rate = float(r[16] or 20.0)
        staff_email = r[17]
        
        gross = 0
        if model == 'Hour': gross = hours * rate
        elif model == 'Day': gross = days * rate
        elif model == 'Year': gross = (rate / 52)
            
        tax = 0.0
        social = 0.0
        holiday_accrued = 0.0
        
        if role_type == 'Sub-Contractor':
            tax = gross * (cis_rate / 100.0)
        else:
            est_tax, est_social = TaxEngine.calculate(gross, country)
            tax = est_tax if tax_limit == 0 else min(est_tax, tax_limit)
            social = est_social if ni_limit == 0 else min(est_social, ni_limit)
            if holiday_entitled:
                holiday_accrued = round(gross * 0.1207, 2)
                
        deductions = tax + social
        net = round(gross - deductions, 2)
        
        if net > 0:
            writer.writerow([name, acc_num, sort_code, bank, f"{net:.2f}", f"Wages W/C {start_of_week.strftime('%d%b')}"])
            
            # --- PAYSLIP GENERATION & EMAIL ---
            if staff_email and settings.get('smtp_host'):
                try:
                    staff_data = {
                        'name': name, 'role': r[2], 'type': role_type,
                        'utr_number': utr_number, 'cis_rate': cis_rate,
                        'tax_code': tax_code, 'account_number': acc_num, 'sort_code': sort_code,
                        'model': model, 'hours': hours, 'days': days, 'rate': rate,
                        'gross': gross, 'holiday': holiday_accrued,
                        'tax': tax, 'social': social, 'net': net
                    }
                    config = get_site_config(comp_id)
                    context = {
                        'config': config,
                        'date': date.today().strftime('%d/%m/%Y'),
                        'period': f"W/C {start_of_week.strftime('%d/%m/%Y')}",
                        'staff': staff_data,
                        'currency': settings.get('currency_symbol', '£')
                    }
                    filename = f"Payslip_{name.replace(' ', '_')}_{today.strftime('%Y%m%d')}.pdf"
                    pdf_path = generate_pdf('finance/pdf_payslip.html', context, filename)

                    import base64
                    attachment_b64 = None
                    if os.path.exists(pdf_path):
                        with open(pdf_path, "rb") as pdf_file:
                            attachment_b64 = base64.b64encode(pdf_file.read()).decode('utf-8')

                    # Send Email (via Celery)
                    from tasks import send_tenant_email_task

                    subject = f"Payslip: W/C {start_of_week.strftime('%d/%m/%Y')}"
                    body_html = f"Hi {name},<br><br>Please find attached your payslip for the week commencing {start_of_week.strftime('%d/%m/%Y')}.<br><br>Your net pay of {settings.get('currency_symbol', '£')}{net:.2f} will be transferred shortly.<br><br>Best regards,<br>{session.get('company_name')}"

                    send_tenant_email_task.delay(
                        company_id=comp_id,
                        recipient_email=staff_email,
                        subject=subject,
                        body_html=body_html,
                        attachment_path=pdf_path,
                        attachment_b64=attachment_b64,
                        attachment_name=filename
                    )
                except Exception as e:
                    print(f"Failed to queue payslip email for {staff_email}: {e}")
            
    pass
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=Payroll_Export_WC_{start_of_week.strftime('%Y-%m-%d')}.csv"}
    )
                          
# --- SETTINGS: IMPORT CENTER ---
@finance_bp.route('/finance/settings/import', methods=['GET', 'POST'])
def settings_import():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    
    if request.method == 'POST':
        import_type = request.form.get('type')
        file = request.files.get('file')
        
        if file and file.filename.endswith('.csv'):
            try:
                stream = TextIOWrapper(file.stream, encoding='utf-8')
                csv_reader = csv.reader(stream)
                header = next(csv_reader) # Skip Header
                
                conn = get_db(); cur = conn.cursor()
                count = 0
                
                for row in csv_reader:
                    if not row: continue
                    
                    if import_type == 'clients':
                        # Expects: Name, Email, Phone, Address
                        if len(row) >= 4:
                            cur.execute("""
                                INSERT INTO clients (company_id, name, email, phone, site_address, billing_address, status)
                                VALUES (%s, %s, %s, %s, %s, %s, 'Active')
                            """, (comp_id, row[0], row[1], row[2], row[3], row[3]))
                            count += 1

                    elif import_type == 'staff':
                        # Expects: Name, Email, Position, Rate
                        if len(row) >= 4:
                            rate = float(row[3]) if row[3] else 0.0
                            cur.execute("""
                                INSERT INTO staff (company_id, name, email, position, pay_rate, pay_model)
                                VALUES (%s, %s, %s, %s, %s, 'Hour')
                            """, (comp_id, row[0], row[1], row[2], rate))
                            count += 1

                    elif import_type == 'vehicles':
                        # Expects: Reg, Model, Daily Cost
                        if len(row) >= 3:
                            cost = float(row[2]) if row[2] else 0.0
                            cur.execute("""
                                INSERT INTO vehicles (company_id, reg_plate, make_model, daily_cost, status)
                                VALUES (%s, %s, %s, %s, 'Active')
                            """, (comp_id, row[0], row[1], cost))
                            count += 1
                
                conn.commit()
                pass
                flash(f"✅ Successfully imported {count} records.", "success")
                
            except Exception as e:
                flash(f"❌ Import Error: {e}", "error")
        else:
            flash("❌ Invalid file. Please upload a CSV.", "error")

    # Load Settings Context (for Layout)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    pass

    return render_template('finance/settings_import.html', settings=settings, active_tab='import')
    
@finance_bp.route('/finance/bookkeeping', methods=['GET', 'POST'])
def finance_bookkeeping():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']:
        return redirect(url_for('auth.login'))

    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    # 1. DEFINE INBOX PATH (Server-side disk path)
    inbox_path = os.path.join(current_app.static_folder, 'uploads', f"company_{comp_id}", 'inbox')
    os.makedirs(inbox_path, exist_ok=True)

    # 2. HANDLE ACTIONS
    if request.method == 'POST':
        action = request.form.get('action')
        raw_filename = request.form.get('file_id')
        
        if not raw_filename:
            flash("❌ No file selected.", "error")
            return redirect(url_for('finance.finance_bookkeeping'))
            
        filename = secure_filename(raw_filename) 
        cost = request.form.get('cost') or 0
        desc = request.form.get('description') or "Unsorted Receipt"
        src_file = os.path.join(inbox_path, filename)
        
        try:
            if not os.path.exists(src_file):
                flash("❌ File not found or invalid filename.", "error")
            
            elif action == 'delete':
                os.remove(src_file)
                flash("🗑️ Document discarded.")

            elif action == 'assign_job':
                job_id = request.form.get('job_id')
                dest_dir = os.path.join(current_app.static_folder, 'uploads', f"company_{comp_id}", 'expenses')
                os.makedirs(dest_dir, exist_ok=True)
                dest_path = os.path.join(dest_dir, filename)
                shutil.move(src_file, dest_path)
                
                # FIXED DB PATH: Must match Bouncer prefix and correct subfolder
                db_path = f"/uploads/company_{comp_id}/expenses/{filename}"
                
                cur.execute("""
                    INSERT INTO job_expenses (company_id, job_id, description, cost, date, receipt_path)
                    VALUES (%s, %s, %s, %s, CURRENT_DATE, %s)
                """, (comp_id, job_id, desc, cost, db_path))
                flash("✅ Assigned to Job Expense.")

            elif action == 'scan_materials':
                from utils.encryption import get_encryptor
                from services.ai_assistant import extract_receipt_materials
                
                # Fetch API key
                cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'google_ai_key'", (comp_id,))
                row = cur.fetchone()
                if not row or not row[0]:
                    flash("❌ You do not have an API set up, please process via the sorting office manually.", "error")
                    pass
                    return redirect(url_for('finance.finance_bookkeeping'))
                
                api_key = get_encryptor().decrypt(row[0])
                
                # Fetch context
                cur.execute("SELECT name FROM suppliers WHERE company_id = %s", (comp_id,))
                suppliers_list = [r[0] for r in cur.fetchall()]
                cur.execute("SELECT name FROM materials WHERE company_id = %s", (comp_id,))
                materials_list = [r[0] for r in cur.fetchall()]
                
                res = extract_receipt_materials(src_file, api_key, materials_list, suppliers_list)
                if not res.get('success'):
                    flash(f"❌ AI Extraction failed: {res.get('error')}", "error")
                else:
                    data = res['data']
                    vendor = data.get('vendor')
                    supplier_id = None
                    if vendor:
                        cur.execute("SELECT id FROM suppliers WHERE company_id = %s AND LOWER(name) = LOWER(%s)", (comp_id, vendor.strip()))
                        s_row = cur.fetchone()
                        if s_row:
                            supplier_id = s_row[0]
                        else:
                            cur.execute("INSERT INTO suppliers (company_id, name) VALUES (%s, %s) RETURNING id", (comp_id, vendor.strip()))
                            supplier_id = cur.fetchone()[0]
                    
                    line_items = data.get('line_items', [])
                    items_added = 0
                    for item in line_items:
                        desc = item.get('description')
                        price = item.get('unit_price')
                        if desc and price is not None:
                            clean_desc = desc.strip()
                            cur.execute("SELECT id FROM materials WHERE company_id = %s AND LOWER(name) = LOWER(%s)", (comp_id, clean_desc))
                            mat_row = cur.fetchone()
                            if mat_row:
                                cur.execute("UPDATE materials SET cost_price = %s, supplier_id = %s WHERE id = %s", (price, supplier_id, mat_row[0]))
                            else:
                                sku = f"MAT-{int(datetime.now().timestamp())}-{items_added}"
                                cur.execute("""
                                    INSERT INTO materials (company_id, sku, name, category, unit, cost_price, supplier_id)
                                    VALUES (%s, %s, %s, 'General', 'Each', %s, %s)
                                """, (comp_id, sku, clean_desc, price, supplier_id))
                            items_added += 1
                    
                    # File the receipt to Overheads (or generic expenses)
                    dest_dir = os.path.join(current_app.static_folder, 'uploads', f"company_{comp_id}", 'overheads')
                    os.makedirs(dest_dir, exist_ok=True)
                    dest_path = os.path.join(dest_dir, filename)
                    shutil.move(src_file, dest_path)
                    
                    db_path = f"/uploads/company_{comp_id}/overheads/{filename}"
                    
                    # Try to get a default category, or insert one
                    cur.execute("SELECT id FROM overhead_categories WHERE company_id = %s LIMIT 1", (comp_id,))
                    cat_row = cur.fetchone()
                    if cat_row:
                        cat_id = cat_row[0]
                    else:
                        cur.execute("INSERT INTO overhead_categories (company_id, name) VALUES (%s, 'General Supplies') RETURNING id", (comp_id,))
                        cat_id = cur.fetchone()[0]
                        
                    total_cost = data.get('total_cost') or cost
                    desc_text = f"Supplies from {vendor}" if vendor else "General Supplies"
                    
                    cur.execute("""
                        INSERT INTO overhead_items (category_id, name, amount, date_incurred, receipt_path)
                        VALUES (%s, %s, %s, CURRENT_DATE, %s)
                    """, (cat_id, desc_text, total_cost, db_path))
                    
                    flash(f"✅ AI Extracted {items_added} materials from {vendor or 'receipt'}.", "success")

            elif action == 'assign_overhead':
                cat_id = request.form.get('category_id')
                dest_dir = os.path.join(current_app.static_folder, 'uploads', f"company_{comp_id}", 'overheads')
                os.makedirs(dest_dir, exist_ok=True)
                dest_path = os.path.join(dest_dir, filename)
                shutil.move(src_file, dest_path)
                
                # FIXED DB PATH: Added leading slash and company_ prefix
                db_path = f"/uploads/company_{comp_id}/overheads/{filename}"
                
                cur.execute("""
                    INSERT INTO overhead_items (category_id, name, amount, date_incurred, receipt_path)
                    VALUES (%s, %s, %s, CURRENT_DATE, %s)
                """, (cat_id, desc, cost, db_path))
                flash("✅ Assigned to Overheads.")

            conn.commit()
        except Exception as e:
            conn.rollback()
            flash(f"Error: {e}", "error")

    # 3. FETCH UNSORTED FILES (For Web Display)
    unsorted_files = []
    if os.path.exists(inbox_path):
        for f in os.listdir(inbox_path):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf')):
                # FIXED WEB PATH: Leading slash and /uploads/ prefix for bouncer
                full_web_path = f"/uploads/company_{comp_id}/inbox/{f}"
                unsorted_files.append((f, "Scanned Receipt", 0.00, f, full_web_path))

    # 4. FETCH DROPDOWNS
    cur.execute("SELECT id, ref, description FROM jobs WHERE company_id=%s AND status!='Completed'", (comp_id,))
    jobs = cur.fetchall()
    cur.execute("SELECT id, name FROM overhead_categories WHERE company_id=%s", (comp_id,))
    categories = cur.fetchall()
    pass

    return render_template('finance/bookkeeping_inbox.html', unsorted=unsorted_files, jobs=jobs, categories=categories)