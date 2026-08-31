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
from services.pricing_engine import calculate_vehicle_daily_cost
from utils.db_utils import db_transaction
from utils.encryption import get_encryptor
import base64
from services.dashboard_service import get_finance_dashboard_data
import secrets
import string
from services.tax_engine import TaxEngine
import io
import csv
from services.ai_assistant import extract_receipt_materials

@finance_bp.route('/finance/invoices')
def finance_invoices():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: 
        return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    config = get_site_config(company_id)
    conn = get_db()
    cur = conn.cursor()
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
        
    
    return render_template('finance/finance_invoices.html', 
                           invoices=invoices, 
                           brand_color=config['color'], 
                           logo_url=config['logo'],
                           currency=currency)

@finance_bp.route('/finance/invoice/create', methods=['GET', 'POST'])
def create_invoice():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        client_id = request.form.get('client_id')
        job_id = request.form.get('job_id') or None
        
        new_client_name = request.form.get('new_client_name')
        
        if not client_id and not new_client_name:
            flash("Error: Client is required.", "error")
            return redirect(request.url)
        
        # 1. Fetch Settings & Tax Engine
        cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
        settings = {r[0]: r[1] for r in cur.fetchall()}
        
        # 2. Get line items
        descriptions = request.form.getlist('desc[]')
        quantities = request.form.getlist('qty[]')
        prices = request.form.getlist('price[]')
        
        subtotal = 0.0
        items_to_insert = []
        for d, q, p in zip(descriptions, quantities, prices):
            if d.strip():
                qty = float(q or 0)
                price = float(p or 0)
                line_total = qty * price
                subtotal += line_total
                items_to_insert.append((d.strip(), qty, price, line_total))
                
        # Handle Resources
        est_days = float(request.form.get('estimated_days') or 1)
        pref_van = request.form.get('preferred_vehicle_id') or None
        
        if pref_van:
            cur.execute("SELECT daily_cost, assigned_driver_id, reg_plate FROM vehicles WHERE id = %s", (pref_van,))
            van = cur.fetchone()
            
            if van:
                base_cost = float(van[0]) if van[0] else 0.0
                driver_id = van[1]
                reg_plate = van[2]

                daily_total = calculate_vehicle_daily_cost(cur, pref_van, base_cost, driver_id)

                # Fetch labour markup
                labour_markup_percent = float(settings.get('labour_markup_percent', 0) or 0)
                labour_multiplier = 1 + (labour_markup_percent / 100.0)
                
                daily_charge = daily_total * labour_multiplier

                res_total = daily_charge * est_days
                if res_total > 0:
                    subtotal += res_total
                    items_to_insert.append((f"Resources: {reg_plate} (Driver + Crew)", est_days, daily_charge, res_total))

        # 3. Calculate Tax
        tax_rate, tax_amt, final_total = TaxEngine.calculate_invoice_totals(settings, subtotal)
        
        # 4. Generate Reference
        today_str = datetime.now().strftime('%y%m')
        cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id = %s AND date_trunc('month', date) = date_trunc('month', CURRENT_DATE)", (comp_id,))
        count = cur.fetchone()[0] + 1
        ref = f"INV-{today_str}-{count:03d}"
        
        # 5. Insert Invoice (and New Client if applicable)
        with db_transaction() as t_cur:
            # Handle New Client logic inside the transaction
            if not client_id and new_client_name:
                new_addr = request.form.get('new_property_address') or ''
                new_post = request.form.get('new_property_postcode') or ''
                full_billing = f"{new_addr}, {new_post}".strip(', ')
                
                t_cur.execute("""
                    INSERT INTO clients (company_id, name, email, phone, status, billing_address)
                    VALUES (%s, %s, %s, %s, 'Lead', %s) RETURNING id
                """, (comp_id, new_client_name, request.form.get('new_client_email'), 
                      request.form.get('new_client_phone'), full_billing))
                client_id = t_cur.fetchone()[0]
                
                if new_addr or new_post:
                    t_cur.execute("""
                        INSERT INTO properties (company_id, client_id, address_line1, postcode, status)
                        VALUES (%s, %s, %s, %s, 'Active') RETURNING id
                    """, (comp_id, client_id, new_addr, new_post))
                    # no prop_id mapping in invoice unless needed
            
            payment_days = int(settings.get('payment_days', 14))
            due_date = date.today() + timedelta(days=payment_days)
            
            t_cur.execute("""
                INSERT INTO invoices (company_id, client_id, job_id, reference, date, due_date, status, subtotal, tax, total)
                VALUES (%s, %s, %s, %s, CURRENT_DATE, %s, 'Unpaid', %s, %s, %s)
                RETURNING id
            """, (comp_id, client_id, job_id, ref, due_date, subtotal, tax_amt, final_total))
            
            invoice_id = t_cur.fetchone()[0]
            
            # 6. Insert Line Items
            for item in items_to_insert:
                t_cur.execute("""
                    INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
                    VALUES (%s, %s, %s, %s, %s)
                """, (invoice_id, item[0], item[1], item[2], item[3]))
            
        flash(f"✅ Invoice {ref} Created Successfully!", "success")
        return redirect(url_for('finance.finance_invoices'))

    # GET Request: Fetch options
    cur.execute("SELECT id, name FROM clients WHERE company_id = %s ORDER BY name", (comp_id,))
    clients = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]
    
    # We don't fetch jobs here anymore; JS will fetch them dynamically based on client_id.
    
    cur.execute("SELECT id, name, pay_rate FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    staff_list = [{'id': r[0], 'name': r[1], 'pay_rate': r[2]} for r in cur.fetchall()]
    
    cur.execute("SELECT id, name, cost_price, supplier FROM materials WHERE company_id = %s ORDER BY name", (comp_id,))
    materials = [{'id': r[0], 'name': r[1], 'cost': r[2], 'supplier': r[3]} for r in cur.fetchall()]
    
    cur.execute("SELECT id, reg_plate, make_model, daily_cost, assigned_driver_id FROM vehicles WHERE company_id = %s", (comp_id,))
    vehicles_data = cur.fetchall()
    vehicles = []
    for r in vehicles_data:
        v_id, reg, make, cost, drv_id = r
        full_cost = calculate_vehicle_daily_cost(cur, v_id, cost, drv_id)
        vehicles.append({'id': v_id, 'reg': reg, 'make': make, 'cost': full_cost})
    
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {r[0]: r[1] for r in cur.fetchall()}
    tax_rate = TaxEngine.get_tax_rate(settings)

    return render_template('finance/create_invoice.html', 
                           brand_color=config['color'], 
                           logo_url=config['logo'],
                           clients=clients,
                           staff_list=staff_list,
                           materials=materials,
                           vehicles=vehicles,
                           settings=settings,
                           tax_rate=tax_rate)

@finance_bp.route('/api/client/<int:client_id>/jobs')
def api_client_jobs_for_finance(client_id):
    if 'user_id' not in session: return jsonify([])
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, ref, description FROM jobs WHERE client_id = %s AND company_id = %s ORDER BY created_at DESC", (client_id, session.get('company_id')))
    jobs = [{'id': r[0], 'ref': r[1], 'title': r[2]} for r in cur.fetchall()]
    return jsonify(jobs)

# --- 2. HR & STAFF ---
@finance_bp.route('/finance/hr')
def finance_hr():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, position, dept, pay_rate, pay_model, access_level, email, phone, employment_type, address, tax_id FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    cols = [desc[0] for desc in cur.description]; staff = [dict(zip(cols, row)) for row in cur.fetchall()]
    return render_template('finance/finance_hr.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])
    
@finance_bp.route('/finance/hr/delete/<int:id>')
def delete_staff(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM staff WHERE id = %s AND company_id = %s", (id, session.get('company_id')))
    conn.commit(); pass
    return redirect(url_for('finance.finance_hr'))

@finance_bp.route('/finance/fleet', methods=['GET', 'POST'])
def finance_fleet():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        
        with db_transaction() as t_cur:
            if action == 'add_vehicle':
                allowed, msg = check_limit(comp_id, 'max_vehicles')
                if not allowed:
                    flash(msg, "error")
                    return redirect(url_for('finance.finance_fleet'))
                    
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
        
    return redirect(url_for('finance.finance_fleet'))

# =========================================================
# 4. MATERIALS & SUPPLIERS (UPGRADED)
# =========================================================

@finance_bp.route('/finance/materials')
def finance_materials():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()

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

    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'material_markup_percent'", (comp_id,))
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
    with db_transaction() as cur:
        cur.execute("INSERT INTO suppliers (company_id, name) VALUES (%s, %s)", (session.get('company_id'), request.form.get('name')))
        flash("✅ Supplier Added")
    return redirect(url_for('finance.finance_materials'))
    
@finance_bp.route('/finance/suppliers/delete/<int:id>')
def delete_supplier(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"
    
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
            conn = get_db()
            cur = conn.cursor()
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
    return redirect(url_for('finance.finance_materials'))

@finance_bp.route('/finance/materials/delete/<int:id>', methods=['GET', 'POST'])
def delete_material(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"
    comp_id = session.get('company_id')
    with db_transaction() as cur:
        cur.execute("DELETE FROM materials WHERE id=%s AND company_id=%s", (id, comp_id))
        flash("✅ Material deleted.")
    return redirect(url_for('finance.finance_materials'))

@finance_bp.route('/finance/materials/bulk-delete', methods=['POST'])
def bulk_delete_materials():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"
    comp_id = session.get('company_id')
    scope = request.form.get('scope', 'selected')
    
    with db_transaction() as cur:
        if scope == 'all':
            cur.execute("DELETE FROM materials WHERE company_id = %s", (comp_id,))
            flash("✅ All materials cleared from library.")
        elif scope == 'general':
            cur.execute("DELETE FROM materials WHERE company_id = %s AND (supplier_id IS NULL OR supplier_id = 0)", (comp_id,))
            flash("✅ All General (unassigned) materials deleted.")
        elif scope == 'by_supplier':
            supp_id = request.form.get('supplier_id')
            if supp_id:
                cur.execute("DELETE FROM materials WHERE company_id = %s AND supplier_id = %s", (comp_id, supp_id))
                flash("✅ Supplier materials deleted.")
        else: # 'selected'
            selected_ids = request.form.getlist('material_ids')
            clean_ids = [int(i) for i in selected_ids if i.isdigit()]
            if clean_ids:
                cur.execute("DELETE FROM materials WHERE company_id = %s AND id = ANY(%s)", (comp_id, clean_ids))
                flash(f"✅ Deleted {len(clean_ids)} selected materials.")
            else:
                flash("⚠️ No materials were selected for deletion.")
                
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
        conn.close()
@finance_bp.route('/finance/analysis')
def finance_analysis():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()

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
                    WHEN COALESCE(t.pay_model, s.pay_model) = 'Day' THEN (COALESCE(t.pay_rate, s.pay_rate, 0) / 8.0)
                    WHEN COALESCE(t.pay_model, s.pay_model) = 'Year' THEN (COALESCE(t.pay_rate, s.pay_rate, 0) / (260.0 * 8.0))
                    ELSE COALESCE(t.pay_rate, s.pay_rate, 0)
                END
            ), 0)
            FROM staff_timesheets t JOIN staff s ON t.staff_id=s.id WHERE t.job_id=%s
        """, (job_id,))
        labor = float(cur.fetchone()[0]) if cur.rowcount > 0 else 0.0

        actual_cost = expenses + labor; profit = revenue - actual_cost
        margin = (profit / revenue * 100) if revenue > 0 else 0.0
        total_rev += revenue; total_cost += actual_cost
        analyzed.append({"ref": ref, "client": client, "status": status, "rev": revenue, "cost": actual_cost, "profit": profit, "margin": margin})
    
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
    
    return render_template('finance/finance_audit_logs.html', logs=audit_logs, brand_color=config['color'], logo_url=config['logo'])

@finance_bp.route('/finance/settings')
def settings_redirect(): return redirect(url_for('finance.settings_general'))

# --- SETTINGS: GENERAL TAB ---
@finance_bp.route('/finance/settings/general', methods=['GET', 'POST'])
def settings_general():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db()
    cur = conn.cursor()
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
            'material_markup_percent', 'labour_markup_percent', 'default_profit_margin'
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
    
    return render_template('finance/settings_banking.html', settings=settings, active_tab='banking', brand_color=config['color'], logo_url=config['logo'])

@finance_bp.route('/finance/settings/overheads', methods=['GET', 'POST'])
def settings_overheads():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    # Ensure tables exist
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS overhead_categories (id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL, name VARCHAR(100) NOT NULL);")
        cur.execute("CREATE TABLE IF NOT EXISTS overhead_items (id SERIAL PRIMARY KEY, category_id INTEGER NOT NULL, name VARCHAR(100) NOT NULL, amount DECIMAL(10,2) DEFAULT 0.00, frequency VARCHAR(20) DEFAULT 'Monthly', date_incurred DATE, receipt_path TEXT, FOREIGN KEY (category_id) REFERENCES overhead_categories(id) ON DELETE CASCADE);")
        conn.commit()
    except Exception:
        conn.rollback()

    if request.method == 'POST':
        act = request.form.get('action')
        if act == 'add_category':
            cat_name = request.form.get('category_name')
            if cat_name:
                cur.execute("INSERT INTO overhead_categories (company_id, name) VALUES (%s, %s)", (comp_id, cat_name.strip()))
                flash("Category added.", "success")
        elif act == 'add_item':
            cat_id = request.form.get('category_id')
            item_name = request.form.get('item_name')
            item_cost = request.form.get('item_cost') or 0.00
            freq = request.form.get('frequency', 'Monthly')
            if cat_id and item_name:
                cur.execute("INSERT INTO overhead_items (category_id, name, amount, frequency, date_incurred) VALUES (%s, %s, %s, %s, CURRENT_DATE)", (cat_id, item_name.strip(), item_cost, freq))
                flash("Overhead item added.", "success")
        elif act == 'delete_item':
            item_id = request.form.get('item_id')
            if item_id:
                cur.execute("DELETE FROM overhead_items WHERE id = %s AND category_id IN (SELECT id FROM overhead_categories WHERE company_id = %s)", (item_id, comp_id))
                flash("Overhead item removed.", "info")
        elif act == 'delete_category':
            cat_id = request.form.get('category_id')
            if cat_id:
                cur.execute("DELETE FROM overhead_categories WHERE id = %s AND company_id = %s", (cat_id, comp_id))
                flash("Category removed.", "info")
        conn.commit()

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    currency_symbol = settings.get('currency_symbol', '£')
    
    cur.execute("SELECT id, name FROM overhead_categories WHERE company_id = %s ORDER BY id ASC", (comp_id,))
    cats = cur.fetchall()
    
    class CO:
        def __init__(self, i, n, it, t):
            self.id = i
            self.name = n
            self.items = it
            self.total = t
            
    overheads = []
    tot = 0.0
    for c in cats:
        cur.execute("SELECT id, name, amount, frequency FROM overhead_items WHERE category_id = %s ORDER BY id ASC", (c[0],))
        items = cur.fetchall()
        ct = sum([float(i[2] or 0) for i in items])
        tot += ct
        overheads.append(CO(c[0], c[1], items, ct))
        
    return render_template('finance/settings_overheads.html', 
                           settings=settings, 
                           overheads=overheads, 
                           total_overhead=tot, 
                           currency_symbol=currency_symbol,
                           active_tab='overheads', 
                           brand_color=config['color'], 
                           logo_url=config['logo'])
    
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

@finance_bp.route('/finance/invoice/<int:invoice_id>/email')
def email_invoice(invoice_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']:
        return redirect(url_for('auth.login'))
        
    conn = get_db()
    cur = conn.cursor()
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
        flash("❌ Invoice not found.", "error")
        return redirect(url_for('finance.finance_invoices'))

    client_email = inv[6]
    invoice_ref = inv[1]

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    # Decrypt sensitive fields for email sending
    encryptor = get_encryptor()
    raw_pass = settings.get('smtp_password')
    settings['smtp_password'] = encryptor.decrypt(raw_pass) if raw_pass else None

    if 'smtp_host' not in settings:
        flash("⚠️ SMTP Settings missing.", "warning")
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
    
    return redirect(url_for('finance.finance_invoices'))

@finance_bp.route('/finance/invoice/<int:invoice_id>/mark-sent')
def mark_invoice_sent(invoice_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE invoices SET status = 'Sent' WHERE id = %s AND company_id = %s", (invoice_id, session.get('company_id')))
    conn.commit()
    
    flash("✅ Invoice manually marked as Sent.", "success")
    return redirect(request.referrer or url_for('finance.finance_invoices'))

@finance_bp.route('/finance/invoice/<int:invoice_id>/mark-paid', methods=['GET', 'POST'])
def mark_invoice_paid(invoice_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    user_name = session.get('user_name', session.get('username', 'Admin'))
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT reference, total FROM invoices WHERE id = %s AND company_id = %s", (invoice_id, comp_id))
    inv = cur.fetchone()
    if not inv:
        flash("Invoice not found.", "error")
        return redirect(url_for('finance.finance_invoices'))
        
    ref, total = inv[0], inv[1]
    payment_method = request.form.get('payment_method', 'Bank Transfer') if request.method == 'POST' else 'Manual Payment'
    notes = request.form.get('payment_notes', '').strip() if request.method == 'POST' else ''
    
    try:
        cur.execute("UPDATE invoices SET status = 'Paid' WHERE id = %s AND company_id = %s", (invoice_id, comp_id))
        
        detail_msg = f"Marked as Paid ({payment_method})"
        if notes:
            detail_msg += f" - Note: {notes}"
            
        cur.execute("""
            INSERT INTO audit_logs (company_id, admin_email, action, target, details, ip_address, created_at)
            VALUES (%s, %s, 'INVOICE_PAID', %s, %s, %s, CURRENT_TIMESTAMP)
        """, (comp_id, user_name, f"Invoice #{ref}", detail_msg, request.remote_addr))
        
        conn.commit()
        flash(f"✅ Invoice #{ref} marked as Paid ({payment_method}) and added to Finance Dashboard.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error updating invoice: {e}", "error")
        
    return redirect(request.referrer or url_for('finance.finance_invoices'))

@finance_bp.route('/finance/invoice/<int:invoice_id>/status/<new_status>')
def set_invoice_status_finance(invoice_id, new_status):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']:
        return redirect(url_for('auth.login'))
    
    valid = ['Draft', 'Sent', 'Paid', 'Unpaid', 'Overdue']
    if new_status not in valid:
        flash("❌ Invalid Status", "error")
        return redirect(url_for('finance.finance_invoices'))

    comp_id = session.get('company_id')
    user_name = session.get('user_name', session.get('username', 'Admin'))
    conn = get_db()
    cur = conn.cursor()
    
    try:
        cur.execute("UPDATE invoices SET status = %s WHERE id = %s AND company_id = %s", 
                   (new_status, invoice_id, comp_id))
        
        cur.execute("""
            INSERT INTO audit_logs (company_id, admin_email, action, target, details, ip_address, created_at)
            VALUES (%s, %s, 'INVOICE_UPDATE', %s, %s, %s, CURRENT_TIMESTAMP)
        """, (
            comp_id, 
            user_name, 
            f"Invoice #{invoice_id}", 
            f"Status changed to {new_status} by {user_name}",
            request.remote_addr
        ))

        conn.commit()
        flash(f"✅ Invoice marked as {new_status}")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
        
    return redirect(request.referrer or url_for('finance.finance_invoices'))
    
@finance_bp.route('/finance/invoice/<int:invoice_id>/delete')
def delete_invoice(invoice_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']:
        return redirect(url_for('auth.login'))
        
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM invoice_items WHERE invoice_id = %s", (invoice_id,))
        cur.execute("DELETE FROM invoices WHERE id = %s", (invoice_id,))
        conn.commit()
        flash("✅ Invoice deleted successfully.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error deleting invoice: {e}", "error")
        
    return redirect(url_for('finance.finance_invoices'))
    
@finance_bp.route('/finance/invoice/<int:invoice_id>/view')
def view_invoice_dashboard(invoice_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']:
        return redirect(url_for('auth.login'))
        
    company_id = session.get('company_id')
    config = get_site_config(company_id)
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT key, value FROM settings WHERE company_id=%s", (company_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    currency = settings.get('currency_symbol', '£')
    
    cur.execute("""
        SELECT i.id, i.reference, c.name, i.date, i.total, i.status,
               i.due_date, c.id, c.email, c.phone,
               COALESCE(p.address_line1, ''), COALESCE(p.postcode, ''),
               i.subtotal, i.tax,
               COALESCE(q.job_title, j.description, 'Invoice Services'),
               COALESCE(q.job_description, j.description, ''),
               i.job_id, j.ref as job_ref, j.status as job_status,
               i.quote_id, q.reference as quote_ref, q.status as quote_status
        FROM invoices i 
        JOIN clients c ON i.client_id = c.id 
        LEFT JOIN jobs j ON i.job_id = j.id
        LEFT JOIN quotes q ON i.quote_id = q.id
        LEFT JOIN properties p ON (j.property_id = p.id OR q.property_id = p.id)
        WHERE i.id = %s AND i.company_id = %s
    """, (invoice_id, company_id))
    inv = cur.fetchone()
    
    if not inv:
        flash("Invoice not found.", "error")
        return redirect(url_for('finance.finance_invoices'))
        
    invoice = {
        'id': inv[0],
        'reference': inv[1],
        'client_name': inv[2] or 'Client',
        'date': inv[3].strftime('%d/%m/%Y') if hasattr(inv[3], 'strftime') else str(inv[3] or ''),
        'total': float(inv[4] or 0),
        'status': inv[5],
        'due_date': inv[6].strftime('%d/%m/%Y') if hasattr(inv[6], 'strftime') else str(inv[6] or ''),
        'client_id': inv[7],
        'client_email': inv[8] or '',
        'client_phone': inv[9] or '',
        'property_address': inv[10] or '',
        'property_postcode': inv[11] or '',
        'title': inv[14] or 'Invoice',
        'desc': inv[15] or ''
    }

    # Line Items
    cur.execute("""
        SELECT description, quantity, unit_price, total
        FROM invoice_items
        WHERE invoice_id = %s ORDER BY id ASC
    """, (invoice_id,))
    items_raw = cur.fetchall()
    items = []
    items_total_sum = 0.0
    for r in items_raw:
        line_tot = float(r[3] or 0)
        items_total_sum += line_tot
        items.append({
            'desc': r[0],
            'qty': r[1],
            'price': float(r[2] or 0),
            'total': line_tot
        })

    # Tax & Subtotal
    from services.tax_engine import TaxEngine
    comp_tax_rate = TaxEngine.get_tax_rate(settings)
    stored_subtotal = float(inv[12]) if inv[12] is not None else None
    stored_tax = float(inv[13]) if inv[13] is not None else None
    grand_total = float(inv[4] or 0.0)

    if stored_subtotal is not None and stored_tax is not None:
        subtotal = stored_subtotal
        tax_amount = stored_tax
    elif comp_tax_rate > 0:
        divisor = 1 + comp_tax_rate
        subtotal = grand_total / divisor
        tax_amount = grand_total - subtotal
    else:
        subtotal = grand_total if grand_total > 0 else items_total_sum
        tax_amount = 0.0

    if not items:
        items.append({
            'desc': invoice['title'] or 'General Contract Works',
            'qty': 1,
            'price': subtotal,
            'total': subtotal
        })

    connected_job = None
    if inv[16]:
        connected_job = {
            'id': inv[16],
            'ref': inv[17] or f"JOB-{inv[16]}",
            'status': inv[18] or 'Active'
        }

    connected_quote = None
    if inv[19]:
        connected_quote = {
            'id': inv[19],
            'ref': inv[20] or f"Q-{inv[19]}",
            'status': inv[21] or 'Accepted'
        }
    
    return render_template('finance/view_invoice_dashboard.html', 
                           invoice=invoice, 
                           items=items,
                           subtotal=subtotal,
                           tax_amount=tax_amount,
                           tax_rate_percent=int(comp_tax_rate * 100),
                           grand_total=grand_total,
                           connected_job=connected_job,
                           connected_quote=connected_quote,
                           currency=currency,
                           brand_color=config.get('color', '#0f172a'),
                           logo_url=config.get('logo'),
                           config=config,
                           settings=settings)

@finance_bp.route('/finance-dashboard')
def finance_dashboard():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    
    data = get_finance_dashboard_data(comp_id)

    return render_template('finance/finance_dashboard.html',
                           currency_symbol=data.get('currency_symbol', '£'),
                           total_income=data.get('total_income', 0),
                           total_invoiced=data.get('total_invoiced', 0),
                           pending_income=data.get('pending_income', 0),
                           total_wages=data.get('total_wages', 0),
                           ytd_wages=data.get('ytd_wages', 0),
                           fleet_cost=data.get('fleet_cost', 0),
                           overhead_costs=data.get('overhead_costs', 0),
                           job_expenses_cost=data.get('job_expenses_cost', 0),
                           total_expense=data.get('total_expense', 0),
                           total_balance=data.get('total_balance', 0),
                           profit_margin=data.get('profit_margin', 0),
                           break_even=data.get('break_even', 0),
                           yearly_summary=data.get('yearly_summary', []),
                           transactions=data.get('transactions', []),
                           logs=data.get('logs', []),
                           chart_labels=data.get('chart_labels', []),
                           chart_income=data.get('chart_income', []),
                           chart_expense=data.get('chart_expense', []),
                           brand_color=config['color'],
                           logo_url=config['logo'])
                           
@finance_bp.route('/finance/settings/billing')
def settings_billing():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Current Subscription
    cur.execute("""
        SELECT s.id, s.plan_id, s.status, s.start_date, s.renewal_date, s.stripe_customer_id,
               COALESCE(p.name, s.plan_tier, 'Basic'), COALESCE(p.price, 0),
               COALESCE(p.max_users, s.max_users, 9999),
               COALESCE(p.max_vehicles, s.max_vehicles, 9999),
               COALESCE(p.max_properties, s.max_properties, 9999),
               COALESCE(p.max_clients, s.max_clients, 9999),
               COALESCE(p.sector, 'Trade')
        FROM subscriptions s
        LEFT JOIN plans p ON s.plan_id = p.id
        WHERE s.company_id = %s
    """, (comp_id,))
    sub_row = cur.fetchone()
    
    current_sub = None
    if sub_row:
        current_sub = {
            'id': sub_row[0],
            'plan_id': sub_row[1],
            'status': sub_row[2],
            'start_date': sub_row[3].strftime('%d %b %Y') if sub_row[3] else '',
            'renewal_date': sub_row[4].strftime('%d %b %Y') if sub_row[4] else '',
            'stripe_customer_id': sub_row[5],
            'plan_name': sub_row[6],
            'price': float(sub_row[7] or 0),
            'max_users': sub_row[8],
            'max_vehicles': sub_row[9],
            'max_properties': sub_row[10],
            'max_clients': sub_row[11],
            'sector': sub_row[12]
        }

    # 2. Compute Live Usage
    cur.execute("SELECT COUNT(*) FROM staff WHERE company_id = %s AND status = 'Active'", (comp_id,))
    staff_count = cur.fetchone()[0] or 0

    cur.execute("SELECT COUNT(*) FROM vehicles WHERE company_id = %s", (comp_id,))
    vehicles_count = cur.fetchone()[0] or 0

    cur.execute("SELECT COUNT(*) FROM properties WHERE company_id = %s", (comp_id,))
    properties_count = cur.fetchone()[0] or 0

    cur.execute("SELECT COUNT(*) FROM clients WHERE company_id = %s", (comp_id,))
    clients_count = cur.fetchone()[0] or 0

    usage = {
        'staff_count': staff_count,
        'vehicles_count': vehicles_count,
        'properties_count': properties_count,
        'clients_count': clients_count
    }

    # 3. Fetch All Available Upgrade Plans
    cur.execute("""
        SELECT id, name, price, max_users, max_vehicles, max_clients, max_properties, max_storage, sector
        FROM plans
        WHERE price > 0
        ORDER BY price ASC
    """)
    available_plans = []
    for r in cur.fetchall():
        available_plans.append({
            'id': r[0],
            'name': r[1],
            'price': float(r[2]),
            'max_users': r[3],
            'max_vehicles': r[4],
            'max_clients': r[5],
            'max_properties': r[6],
            'max_storage': r[7],
            'sector': r[8] or 'Trade'
        })

    return render_template('finance/settings_billing.html',
                           current_sub=current_sub,
                           usage=usage,
                           available_plans=available_plans,
                           active_tab='billing',
                           brand_color=config['color'],
                           logo_url=config['logo'])

@finance_bp.route('/finance/settings/switch-plan', methods=['POST'])
def switch_plan():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']:
        return redirect(url_for('auth.login'))
        
    comp_id = session.get('company_id')
    target_plan_id = request.form.get('plan_id', type=int)
    
    if not target_plan_id:
        flash("❌ Invalid plan selected.", "error")
        return redirect(url_for('finance.settings_billing'))
        
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Target Plan
    cur.execute("""
        SELECT id, name, price, max_users, max_vehicles, max_clients, max_properties, max_storage
        FROM plans WHERE id = %s
    """, (target_plan_id,))
    plan_row = cur.fetchone()
    
    if not plan_row:
        flash("❌ Target plan not found.", "error")
        return redirect(url_for('finance.settings_billing'))
        
    p_id, p_name, p_price, p_users, p_veh, p_clients, p_props, p_storage = plan_row
    
    # 2. Check Resource Usage vs New Limits
    cur.execute("SELECT COUNT(*) FROM staff WHERE company_id = %s AND status = 'Active'", (comp_id,))
    staff_count = cur.fetchone()[0] or 0
    if p_users and p_users < 9999 and staff_count > p_users:
        flash(f"⚠️ Cannot switch to {p_name}: You currently have {staff_count} active staff members, but this plan allows up to {p_users}. Please archive inactive staff before downgrading.", "error")
        return redirect(url_for('finance.settings_billing'))

    cur.execute("SELECT COUNT(*) FROM vehicles WHERE company_id = %s", (comp_id,))
    veh_count = cur.fetchone()[0] or 0
    if p_veh and p_veh < 9999 and veh_count > p_veh:
        flash(f"⚠️ Cannot switch to {p_name}: You currently have {veh_count} fleet vehicles, but this plan allows up to {p_veh}. Please remove unused vehicles before downgrading.", "error")
        return redirect(url_for('finance.settings_billing'))

    cur.execute("SELECT COUNT(*) FROM properties WHERE company_id = %s", (comp_id,))
    prop_count = cur.fetchone()[0] or 0
    if p_props and p_props < 9999 and prop_count > p_props:
        flash(f"⚠️ Cannot switch to {p_name}: You currently have {prop_count} managed properties, but this plan allows up to {p_props}.", "error")
        return redirect(url_for('finance.settings_billing'))
        
    # 3. Apply Plan Update
    cur.execute("""
        UPDATE subscriptions 
        SET plan_id = %s, plan_tier = %s, max_users = %s, max_vehicles = %s, 
            max_properties = %s, max_clients = %s, max_storage = %s, status = 'Active'
        WHERE company_id = %s
    """, (p_id, p_name, p_users, p_veh, p_props, p_clients, p_storage, comp_id))
    conn.commit()
    
    from routes.admin_routes import log_audit
    log_audit("SWITCH PLAN TIER", "subscriptions", f"Company switched plan to {p_name} (£{p_price:.0f}/mo)")
    
    flash(f"🎉 Subscription successfully updated to {p_name} (£{p_price:.0f}/mo)!", "success")
    return redirect(url_for('finance.settings_billing'))

@finance_bp.route('/finance/settings/integrations', methods=['GET', 'POST'])
def settings_integrations():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db()
    cur = conn.cursor()
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
    conn = get_db()
    cur = conn.cursor()
    
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
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    # Decrypt sensitive fields for email sending
    encryptor = get_encryptor()
    raw_pass = settings.get('smtp_password')
    settings['smtp_password'] = encryptor.decrypt(raw_pass) if raw_pass else None

    country = settings.get('country_code', 'UK') 

    today = date.today()
    start_of_week = today - timedelta(days=today.weekday()) 
    end_of_week = start_of_week + timedelta(days=6)         
    
    
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
                
                conn = get_db()
                cur = conn.cursor()
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
                flash(f"✅ Successfully imported {count} records.", "success")
                
            except Exception as e:
                flash(f"❌ Import Error: {e}", "error")
        else:
            flash("❌ Invalid file. Please upload a CSV.", "error")

    # Load Settings Context (for Layout)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}

    return render_template('finance/settings_import.html', settings=settings, active_tab='import')
    
@finance_bp.route('/finance/bookkeeping', methods=['GET', 'POST'])
def finance_bookkeeping():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']:
        return redirect(url_for('auth.login'))

    comp_id = session.get('company_id')
    conn = get_db()
    cur = conn.cursor()
    
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
                
                # Fetch API key
                cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'google_ai_key'", (comp_id,))
                row = cur.fetchone()
                if not row or not row[0]:
                    flash("❌ You do not have an API set up, please process via the sorting office manually.", "error")
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

    return render_template('finance/bookkeeping_inbox.html', unsorted=unsorted_files, jobs=jobs, categories=categories)


