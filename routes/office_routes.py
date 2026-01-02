from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify
from db import get_db, get_site_config
from datetime import datetime, date, timedelta
from werkzeug.utils import secure_filename
import os
import secrets
import string
from werkzeug.security import generate_password_hash
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Import the AI Brain
from services.ai_assistant import scan_receipt, verify_license, universal_sort_document

office_bp = Blueprint('office', __name__)
ALLOWED_OFFICE_ROLES = ['Admin', 'SuperAdmin', 'Office']
UPLOAD_FOLDER = 'static/uploads/receipts'

# --- HELPERS ---
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

# --- 1. OFFICE DASHBOARD ---
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

    # Completed Jobs
    cur.execute("SELECT j.id, j.ref, j.site_address, c.name, j.description, j.start_date FROM jobs j LEFT JOIN clients c ON j.client_id = c.id WHERE j.company_id = %s AND j.status = 'Completed' ORDER BY j.start_date DESC", (company_id,))
    completed = [{'id': r[0], 'ref': r[1], 'address': r[2], 'client': r[3], 'desc': r[4], 'date': format_date(r[5])} for r in cur.fetchall()]

    # Live Ops
    cur.execute("SELECT j.id, j.ref, j.site_address, s.name, j.start_date FROM jobs j LEFT JOIN staff s ON j.staff_id = s.id WHERE j.company_id = %s AND j.status = 'In Progress'", (company_id,))
    live = []
    for r in cur.fetchall():
        live.append({'id': r[0], 'ref': r[1], 'address': r[2], 'staff': r[3], 'duration': 'Active'})

    conn.close()
    return render_template('office/office_dashboard.html', pending_requests_count=pending, active_jobs_count=active, quotes=quotes, completed_jobs=completed, live_ops=live, brand_color=config['color'], logo_url=config['logo'])

# --- 2. STAFF MANAGEMENT (AI Powered) ---
@office_bp.route('/office/staff', methods=['GET', 'POST'])
def staff_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    
    try: cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS license_path TEXT"); conn.commit()
    except: conn.rollback()

    if request.method == 'POST':
        action = request.form.get('action')
        name = request.form.get('name')
        
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
                ai_check = verify_license(full_sys_path, name)
                if ai_check['success'] and not ai_check['verified']:
                    flash(f"⚠️ AI Warning: The name on this license does not match '{name}'.", "warning")
                elif ai_check['success']:
                    flash("✅ AI Verified: License name matches staff member.")

        try:
            if action == 'add_staff':
                cur.execute("INSERT INTO staff (company_id, name, email, phone, position, status, license_path) VALUES (%s, %s, %s, %s, %s, 'Active', %s)", 
                           (comp_id, name, request.form.get('email'), request.form.get('phone'), request.form.get('role'), file_path))
                conn.commit(); flash("✅ Staff Added")
            
            elif action == 'edit_staff':
                sid = request.form.get('staff_id')
                # Use COALESCE logic in Python or SQL to keep old file if no new file uploaded
                if file_path:
                    cur.execute("UPDATE staff SET name=%s, email=%s, phone=%s, position=%s, status=%s, license_path=%s WHERE id=%s AND company_id=%s", 
                               (name, request.form.get('email'), request.form.get('phone'), request.form.get('role'), request.form.get('status'), file_path, sid, comp_id))
                else:
                    cur.execute("UPDATE staff SET name=%s, email=%s, phone=%s, position=%s, status=%s WHERE id=%s AND company_id=%s", 
                               (name, request.form.get('email'), request.form.get('phone'), request.form.get('role'), request.form.get('status'), sid, comp_id))
                conn.commit(); flash("✅ Staff Updated")

        except Exception as e: conn.rollback(); flash(f"Error: {e}")

    # Fetch Data
    cur.execute("SELECT id, name, email, phone, position AS role, status, license_path FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    cols = [desc[0] for desc in cur.description]
    staff = [dict(zip(cols, row)) for row in cur.fetchall()]
    
    # Fetch History
    cur.execute("SELECT j.id, j.ref, j.site_address, j.description, j.start_date, j.status, j.staff_id FROM jobs j WHERE j.company_id = %s AND j.staff_id IS NOT NULL ORDER BY j.start_date DESC", (comp_id,))
    jobs_by_staff = {}
    for j in cur.fetchall():
        sid = j[6]
        if sid not in jobs_by_staff: jobs_by_staff[sid] = []
        jobs_by_staff[sid].append({'ref': j[1], 'address': j[2], 'desc': j[3], 'date': format_date(j[4]), 'status': j[5]})
    
    for s in staff: s['history'] = jobs_by_staff.get(s['id'], [])

    conn.close()
    return render_template('office/staff_management.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

# --- 3. FLEET MANAGEMENT (AI Powered) ---
@office_bp.route('/office/fleet', methods=['GET', 'POST'])
def fleet_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    
    cur.execute("CREATE TABLE IF NOT EXISTS vehicle_crew (vehicle_id INTEGER, staff_id INTEGER, PRIMARY KEY(vehicle_id, staff_id))")
    try: cur.execute("ALTER TABLE maintenance_logs ADD COLUMN IF NOT EXISTS receipt_path TEXT"); conn.commit()
    except: conn.rollback() 

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
                        
                        # AI Auto-Fill
                        if not cost or cost == '0':
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

    # Fetch Fleet Data
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

# --- 4. UNIVERSAL UPLOAD CENTER (AI) ---
@office_bp.route('/office/upload-center', methods=['POST'])
def universal_upload():
    if not check_office_access(): return jsonify({'error': 'Unauthorized'}), 403
    
    comp_id = session.get('company_id')
    file = request.files.get('file')
    if not file: return jsonify({'error': 'No file'}), 400

    # 1. Secure Storage
    save_dir = os.path.join('static', 'uploads', str(comp_id), 'inbox')
    os.makedirs(save_dir, exist_ok=True)
    
    filename = secure_filename(f"{int(datetime.now().timestamp())}_{file.filename}")
    full_path = os.path.join(save_dir, filename)
    file.save(full_path)
    db_path = f"uploads/{comp_id}/inbox/{filename}"

    # 2. AI Analysis
    scan = universal_sort_document(full_path)
    
    if not scan['success']:
        return jsonify({'status': 'error', 'message': scan.get('error')})

    result = scan['result']
    doc_type = result.get('doc_type')
    data = result.get('data', {})
    
    conn = get_db(); cur = conn.cursor()
    msg = "File Processed"
    
    try:
        # A. FUEL RECEIPT
        if doc_type == 'fuel_receipt':
            v_id = None
            reg = data.get('vehicle_reg')
            if reg:
                clean_reg = reg.replace(" ", "")
                cur.execute("SELECT id FROM vehicles WHERE REPLACE(reg_plate, ' ', '') ILIKE %s AND company_id=%s", (f"%{clean_reg}%", comp_id))
                row = cur.fetchone()
                if row: v_id = row[0]

            cur.execute("""
                INSERT INTO maintenance_logs (company_id, vehicle_id, type, description, date, cost, receipt_path)
                VALUES (%s, %s, 'Fuel', %s, %s, %s, %s)
            """, (comp_id, v_id, f"AI: {data.get('vendor')} ({reg or 'Unknown Van'})", data.get('date') or date.today(), data.get('total_cost') or 0, db_path))
            msg = f"Fuel Logged. Linked to Van: {reg if v_id else 'No Match Found'}"

        # B. INVOICE
        elif doc_type == 'supplier_invoice':
            cur.execute("""
                CREATE TABLE IF NOT EXISTS job_expenses (
                    id SERIAL PRIMARY KEY, company_id INTEGER, job_id INTEGER, 
                    description TEXT, cost REAL, date DATE, receipt_path TEXT
                )
            """)
            j_id = None
            ref = data.get('job_ref')
            if ref:
                cur.execute("SELECT id FROM jobs WHERE ref ILIKE %s AND company_id=%s", (f"%{ref}%", comp_id))
                row = cur.fetchone()
                if row: j_id = row[0]
            
            cur.execute("""
                INSERT INTO job_expenses (company_id, job_id, description, cost, date, receipt_path)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (comp_id, j_id, f"Invoice: {data.get('supplier_name')}", data.get('total') or 0, data.get('date') or date.today(), db_path))
            msg = f"Invoice Filed. Linked to Job: {ref if j_id else 'Unassigned'}"

        # C. LICENSE
        elif doc_type == 'driving_license':
            s_name = data.get('staff_name')
            s_id = None
            if s_name:
                cur.execute("SELECT id FROM staff WHERE name ILIKE %s AND company_id=%s", (f"%{s_name}%", comp_id))
                row = cur.fetchone()
                if row: 
                    s_id = row[0]
                    cur.execute("UPDATE staff SET license_path = %s WHERE id = %s", (db_path, s_id))
                    msg = f"License Verified & Attached to {s_name}."
                else:
                    msg = f"License Uploaded for {s_name}, but staff member not found."
            else:
                msg = "License uploaded but no name could be read."

        conn.commit()
        return jsonify({'status': 'success', 'doc_type': doc_type, 'message': msg, 'data': data})

    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        conn.close()

# --- 5. ENABLE PORTAL ---
@office_bp.route('/office/client/<int:client_id>/enable-portal', methods=['POST'])
def enable_portal(client_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

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

            body = f"""
            <h3>Hello {client_name},</h3>
            <p>An account has been created for you to track your jobs, quotes, and invoices.</p>
            <div style="background:#f4f4f4; padding:15px; border-radius:5px; margin: 15px 0;">
                <strong>Login URL:</strong> <a href="{login_url}">{login_url}</a><br>
                <strong>Username:</strong> {client_email}<br>
                <strong>Password:</strong> {raw_password}
            </div>
            """
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
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error")
    finally:
        conn.close()

    return redirect('/clients')

# --- 6. SERVICE DESK ---
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
            elif action == 'convert_job':
                return redirect(url_for('office.office_calendar'))
                
            conn.commit()
        except Exception as e:
            conn.rollback(); flash(f"Error updating request: {e}")

    cur.execute("""
        SELECT sr.id, sr.issue_description, sr.severity, sr.status, sr.created_at, c.name, p.address_line1
        FROM service_requests sr
        LEFT JOIN clients c ON sr.client_id = c.id
        LEFT JOIN properties p ON sr.property_id = p.id
        WHERE sr.company_id = %s
        ORDER BY CASE WHEN sr.status = 'Pending' THEN 1 ELSE 2 END, sr.created_at DESC
    """, (comp_id,))
    
    rows = cur.fetchall()
    requests = []
    for r in rows:
        requests.append({
            'id': r[0], 'issue_description': r[1], 'severity': r[2], 'status': r[3], 'date': format_date(r[4]),
            'client_name': r[5] or 'N/A', 'property_address': r[6] or 'General'
        })

    cur.execute("SELECT id, name FROM staff WHERE company_id = %s", (comp_id,))
    staff = [{'id': s[0], 'name': s[1]} for s in cur.fetchall()]

    conn.close()
    return render_template('office/service_desk.html', requests=requests, staff=staff, brand_color=config['color'], logo_url=config['logo'])

# --- DISPATCH JOB (Smart Update) ---
@office_bp.route('/office/create-work-order', methods=['POST'])
def create_work_order():
    if 'user_id' not in session: return redirect('/login')

    request_id = request.form.get('request_id')
    staff_id = request.form.get('assigned_staff_id')
    schedule_date = request.form.get('schedule_date')

    conn = get_db(); cur = conn.cursor()

    try:
        # 1. Get details from the Service Request
        cur.execute("SELECT property_id, client_id, issue_description FROM service_requests WHERE id = %s", (request_id,))
        req_data = cur.fetchone()
        
        if not req_data:
            flash("❌ Error: Service Request not found.", "error")
            return redirect('/office/service-desk')

        prop_id, client_id, description = req_data

        # 2. CHECK: Is there already an ACTIVE job for this property?
        # We assume if it's not 'Completed', it's the one we are working on.
        cur.execute("""
            SELECT id FROM jobs 
            WHERE property_id = %s AND status != 'Completed'
        """, (prop_id,))
        existing_job = cur.fetchone()

        if existing_job:
            # --- SCENARIO A: UPDATE EXISTING JOB ---
            job_id = existing_job[0]
            cur.execute("""
                UPDATE jobs 
                SET engineer_id = %s, start_date = %s 
                WHERE id = %s
            """, (staff_id, schedule_date, job_id))
            
            # Update the ticket status just in case it wasn't set
            cur.execute("UPDATE service_requests SET status = 'In Progress' WHERE id = %s", (request_id,))
            
            flash(f"✅ Job updated! Reassigned to new engineer/date.", "info")

        else:
            # --- SCENARIO B: CREATE NEW JOB ---
            # Generate a Job Ref (e.g., JOB-{prop_id}-{random})
            import random
            job_ref = f"JOB-{prop_id}-{random.randint(100,999)}"

            cur.execute("""
                INSERT INTO jobs (company_id, client_id, property_id, engineer_id, start_date, status, description, ref)
                VALUES (%s, %s, %s, %s, %s, 'Scheduled', %s, %s)
            """, (session['company_id'], client_id, prop_id, staff_id, schedule_date, description, job_ref))

            # Mark the Ticket as 'In Progress' so the client sees it
            cur.execute("UPDATE service_requests SET status = 'In Progress' WHERE id = %s", (request_id,))
            
            flash(f"✅ Job Created & Dispatched successfully!", "success")

        conn.commit()

    except Exception as e:
        conn.rollback()
        flash(f"Error dispatching job: {e}", "error")
    finally:
        conn.close()

    return redirect('/office/service-desk')

# --- 8. SYSTEM REPAIR ---
@office_bp.route('/office/system-upgrade')
@office_bp.route('/office/repair-db')
def system_upgrade():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    log = []
    
    try:
        # 1. Invoices Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL, client_id INTEGER NOT NULL,
                invoice_number VARCHAR(50), date_issue DATE, total_amount NUMERIC(10, 2),
                status VARCHAR(20) DEFAULT 'Unpaid', file_path TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 2. Property Columns
        cur.execute("ALTER TABLE properties ADD COLUMN IF NOT EXISTS tenant_phone VARCHAR(50)")
        cur.execute("ALTER TABLE properties ADD COLUMN IF NOT EXISTS key_code VARCHAR(100)")
        
        # 3. Service Request Columns
        cur.execute("ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS image_url TEXT")
        
        # 4. Jobs Column
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS property_id INTEGER")
        
        # 5. Quote Items Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS quote_items (
                id SERIAL PRIMARY KEY,
                quote_id INTEGER,
                description TEXT,
                quantity INTEGER,
                unit_price NUMERIC(10, 2),
                total NUMERIC(10, 2)
            )
        """)
        
        conn.commit()
        log.append("✅ Success: All database tables and columns verified.")
        
    except Exception as e:
        conn.rollback(); log.append(f"❌ Error: {e}")
    finally:
        conn.close()
        
    return "<br>".join(log)

# --- 9. CALENDAR ROUTES ---
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

# --- 10. PLACEHOLDER ROUTES (To prevent crashes) ---
@office_bp.route('/client/<int:client_id>')
def view_client(client_id): return "Client View Placeholder" 
@office_bp.route('/client/<int:client_id>/add_property', methods=['POST'])
def add_property(client_id): return redirect(url_for('office.view_client', client_id=client_id))
@office_bp.route('/office/quote/<int:quote_id>/convert')
def convert_to_invoice(quote_id): return redirect(url_for('office.office_dashboard'))