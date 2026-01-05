from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify, send_file
from db import get_db, get_site_config
from datetime import datetime, date, timedelta
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
import os
import secrets
import string
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Custom Services
from services.pdf_generator import generate_pdf
# Import the AI Brain (Safe Import)
try:
    from services.ai_assistant import scan_receipt, verify_license, universal_sort_document
except ImportError:
    scan_receipt = None
    verify_license = None
    universal_sort_document = None

office_bp = Blueprint('office', __name__)
ALLOWED_OFFICE_ROLES = ['Admin', 'SuperAdmin', 'Office']
UPLOAD_FOLDER = 'static/uploads/receipts'

# --- HELPER FUNCTIONS ---
def check_office_access():
    if 'user_id' not in session: return False
    if session.get('role') not in ALLOWED_OFFICE_ROLES: return False
    return True

def format_date(d, fmt_str='%d/%m/%Y'):
    if not d: return ""
    try:
        if isinstance(d, str): d = datetime.strptime(d, '%Y-%m-%d')
        return d.strftime(fmt_str)
    except: return str(d)

def parse_date(d):
    if isinstance(d, str):
        try: return datetime.strptime(d, '%Y-%m-%d').date()
        except: return None
    return d

def generate_secure_password(length=10):
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return ''.join(secrets.choice(alphabet) for i in range(length))

# =========================================================
# 1. DASHBOARD & ANALYTICS
# =========================================================

@office_bp.route('/office-hub')
@office_bp.route('/office-hub.html')
def office_dashboard():
    if not check_office_access(): return redirect(url_for('auth.login'))
    company_id = session.get('company_id'); config = get_site_config(company_id)
    conn = get_db(); cur = conn.cursor()
    
    # Stats
    cur.execute("SELECT COUNT(*) FROM service_requests WHERE company_id = %s AND status != 'Completed'", (company_id,))
    pending = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id = %s AND status != 'Completed'", (company_id,))
    active = cur.fetchone()[0]
    
    # Recent Quotes
    cur.execute("SELECT q.id, c.name, q.reference, q.date, q.total, q.status FROM quotes q LEFT JOIN clients c ON q.client_id = c.id WHERE q.company_id = %s AND q.status = 'Draft' ORDER BY q.id DESC LIMIT 5", (company_id,))
    quotes = [(r[0], r[1], r[2], format_date(r[3]), r[4], r[5]) for r in cur.fetchall()]

    # --- THE FIX IS HERE ---
    # We added: AND NOT EXISTS (SELECT 1 FROM invoices i WHERE i.job_id = j.id)
    cur.execute("""
        SELECT j.id, j.ref, j.site_address, c.name, j.description, j.start_date 
        FROM jobs j 
        LEFT JOIN clients c ON j.client_id = c.id 
        WHERE j.company_id = %s 
        AND j.status = 'Completed' 
        AND NOT EXISTS (SELECT 1 FROM invoices i WHERE i.job_id = j.id)
        ORDER BY j.start_date DESC
    """, (company_id,))
    
    completed = [{'id': r[0], 'ref': r[1], 'address': r[2], 'client': r[3], 'desc': r[4], 'date': format_date(r[5])} for r in cur.fetchall()]

    # Live Ops
    cur.execute("SELECT j.id, j.ref, j.site_address, s.name, j.start_date FROM jobs j LEFT JOIN staff s ON j.staff_id = s.id WHERE j.company_id = %s AND j.status = 'In Progress'", (company_id,))
    live = []
    for r in cur.fetchall():
        live.append({'id': r[0], 'ref': r[1], 'address': r[2], 'staff': r[3], 'duration': 'Active'})

    conn.close()
    return render_template('office/office_dashboard.html', pending_requests_count=pending, active_jobs_count=active, quotes=quotes, completed_jobs=completed, live_ops=live, brand_color=config['color'], logo_url=config['logo'])

@office_bp.route('/office/calendar')
def office_calendar():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id)
    return render_template('office/calendar.html', brand_color=config['color'], logo_url=config['logo'])

@office_bp.route('/office/calendar/data')
def get_calendar_data():
    if not check_office_access(): return jsonify([])
    comp_id = session.get('company_id'); conn = get_db(); cur = conn.cursor(); events = []
    try:
        cur.execute("SELECT j.id, j.ref, j.start_date, c.name, j.status FROM jobs j LEFT JOIN clients c ON j.client_id = c.id WHERE j.company_id = %s AND j.start_date IS NOT NULL", (comp_id,))
        for j in cur.fetchall(): events.append({'title': f"{j[1]} - {j[3]}", 'start': str(j[2]), 'color': '#28a745' if j[4] == 'Completed' else '#0d6efd', 'url': f"/site/job/{j[0]}", 'allDay': True})
    except: pass
    conn.close(); return jsonify(events)

# =========================================================
# 2. STAFF & FLEET
# =========================================================

@office_bp.route('/office/staff', methods=['GET', 'POST'])
def staff_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    
    try: cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS license_path TEXT"); conn.commit()
    except: conn.rollback()

    if request.method == 'POST':
        action = request.form.get('action')
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        role = request.form.get('role')
        
        file_path = None
        if 'license_file' in request.files:
            f = request.files['license_file']
            if f and f.filename != '':
                os.makedirs('static/uploads/licenses', exist_ok=True)
                filename = secure_filename(f"license_{comp_id}_{int(datetime.now().timestamp())}_{f.filename}")
                full_sys_path = os.path.join('static/uploads/licenses', filename)
                f.save(full_sys_path)
                file_path = f"uploads/licenses/{filename}"
                
                # AI Verification
                if verify_license:
                    ai_check = verify_license(full_sys_path, name)
                    if ai_check['success'] and not ai_check['verified']:
                        flash(f"⚠️ AI Warning: The name on this license does not match '{name}'.", "warning")
                    elif ai_check['success']:
                        flash("✅ AI Verified: License name matches staff member.")

        try:
            if action == 'add_staff':
                cur.execute("INSERT INTO staff (company_id, name, email, phone, position, status, license_path) VALUES (%s, %s, %s, %s, %s, 'Active', %s) RETURNING id", 
                            (comp_id, name, email, phone, role, file_path))
                staff_id = cur.fetchone()[0]

                raw_password = generate_secure_password()
                hashed_pw = generate_password_hash(raw_password)
                
                login_email = email if email else f"staff{staff_id}_{comp_id}@tradecore.com"
                
                cur.execute("INSERT INTO users (company_id, name, email, password_hash, role) VALUES (%s, %s, %s, %s, %s)", (comp_id, name, login_email, hashed_pw, 'Staff'))
                conn.commit()
                flash(f"✅ Staff Added & Login Created! Password: {raw_password}")
            
            elif action == 'edit_staff':
                sid = request.form.get('staff_id')
                if file_path:
                    cur.execute("UPDATE staff SET name=%s, email=%s, phone=%s, position=%s, status=%s, license_path=%s WHERE id=%s AND company_id=%s", (name, email, phone, role, request.form.get('status'), file_path, sid, comp_id))
                else:
                    cur.execute("UPDATE staff SET name=%s, email=%s, phone=%s, position=%s, status=%s WHERE id=%s AND company_id=%s", (name, email, phone, role, request.form.get('status'), sid, comp_id))
                
                cur.execute("UPDATE users SET name=%s WHERE email=%s AND company_id=%s", (name, email, comp_id))
                conn.commit(); flash("✅ Staff Updated")

        except Exception as e: conn.rollback(); flash(f"Error: {e}")

    cur.execute("SELECT id, name, email, phone, position AS role, status, license_path FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    cols = [desc[0] for desc in cur.description]
    staff = [dict(zip(cols, row)) for row in cur.fetchall()]
    
    conn.close()
    return render_template('office/staff_management.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

@office_bp.route('/office/fleet', methods=['GET', 'POST'])
def fleet_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    
    cur.execute("CREATE TABLE IF NOT EXISTS vehicle_crew (vehicle_id INTEGER, staff_id INTEGER, PRIMARY KEY(vehicle_id, staff_id))")
    
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'assign_crew':
                v_id = request.form.get('vehicle_id'); driver_id = request.form.get('driver_id'); crew_ids = request.form.getlist('crew_ids')
                driver_val = driver_id if driver_id and driver_id != 'None' else None
                cur.execute("UPDATE vehicles SET assigned_driver_id = %s WHERE id = %s AND company_id = %s", (driver_val, v_id, comp_id))
                cur.execute("DELETE FROM vehicle_crew WHERE vehicle_id = %s", (v_id,))
                for staff_id in crew_ids:
                    if str(staff_id) != str(driver_val): cur.execute("INSERT INTO vehicle_crew (vehicle_id, staff_id) VALUES (%s, %s)", (v_id, staff_id))
                flash("✅ Crew Updated")
                
            elif action == 'add_log':
                file_url = None; cost = request.form.get('cost'); desc = request.form.get('description'); date_val = request.form.get('date')
                
                if 'receipt_file' in request.files:
                    f = request.files['receipt_file']
                    if f and f.filename != '':
                        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                        filename = secure_filename(f"receipt_{comp_id}_{int(datetime.now().timestamp())}_{f.filename}")
                        full_sys_path = os.path.join(UPLOAD_FOLDER, filename)
                        f.save(full_sys_path)
                        file_url = f"uploads/receipts/{filename}"
                        
                        if (not cost or cost == '0') and scan_receipt:
                            scan = scan_receipt(full_sys_path)
                            if scan['success']:
                                data = scan['data']
                                if data.get('total_cost'): cost = data['total_cost']
                                if data.get('date') and not date_val: date_val = data['date']
                                if data.get('vendor') and not desc: desc = f"Fuel: {data['vendor']}"
                                flash("✨ AI Auto-filled receipt details!")

                cur.execute("INSERT INTO maintenance_logs (company_id, vehicle_id, type, description, date, cost, receipt_path) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
                            (comp_id, request.form.get('vehicle_id'), request.form.get('log_type'), desc or 'Receipt', date_val or date.today(), cost or 0, file_url))
                flash("✅ Log Added")
            
            conn.commit()
        except Exception as e: conn.rollback(); flash(f"Error: {e}")

    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.status, s.name, v.assigned_driver_id, v.mot_due, v.tax_due, v.insurance_due, v.tracker_url
        FROM vehicles v LEFT JOIN staff s ON v.assigned_driver_id = s.id 
        WHERE v.company_id = %s ORDER BY v.reg_plate
    """, (comp_id,))
    
    raw = cur.fetchall(); vehicles = []; cur2 = conn.cursor()
    for row in raw:
        v_id = row[0]
        cur2.execute("SELECT s.id, s.name, s.position FROM vehicle_crew vc JOIN staff s ON vc.staff_id = s.id WHERE vc.vehicle_id = %s", (v_id,))
        crew = [{'id': c[0], 'name': c[1], 'role': c[2]} for c in cur2.fetchall()]
        cur2.execute("SELECT date, type, description, cost, receipt_path FROM maintenance_logs WHERE vehicle_id = %s ORDER BY date DESC", (v_id,))
        history = [{'date': format_date(r[0]), 'type': r[1], 'desc': r[2], 'cost': r[3], 'receipt': r[4]} for r in cur2.fetchall()]
        vehicles.append({'id': row[0], 'reg_number': row[1], 'make_model': row[2], 'status': row[3], 'driver_name': row[4], 'assigned_driver_id': row[5], 'mot_expiry': parse_date(row[6]), 'tax_expiry': parse_date(row[7]), 'ins_expiry': parse_date(row[8]), 'tracker_url': row[9], 'crew': crew, 'history': history})
        
    cur.execute("SELECT id, name, position as role FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    staff = [dict(zip(['id', 'name', 'role'], r)) for r in cur.fetchall()]
    conn.close()
    
    return render_template('office/fleet_management.html', vehicles=vehicles, staff=staff, today=date.today(), date_fmt='%d/%m/%Y', brand_color=config['color'], logo_url=config['logo'])

# =========================================================
# 3. SERVICE DESK (With Compliance Alerts)
# =========================================================

@office_bp.route('/office/service-desk', methods=['GET', 'POST'])
def service_desk():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        req_id = request.form.get('request_id')
        action = request.form.get('action')
        
        try:
            if action == 'complete':
                cur.execute("UPDATE service_requests SET status = 'Completed' WHERE id = %s AND company_id = %s", (req_id, comp_id))
                flash("✅ Request Marked as Completed")
            elif action == 'delete':
                cur.execute("DELETE FROM service_requests WHERE id = %s AND company_id = %s", (req_id, comp_id))
                flash("🗑️ Request Deleted")
            conn.commit()
        except Exception as e:
            conn.rollback(); flash(f"Error updating request: {e}")

    # 1. Fetch Real User Tickets
    cur.execute("""
        SELECT sr.id, sr.issue_description, sr.severity, sr.status, sr.created_at, c.name, p.address_line1, p.id
        FROM service_requests sr
        LEFT JOIN clients c ON sr.client_id = c.id
        LEFT JOIN properties p ON sr.property_id = p.id
        WHERE sr.company_id = %s AND sr.status != 'Completed'
        ORDER BY sr.created_at DESC
    """, (comp_id,))
    
    rows = cur.fetchall()
    requests = []
    
    # 2. Inject "System Alerts" for Expiring Compliance
    try:
        cur.execute("""
            SELECT p.id, p.address_line1, c.name, p.gas_expiry, p.eicr_expiry
            FROM properties p
            JOIN clients c ON p.client_id = c.id
            WHERE p.company_id = %s
            AND (
                (p.gas_expiry BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days') OR 
                (p.eicr_expiry BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days')
            )
        """, (comp_id,))
        
        alerts = cur.fetchall()
        for a in alerts:
            prop_id, addr, client, gas_date, elec_date = a
            issue = []
            if gas_date: issue.append(f"Gas Safety Expiring ({gas_date})")
            if elec_date: issue.append(f"EICR Expiring ({elec_date})")
            
            requests.append({
                'id': f"SYS-{prop_id}", 
                'issue_description': " ⚠️ " + " & ".join(issue), 
                'severity': 'Urgent', 
                'status': 'System Alert', 
                'date': 'Due Soon',
                'client_name': client, 
                'property_address': addr,
                'is_alert': True,
                'prop_id': prop_id
            })
    except Exception:
        # Columns missing? Just skip alerts for now.
        pass

    for r in rows:
        requests.append({
            'id': r[0], 'issue_description': r[1], 'severity': r[2], 'status': r[3], 'date': format_date(r[4]),
            'client_name': r[5] or 'N/A', 'property_address': r[6] or 'General',
            'is_alert': False
        })

    cur.execute("SELECT id, name FROM staff WHERE company_id = %s", (comp_id,))
    staff = [{'id': s[0], 'name': s[1]} for s in cur.fetchall()]

    conn.close()
    return render_template('office/service_desk.html', requests=requests, staff=staff, brand_color=config['color'], logo_url=config['logo'])

@office_bp.route('/office/create-work-order', methods=['POST'])
def create_work_order():
    if 'user_id' not in session: return redirect('/login')

    request_id = request.form.get('request_id')
    staff_id = request.form.get('assigned_staff_id')
    schedule_date = request.form.get('schedule_date')

    conn = get_db(); cur = conn.cursor()

    try:
        cur.execute("SELECT property_id, client_id, issue_description FROM service_requests WHERE id = %s", (request_id,))
        req_data = cur.fetchone()
        
        if not req_data:
            flash("❌ Error: Service Request not found.", "error")
            return redirect('/office/service-desk')

        prop_id, client_id, description = req_data

        cur.execute("SELECT id FROM jobs WHERE property_id = %s AND status != 'Completed'", (prop_id,))
        existing_job = cur.fetchone()

        if existing_job:
            job_id = existing_job[0]
            cur.execute("UPDATE jobs SET engineer_id = %s, start_date = %s WHERE id = %s", (staff_id, schedule_date, job_id))
            cur.execute("UPDATE service_requests SET status = 'In Progress' WHERE id = %s", (request_id,))
            flash(f"✅ Job updated! Reassigned to new engineer/date.", "info")
        else:
            import random
            job_ref = f"JOB-{prop_id}-{random.randint(100,999)}"
            cur.execute("""
                INSERT INTO jobs (company_id, client_id, property_id, engineer_id, start_date, status, description, ref)
                VALUES (%s, %s, %s, %s, %s, 'Scheduled', %s, %s)
            """, (session['company_id'], client_id, prop_id, staff_id, schedule_date, description, job_ref))

            cur.execute("UPDATE service_requests SET status = 'In Progress' WHERE id = %s", (request_id,))
            flash(f"✅ Job Created & Dispatched successfully!", "success")

        conn.commit()
    except Exception as e: conn.rollback(); flash(f"Error dispatching job: {e}", "error")
    finally: conn.close()

    return redirect('/office/service-desk')

# =========================================================
# 4. COMPLIANCE & CERTIFICATES (NEW SECTIONS)
# =========================================================

@office_bp.route('/office/cert/gas/create')
def create_gas_cert():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    prop_id = request.args.get('prop_id')
    comp_id = session.get('company_id')
    
    conn = get_db(); cur = conn.cursor()
    
    # Get Country
    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'country_code'", (comp_id,))
    row = cur.fetchone()
    country = row[0] if row else 'UK'
    
    # Get Property Data (Including new columns)
    cur.execute("""
        SELECT p.address_line1, p.address_line2, p.city, p.postcode, c.name, c.email
        FROM properties p 
        JOIN clients c ON p.client_id = c.id 
        WHERE p.id = %s AND p.company_id = %s
    """, (prop_id, comp_id))
    data = cur.fetchone()
    conn.close()
    
    prop_data = {}
    if data:
        # Smart Address Joiner: Joins parts with commas, ignores empty ones
        addr_parts = [data[0], data[1], data[2], data[3]] 
        full_addr = ", ".join([part for part in addr_parts if part and part.strip() != ""])
        
        prop_data = {
            'id': prop_id,
            'address': full_addr,
            'client': data[4],
            'client_email': data[5]
        }
    
    next_year = date.today() + timedelta(days=365)
    
    if country == 'UK':
        return render_template('office/certs/uk/cp12.html', prop=prop_data, today=date.today(), next_year_date=next_year)
    elif country == 'US':
        return render_template('office/certs/us/gas_inspection.html', prop=prop_data, today=date.today(), next_year_date=next_year)
    else:
        return render_template('office/certs/generic/safety_check.html', prop=prop_data, today=date.today(), next_year_date=next_year)

@office_bp.route('/office/cert/gas/save', methods=['POST'])
def save_gas_cert():
    if not check_office_access(): return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    data = request.json
    prop_id = data.get('prop_id')
    comp_id = session.get('company_id')
    
    conn = get_db(); cur = conn.cursor()
    
    try:
        # 1. Generate Filename
        ref = f"CP12-{prop_id}-{int(datetime.now().timestamp())}"
        filename = f"{ref}.pdf"
        
        # 2. Get Property Info
        cur.execute("SELECT p.address_line1, p.postcode, c.name, c.email FROM properties p JOIN clients c ON p.client_id = c.id WHERE p.id = %s", (prop_id,))
        p_row = cur.fetchone()
        prop_info = {
            'address': f"{p_row[0]}, {p_row[1]}",
            'client': p_row[2],
            'client_email': p_row[3],
            'id': prop_id
        }
        
        # 3. Generate PDF
        pdf_context = {
            'prop': prop_info,
            'data': data,
            'signature_url': data.get('signature_img'),
            'next_year_date': data.get('next_date'),
            'today': date.today().strftime('%d/%m/%Y')
        }
        
        # NOTE: Using UK template for PDF generation for now (Make dynamic if needed)
        pdf_path = generate_pdf('office/certs/uk/cp12.html', pdf_context, filename)
        
        # 4. Save Record (Update Property Compliance)
        next_due = data.get('next_date')
        if next_due:
            cur.execute("UPDATE properties SET gas_expiry = %s WHERE id = %s", (next_due, prop_id))
            
        conn.commit()
        
        return jsonify({
            'success': True, 
            'redirect_url': url_for('office.office_dashboard')
        })
        
    except Exception as e:
        conn.rollback(); return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()
# --- SAVE EICR CERTIFICATE ---
@office_bp.route('/office/cert/eicr/save', methods=['POST'])
def save_eicr_cert():
    if not check_office_access(): return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    data = request.json
    prop_id = data.get('prop_id')
    comp_id = session.get('company_id')
    
    # Validation
    if not prop_id:
        return jsonify({'success': False, 'error': 'Property ID missing'})

    conn = get_db()
    cur = conn.cursor()
    
    try:
        # 1. Determine Status
        # If the user clicked "Save as Draft", status is Draft. Otherwise Issued.
        status = data.get('status', 'Issued') 
        
        # 2. Insert into Certificates Table (JSON Storage)
        # We store the ENTIRE form data in the 'data' column so we can reload it later.
        cur.execute("""
            INSERT INTO certificates (company_id, property_id, type, status, data, engineer_name, date_issued, expiry_date)
            VALUES (%s, %s, 'EICR', %s, %s, %s, CURRENT_DATE, %s)
            RETURNING id
        """, (
            comp_id, 
            prop_id, 
            status, 
            json.dumps(data),  # Requires: import json at top of file
            session.get('user_name', 'Engineer'),
            data.get('next_inspection_date')
        ))
        
        cert_id = cur.fetchone()[0]

        # 3. Update Property Expiry Date (Only if Issued)
        if status == 'Issued':
            next_date = data.get('next_inspection_date')
            if next_date:
                cur.execute("UPDATE properties SET eicr_expiry = %s WHERE id = %s", (next_date, prop_id))

        conn.commit()
        
        # 4. Success Response
        return jsonify({
            'success': True, 
            'message': 'EICR Saved Successfully',
            'redirect_url': url_for('office.office_dashboard')
        })

    except Exception as e:
        conn.rollback()
        print(f"EICR Save Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

# =========================================================
# 5. UPLOAD CENTER & CLIENT PORTAL
# =========================================================

@office_bp.route('/office/upload-center', methods=['POST'])
def universal_upload():
    if not check_office_access(): return jsonify({'error': 'Unauthorized'}), 403
    
    comp_id = session.get('company_id')
    file = request.files.get('file')
    if not file: return jsonify({'error': 'No file'}), 400

    save_dir = os.path.join('static', 'uploads', str(comp_id), 'inbox')
    os.makedirs(save_dir, exist_ok=True)
    
    filename = secure_filename(f"{int(datetime.now().timestamp())}_{file.filename}")
    full_path = os.path.join(save_dir, filename)
    file.save(full_path)
    db_path = f"uploads/{comp_id}/inbox/{filename}"
    
    # Use the AI Sorter if available
    if not universal_sort_document:
        return jsonify({'status': 'success', 'message': 'File uploaded (AI disabled)', 'data': {}})

    scan = universal_sort_document(full_path)
    
    if not scan['success']:
        return jsonify({'status': 'error', 'message': scan.get('error')})

    result = scan['result']
    doc_type = result.get('doc_type')
    data = result.get('data', {})
    
    conn = get_db(); cur = conn.cursor()
    msg = "File Processed"
    
    try:
        if doc_type == 'fuel_receipt':
            v_id = None
            reg = data.get('vehicle_reg')
            if reg:
                clean_reg = reg.replace(" ", "")
                cur.execute("SELECT id FROM vehicles WHERE REPLACE(reg_plate, ' ', '') ILIKE %s AND company_id=%s", (f"%{clean_reg}%", comp_id))
                row = cur.fetchone()
                if row: v_id = row[0]

            cur.execute("INSERT INTO maintenance_logs (company_id, vehicle_id, type, description, date, cost, receipt_path) VALUES (%s, %s, 'Fuel', %s, %s, %s, %s)", 
                        (comp_id, v_id, f"AI: {data.get('vendor')} ({reg or 'Unknown'})", data.get('date') or date.today(), data.get('total_cost') or 0, db_path))
            msg = f"Fuel Logged. Linked to Van: {reg if v_id else 'No Match Found'}"

        elif doc_type == 'supplier_invoice':
            cur.execute("CREATE TABLE IF NOT EXISTS job_expenses (id SERIAL PRIMARY KEY, company_id INTEGER, job_id INTEGER, description TEXT, cost REAL, date DATE, receipt_path TEXT)")
            j_id = None
            ref = data.get('job_ref')
            if ref:
                cur.execute("SELECT id FROM jobs WHERE ref ILIKE %s AND company_id=%s", (f"%{ref}%", comp_id))
                row = cur.fetchone()
                if row: j_id = row[0]
            
            cur.execute("INSERT INTO job_expenses (company_id, job_id, description, cost, date, receipt_path) VALUES (%s, %s, %s, %s, %s, %s)", 
                        (comp_id, j_id, f"Invoice: {data.get('supplier_name')}", data.get('total') or 0, data.get('date') or date.today(), db_path))
            msg = f"Invoice Filed. Linked to Job: {ref if j_id else 'Unassigned'}"

        conn.commit()
        return jsonify({'status': 'success', 'doc_type': doc_type, 'message': msg, 'data': data})
    except Exception as e: conn.rollback(); return jsonify({'status': 'error', 'message': str(e)})
    finally: conn.close()

@office_bp.route('/office/client/<int:client_id>/enable-portal', methods=['POST'])
def enable_portal(client_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); conn = get_db(); cur = conn.cursor()

    try:
        cur.execute("SELECT name, email FROM clients WHERE id = %s AND company_id = %s", (client_id, comp_id))
        client = cur.fetchone()
        
        if not client or not client[1]: 
            flash("❌ Client needs an email address first.", "error")
            return redirect(url_for('office.view_client', client_id=client_id))

        client_name, client_email = client
        raw_password = generate_secure_password()
        hashed_password = generate_password_hash(raw_password)

        cur.execute("UPDATE clients SET password_hash = %s WHERE id = %s", (hashed_password, client_id))
        
        cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
        settings = {row[0]: row[1] for row in cur.fetchall()}
        
        if 'smtp_host' in settings:
            login_url = url_for('portal.portal_login', company_id=comp_id, _external=True)
            msg = MIMEMultipart()
            msg['From'] = settings.get('smtp_email')
            msg['To'] = client_email
            msg['Subject'] = "Your Client Portal Access"
            body = f"<h3>Hello {client_name},</h3><p>An account has been created.</p>Login: {login_url}<br>User: {client_email}<br>Pass: {raw_password}"
            msg.attach(MIMEText(body, 'html'))

            server = smtplib.SMTP(settings['smtp_host'], int(settings['smtp_port']))
            server.starttls()
            server.login(settings['smtp_email'], settings['smtp_password'])
            server.send_message(msg)
            server.quit()
            flash(f"✅ Access Granted! Password sent to {client_email}")
        else:
            flash("⚠️ Password generated, but Email Failed (SMTP Settings missing).", "warning")
            
        conn.commit()
    except Exception as e: conn.rollback(); flash(f"Error: {e}", "error")
    finally: conn.close()
    
# --- EMAIL QUOTE TO CLIENT ---
@office_bp.route('/office/quote/<int:quote_id>/email')
def email_quote(quote_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Quote & Client Data
    cur.execute("""
        SELECT q.id, q.reference, q.date, q.total, q.status, c.name, c.email, c.billing_address
        FROM quotes q JOIN clients c ON q.client_id = c.id
        WHERE q.id = %s AND q.company_id = %s
    """, (quote_id, company_id))
    q = cur.fetchone()
    
    if not q:
        conn.close()
        flash("❌ Quote not found.", "error")
        return redirect(url_for('office.office_dashboard'))

    quote_data = {'id': q[0], 'ref': q[1], 'date': q[2], 'total': q[3], 'status': q[4], 'client_name': q[5], 'client_email': q[6], 'client_address': q[7]}
    client_email = q[6]

    # 2. Check SMTP Settings
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    if 'smtp_host' not in settings or 'smtp_email' not in settings:
        conn.close()
        flash("⚠️ Email Failed: SMTP settings are missing. Please configure them in Settings.", "warning")
        return redirect(url_for('office.office_dashboard'))

    # 3. Generate the PDF (Same logic as download)
    cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
    items = [{'desc': r[0], 'qty': r[1], 'price': r[2], 'total': r[3]} for r in cur.fetchall()]
    config = get_site_config(company_id)
    
    context = {'invoice': quote_data, 'items': items, 'settings': settings, 'config': config, 'is_quote': True, 'company': {'name': session.get('company_name')}}
    filename = f"Quote_{quote_data['ref']}.pdf"
    
    try:
        pdf_path = generate_pdf('finance/pdf_invoice_template.html', context, filename)
        
        # 4. Send Email
        msg = MIMEMultipart()
        msg['From'] = settings.get('smtp_email')
        msg['To'] = client_email
        msg['Subject'] = f"Quote {quote_data['ref']} from {session.get('company_name')}"
        
        body = f"Dear {quote_data['client_name']},\n\nPlease find attached the quote {quote_data['ref']} as requested.\n\nKind regards,\n{session.get('company_name')}"
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach PDF
        with open(pdf_path, "rb") as f:
            from email.mime.application import MIMEApplication
            part = MIMEApplication(f.read(), Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            msg.attach(part)

        server = smtplib.SMTP(settings['smtp_host'], int(settings.get('smtp_port', 587)))
        server.starttls()
        server.login(settings['smtp_email'], settings['smtp_password'])
        server.send_message(msg)
        server.quit()
        
        # 5. Update Status to 'Sent'
        cur.execute("UPDATE quotes SET status = 'Sent' WHERE id = %s", (quote_id,))
        conn.commit()
        flash(f"✅ Quote emailed to {client_email} and marked as Sent!", "success")

    except Exception as e:
        flash(f"❌ Error sending email: {e}", "error")
    
    conn.close()
    return redirect(url_for('office.office_dashboard'))

# --- MANUAL STATUS UPDATE (For Manual/Offline Sending) ---
@office_bp.route('/office/quote/<int:quote_id>/mark-sent')
def mark_quote_sent(quote_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    company_id = session.get('company_id')
    
    cur.execute("UPDATE quotes SET status = 'Sent' WHERE id = %s AND company_id = %s", (quote_id, company_id))
    conn.commit()
    conn.close()
    
    flash("✅ Quote manually marked as Sent.", "success")
    return redirect(url_for('office.office_dashboard'))

@office_bp.route('/office/quote/<int:quote_id>')
def view_quote(quote_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    if request.args.get('mode') == 'pdf': return download_quote_pdf(quote_id)

    company_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Quote
    cur.execute("""
        SELECT q.id, c.name, q.reference, q.date, q.total, q.status, q.expiry_date 
        FROM quotes q 
        LEFT JOIN clients c ON q.client_id = c.id 
        WHERE q.id = %s AND q.company_id = %s
    """, (quote_id, company_id))
    quote = cur.fetchone()

    # 2. Fetch Currency (The Missing Part)
    cur.execute("SELECT value FROM settings WHERE key = 'currency_symbol' AND company_id = %s", (company_id,))
    res = cur.fetchone()
    currency = res[0] if res else '£'

    conn.close()
    
    if not quote: return "Quote not found", 404
    
    # 3. Pass currency_symbol to the template
    return render_template('office/view_quote_dashboard.html', quote=quote, currency_symbol=currency)

# --- VIEW CLIENT PROFILE (Add this to fix the BuildError) ---
@office_bp.route('/client/<int:client_id>')
def view_client(client_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    # 1. Fetch Client Details
    cur.execute("SELECT id, name, email, phone, billing_address FROM clients WHERE id = %s AND company_id = %s", (client_id, comp_id))
    c = cur.fetchone()
    
    if not c:
        conn.close()
        return "Client not found", 404
        
    client = {'id': c[0], 'name': c[1], 'email': c[2], 'phone': c[3], 'addr': c[4]}

    # 2. Fetch Properties
    cur.execute("""
        SELECT id, address_line1, postcode, tenant, 
               gas_expiry, eicr_expiry, pat_expiry, fire_alarm_expiry, tenant_phone
        FROM properties 
        WHERE client_id = %s
        ORDER BY address_line1
    """, (client_id,))
    
    properties = []
    for r in cur.fetchall():
        # Helper to check compliance dates
        def check_comp(d):
            if not d: return {'status': 'Missing', 'date': None}
            if d < date.today(): return {'status': 'Expired', 'date': d.strftime('%d/%m/%y')}
            if d < (date.today() + timedelta(days=30)): return {'status': 'Due', 'date': d.strftime('%d/%m/%y')}
            return {'status': 'Valid', 'date': d.strftime('%d/%m/%y')}

        properties.append({
            'id': r[0], 'addr': r[1], 'postcode': r[2], 'tenant': r[3], 'tenant_phone': r[8],
            'compliance': {
                'Gas': check_comp(r[4]),
                'EICR': check_comp(r[5]),
                'PAT': check_comp(r[6]),
                'Fire': check_comp(r[7])
            }
        })
    
    conn.close()
    
    # This points to your existing file in templates/office/
    return render_template('office/client_details.html', client=client, properties=properties, brand_color=config['color'], logo_url=config['logo'])

@office_bp.route('/client/<int:client_id>/add_property', methods=['POST'])
def add_property(client_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    # Get form data
    addr1 = request.form.get('address_line1')
    addr2 = request.form.get('address_line2')
    city = request.form.get('city')
    postcode = request.form.get('postcode')
    
    tenant = request.form.get('tenant_name')
    t_phone = request.form.get('tenant_phone')
    comp_id = session.get('company_id')

    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO properties (company_id, client_id, address_line1, address_line2, city, postcode, tenant, tenant_phone)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, client_id, addr1, addr2, city, postcode, tenant, t_phone))
        conn.commit()
        flash("✅ Property Added Successfully")
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}")
    finally:
        conn.close()

    return redirect(url_for('office.view_client', client_id=client_id))

# --- CONVERT QUOTE TO INVOICE ---
@office_bp.route('/office/quote/<int:quote_id>/convert')
def convert_to_invoice(quote_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    comp_id = session.get('company_id')

    # 1. Fetch Quote Details
    cur.execute("SELECT client_id, total, status FROM quotes WHERE id = %s AND company_id = %s", (quote_id, comp_id))
    quote = cur.fetchone()
    
    if not quote:
        conn.close()
        flash("❌ Quote not found.", "error")
        return redirect(url_for('office.office_dashboard'))

    # Optional: Prevent double conversion
    if quote[2] == 'Converted':
        conn.close()
        flash("⚠️ This quote has already been converted.", "warning")
        return redirect(url_for('office.office_dashboard'))

    client_id = quote[0]
    total_amount = quote[1]

    # 2. Create New Invoice
    # We use the Quote ID in the reference to link them visually (e.g., INV-Q-1001)
    new_ref = f"INV-Q-{quote_id}"
    
    try:
        cur.execute("""
            INSERT INTO invoices (company_id, client_id, ref, date_created, due_date, status, total_amount)
            VALUES (%s, %s, %s, CURRENT_DATE, CURRENT_DATE + INTERVAL '14 days', 'Unpaid', %s)
            RETURNING id
        """, (comp_id, client_id, new_ref, total_amount))
        
        new_invoice_id = cur.fetchone()[0]

        # 3. Copy Items from Quote to Invoice
        cur.execute("""
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
            SELECT %s, description, quantity, unit_price, total
            FROM quote_items
            WHERE quote_id = %s
        """, (new_invoice_id, quote_id))

        # 4. Update Quote Status
        cur.execute("UPDATE quotes SET status = 'Converted' WHERE id = %s", (quote_id,))
        
        conn.commit()
        flash(f"✅ Quote Converted! Created Invoice {new_ref}", "success")
        
        # Redirect to the Finance list so you can see the new invoice
        return redirect(url_for('finance.finance_invoices'))

    except Exception as e:
        conn.rollback()
        flash(f"❌ Error converting quote: {e}", "error")
        return redirect(url_for('office.office_dashboard'))
    finally:
        conn.close()

@office_bp.route('/office/upgrade-certs-db')
def upgrade_certs_db():
    if 'user_id' not in session: return "Not logged in"
    conn = get_db(); cur = conn.cursor()
    try:
        # Create a dedicated table for storing detailed Certificate Data (Drafts & Finals)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS certificates (
                id SERIAL PRIMARY KEY,
                company_id INTEGER,
                property_id INTEGER,
                type VARCHAR(20), -- 'EICR', 'CP12', 'PAT'
                status VARCHAR(20), -- 'Draft', 'Issued'
                data JSONB, -- Stores the complex circuit/test data
                engineer_name VARCHAR(100),
                date_issued DATE,
                expiry_date DATE,
                pdf_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        return "✅ SUCCESS: Certificate Storage Engine (JSON) Ready."
    except Exception as e:
        conn.rollback()
        return f"Database Error: {e}"
    finally:
        conn.close()

# --- NEW EICR ROUTE (Unindented) ---
@office_bp.route('/office/cert/eicr/create')
def create_eicr_cert():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    prop_id = request.args.get('prop_id')
    comp_id = session.get('company_id')
    
    conn = get_db(); cur = conn.cursor()
    
    # Get Property Data
    cur.execute("""
        SELECT p.address_line1, p.city, p.postcode, c.name 
        FROM properties p 
        JOIN clients c ON p.client_id = c.id 
        WHERE p.id = %s AND p.company_id = %s
    """, (prop_id, comp_id))
    data = cur.fetchone()
    conn.close()
    
    prop_data = {}
    if data:
        # Re-using the smart address joiner logic
        parts = [data[0], data[1], data[2]]
        full_addr = ", ".join([p for p in parts if p])
        prop_data = {'id': prop_id, 'address': full_addr, 'client': data[3]}
        
    return render_template('office/certs/uk/eicr.html', prop=prop_data, next_five_years=(date.today() + timedelta(days=365*5)))
    
@office_bp.route('/office/job/<int:job_id>/invoice', methods=['GET', 'POST'])
def job_to_invoice(job_id):
    # 1. Security Check
    if not session.get('user_id'): return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    comp_id = session.get('company_id')

    # 2. Check if Invoice Already Exists
    cur.execute("SELECT id FROM invoices WHERE job_id = %s", (job_id,))
    existing = cur.fetchone()
    if existing:
        flash("ℹ️ Invoice already exists for this job.", "info")
        return redirect(url_for('finance.download_invoice_pdf', invoice_id=existing[0]))

    # 3. Fetch Job Data
    cur.execute("SELECT client_id, description, status FROM jobs WHERE id = %s AND company_id = %s", (job_id, comp_id))
    job = cur.fetchone()
    
    if not job:
        conn.close()
        return "Job not found", 404

    client_id = job[0]
    job_desc = job[1]

    # 4. Fetch Markup Setting (Updated to match your HTML)
    cur.execute("SELECT value FROM settings WHERE key = 'default_markup' AND company_id = %s", (comp_id,))
    res = cur.fetchone()
    # Default to 20% if not set
    markup_percent = float(res[0]) if res and res[0] else 20.0
    markup_multiplier = 1 + (markup_percent / 100)

    # 5. Create The Invoice Record
    ref_number = f"INV-JOB-{job_id}"
    cur.execute("""
        INSERT INTO invoices (company_id, client_id, job_id, ref, date_created, due_date, status, total_amount)
        VALUES (%s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + INTERVAL '14 days', 'Unpaid', 0.00)
        RETURNING id
    """, (comp_id, client_id, job_id, ref_number))
    
    new_invoice_id = cur.fetchone()[0]

    # 6. Transfer Materials (Using Dynamic Markup)
    cur.execute("""
        INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
        SELECT %s, description, quantity, (unit_price * %s), (quantity * unit_price * %s)
        FROM job_materials 
        WHERE job_id = %s
    """, (new_invoice_id, markup_multiplier, markup_multiplier, job_id))

    # 7. Add Labor Line
    cur.execute("""
        INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
        VALUES (%s, %s, 1, 0.00, 0.00)
    """, (new_invoice_id, f"Labor / Works for Job #{job_id}: {job_desc}"))

    # 8. Update Total
    cur.execute("""
        UPDATE invoices 
        SET total_amount = (SELECT COALESCE(SUM(total), 0) FROM invoice_items WHERE invoice_id = %s)
        WHERE id = %s
    """, (new_invoice_id, new_invoice_id))
    
    # 9. Mark Job as Invoiced
    cur.execute("UPDATE jobs SET status = 'Invoiced' WHERE id = %s", (job_id,))

    conn.commit()
    conn.close()

    flash(f"✅ Invoice {ref_number} Generated (Markup: {markup_percent}%)", "success")
    return redirect(url_for('finance.finance_invoices'))

# --- SYSTEM UTILITY: MASS FIX DATABASE ---
@office_bp.route('/office/system-repair')
def system_repair():
    if 'user_id' not in session: return "Not logged in"
    
    conn = get_db()
    cur = conn.cursor()
    log = []
    
    try:
        # 1. UPGRADE INVOICES TABLE
        invoice_cols = [
            ("job_id", "INTEGER"), ("ref", "VARCHAR(50)"),
            ("date_created", "DATE DEFAULT CURRENT_DATE"), ("due_date", "DATE"),
            ("status", "VARCHAR(20) DEFAULT 'Unpaid'"),
            ("total_amount", "NUMERIC(10, 2) DEFAULT 0.00"), ("client_id", "INTEGER")
        ]
        for col, dtype in invoice_cols:
            try:
                cur.execute(f"ALTER TABLE invoices ADD COLUMN IF NOT EXISTS {col} {dtype};")
                log.append(f"✅ Checked invoices.{col}")
            except Exception: conn.rollback()

        # 2. CREATE INVOICE ITEMS TABLE
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invoice_items (
                id SERIAL PRIMARY KEY, invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
                description TEXT, quantity INTEGER DEFAULT 1,
                unit_price NUMERIC(10, 2) DEFAULT 0.00, total NUMERIC(10, 2) DEFAULT 0.00
            );
        """)
        log.append("✅ Checked table: invoice_items")

        # 3. UPGRADE JOBS TABLE
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS company_id INTEGER;")
        log.append("✅ Checked jobs.company_id")

        # 4. UPGRADE CLIENTS TABLE
        client_cols = [
            ("status", "VARCHAR(20) DEFAULT 'Active'"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("internal_notes", "TEXT"), ("company_id", "INTEGER")
        ]
        for col, dtype in client_cols:
            try:
                cur.execute(f"ALTER TABLE clients ADD COLUMN IF NOT EXISTS {col} {dtype};")
                log.append(f"✅ Checked clients.{col}")
            except Exception: conn.rollback()

        # 5. UPGRADE PROPERTIES TABLE (THE FIX FOR YOUR NEW ERROR)
        prop_cols = [
            ("tenant", "VARCHAR(100)"),
            ("tenant_phone", "VARCHAR(50)"),
            ("gas_expiry", "DATE"),
            ("eicr_expiry", "DATE"),
            ("pat_expiry", "DATE"),
            ("fire_alarm_expiry", "DATE"),
            ("company_id", "INTEGER")
        ]
        for col, dtype in prop_cols:
            try:
                cur.execute(f"ALTER TABLE properties ADD COLUMN IF NOT EXISTS {col} {dtype};")
                log.append(f"✅ Checked/Added column: properties.{col}")
            except Exception as e:
                conn.rollback()
                log.append(f"⚠️ Note on properties.{col}: {e}")

        conn.commit()
        return f"<h1>System Repair Report</h1><pre>{'<br>'.join(log)}</pre><br><a href='/office-hub'>Return to Dashboard</a>"

    except Exception as e:
        conn.rollback()
        return f"<h1>❌ Critical Error</h1><p>{str(e)}</p>"
    finally:
        conn.close()