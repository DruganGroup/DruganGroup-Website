from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify
from db import get_db, get_site_config
from datetime import datetime, date, timedelta
from werkzeug.utils import secure_filename
import os

office_bp = Blueprint('office', __name__)
ALLOWED_OFFICE_ROLES = ['Admin', 'SuperAdmin', 'Office']

def check_office_access():
    if 'user_id' not in session: return False
    if session.get('role') not in ALLOWED_OFFICE_ROLES: return False
    return True

def get_staff_list(cur, company_id):
    try:
        cur.execute("SELECT id, name, email, phone, position AS role, status FROM staff WHERE company_id = %s ORDER BY name", (company_id,))
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except: return []

# --- HELPER: UK DATE FORMATTER ---
def uk_date(d):
    if not d: return ""
    try:
        if isinstance(d, str):
            try: d = datetime.strptime(d, '%Y-%m-%d')
            except: 
                try: d = datetime.strptime(d, '%Y-%m-%d %H:%M:%S')
                except: return d
        return d.strftime('%d/%m/%Y')
    except: return str(d)

# --- 1. OFFICE DASHBOARD (Updated with Live Ops) ---
@office_bp.route('/office-hub')
@office_bp.route('/office-hub.html')
def office_dashboard():
    if not check_office_access(): return redirect(url_for('auth.login'))
    company_id = session.get('company_id')
    config = get_site_config(company_id)
    conn = get_db(); cur = conn.cursor()
    
    # Basic Stats
    cur.execute("SELECT COUNT(*) FROM service_requests WHERE company_id = %s AND status != 'Completed'", (company_id,))
    pending_requests_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id = %s AND status != 'Completed'", (company_id,))
    active_jobs_count = cur.fetchone()[0]

    # Quotes (Apply UK Date)
    cur.execute("SELECT q.id, c.name, q.reference, q.date, q.total, q.status FROM quotes q LEFT JOIN clients c ON q.client_id = c.id WHERE q.company_id = %s AND q.status = 'Draft' ORDER BY q.id DESC LIMIT 5", (company_id,))
    recent_quotes = []
    for r in cur.fetchall():
        recent_quotes.append((r[0], r[1], r[2], uk_date(r[3]), r[4], r[5]))

    # Completed Jobs (Apply UK Date)
    cur.execute("""
        SELECT j.id, j.ref, j.site_address, c.name, j.description, j.start_date
        FROM jobs j LEFT JOIN clients c ON j.client_id = c.id
        WHERE j.company_id = %s AND j.status = 'Completed'
        ORDER BY j.start_date DESC
    """, (company_id,))
    completed_jobs = []
    for r in cur.fetchall():
        completed_jobs.append({'id': r[0], 'ref': r[1], 'address': r[2], 'client': r[3], 'desc': r[4], 'date': uk_date(r[5])})

    # --- LIVE OPERATIONS BOARD logic ---
    # Fetch jobs that are 'In Progress' right now
    cur.execute("""
        SELECT j.id, j.ref, j.site_address, s.name, j.start_date
        FROM jobs j
        LEFT JOIN staff s ON j.staff_id = s.id
        WHERE j.company_id = %s AND j.status = 'In Progress'
    """, (company_id,))
    
    live_ops = []
    now = datetime.now()
    for r in cur.fetchall():
        start_time = r[4] # This is a datetime object from DB
        duration_str = "Just Started"
        
        # Calculate Duration
        if start_time:
            # Handle edge case where DB returns date only
            if isinstance(start_time, date) and not isinstance(start_time, datetime):
                start_time = datetime.combine(start_time, datetime.min.time())
            
            diff = now - start_time
            hours = diff.seconds // 3600
            mins = (diff.seconds % 3600) // 60
            duration_str = f"{hours}h {mins}m"

        live_ops.append({
            'id': r[0], 'ref': r[1], 'address': r[2], 
            'staff': r[3], 'duration': duration_str
        })

    conn.close()

    return render_template('office/office_dashboard.html', 
                         pending_requests_count=pending_requests_count, 
                         active_jobs_count=active_jobs_count, 
                         quotes=recent_quotes,
                         completed_jobs=completed_jobs,
                         live_ops=live_ops, # <--- Sending Live Data
                         brand_color=config['color'], 
                         logo_url=config['logo'])

# --- 2. MANUAL INVOICE GENERATION (Backup) ---
@office_bp.route('/office/job/<int:job_id>/invoice', methods=['POST'])
def generate_invoice_from_job(job_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    try:
        cur.execute("SELECT client_id, ref, description, start_date FROM jobs WHERE id = %s", (job_id,))
        job = cur.fetchone()
        client_id, job_ref, job_desc, job_date = job
        
        cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id = %s", (comp_id,))
        new_ref = f"INV-{1000 + cur.fetchone()[0] + 1}"

        cur.execute("""
            INSERT INTO invoices (company_id, client_id, quote_ref, reference, date, due_date, status, subtotal, tax, total, notes) 
            VALUES (%s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + 14, 'Unpaid', 0, 0, 0, %s) 
            RETURNING id
        """, (comp_id, client_id, job_ref, new_ref, f"Generated from Job {job_ref}"))
        inv_id = cur.fetchone()[0]

        # Use uk_date here for the description
        cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) VALUES (%s, %s, 1, 0, 0)", (inv_id, f"Work Completed: {job_desc} ({uk_date(job_date)})"))
        cur.execute("UPDATE jobs SET status = 'Invoiced' WHERE id = %s", (job_id,))
        conn.commit(); flash(f"✅ Invoice {new_ref} Generated!")
        return redirect(url_for('finance.finance_dashboard')) 
    except Exception as e: conn.rollback(); flash(f"❌ Error: {e}"); return redirect(url_for('office.office_dashboard'))
    finally: conn.close()

# --- 3. CREATE QUOTE ---
@office_bp.route('/office/quote/new', methods=['GET', 'POST'])
def create_quote():
    allowed_roles = ['Admin', 'SuperAdmin', 'Office', 'Site Manager']
    if session.get('role') not in allowed_roles: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    tax_rate = float(settings.get('tax_rate', '20')) / 100 if settings.get('vat_registered', 'no') == 'yes' else 0.0

    if request.method == 'POST':
        try:
            client_mode = request.form.get('client_mode'); client_id = None
            if client_mode == 'existing': client_id = request.form.get('existing_client_id')
            elif client_mode == 'new':
                cur.execute("INSERT INTO clients (company_id, name, email, address, status) VALUES (%s, %s, %s, %s, 'Active') RETURNING id", (comp_id, request.form.get('new_client_name'), request.form.get('new_client_email'), request.form.get('new_client_address')))
                client_id = cur.fetchone()[0]

            if not client_id: client_id = request.form.get('client_id') 
            if not client_id: raise Exception("No client selected.")
            
            ref = request.form.get('reference'); notes = request.form.get('notes')
            cur.execute("INSERT INTO quotes (company_id, client_id, reference, status, notes, date) VALUES (%s, %s, %s, 'Draft', %s, CURRENT_DATE) RETURNING id", (comp_id, client_id, ref, notes))
            quote_id = cur.fetchone()[0]
            
            descriptions = request.form.getlist('desc[]'); quantities = request.form.getlist('qty[]'); prices = request.form.getlist('price[]')
            grand_subtotal = 0
            for i in range(len(descriptions)):
                if descriptions[i]: 
                    d = descriptions[i]; q = float(quantities[i]) if quantities[i] else 0; p = float(prices[i]) if prices[i] else 0
                    row_total = q * p; grand_subtotal += row_total
                    cur.execute("INSERT INTO quote_items (quote_id, description, quantity, unit_price, total) VALUES (%s, %s, %s, %s, %s)", (quote_id, d, q, p, row_total))
            
            tax_amount = grand_subtotal * tax_rate; final_total = grand_subtotal + tax_amount
            cur.execute("UPDATE quotes SET subtotal=%s, tax=%s, total=%s WHERE id=%s", (grand_subtotal, tax_amount, final_total, quote_id))
            conn.commit(); flash(f"✅ Quote {ref} Created!")
            return redirect(url_for('office.view_quote', quote_id=quote_id))
        except Exception as e: conn.rollback(); flash(f"Error: {e}")
            
    cur.execute("SELECT COUNT(*) FROM quotes WHERE company_id = %s", (comp_id,))
    count = cur.fetchone()[0]; new_ref = f"Q-{1000 + count + 1}"
    cur.execute("SELECT id, name FROM clients WHERE company_id = %s ORDER BY name", (comp_id,))
    clients = cur.fetchall(); conn.close()
    return render_template('office/create_quote.html', clients=clients, new_ref=new_ref, today=date.today(), tax_rate=tax_rate, settings=settings, brand_color=config['color'], logo_url=config['logo'])

# --- 4. VIEW QUOTE ---
@office_bp.route('/office/quote/<int:quote_id>')
def view_quote(quote_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office', 'Site Manager']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()

    cur.execute("SELECT q.id, c.name, c.address, c.email, q.reference, q.date, q.status, q.subtotal, q.tax, q.total, q.notes FROM quotes q JOIN clients c ON q.client_id = c.id WHERE q.id = %s AND q.company_id = %s", (quote_id, comp_id))
    quote = cur.fetchone()
    
    if not quote: return redirect(url_for('finance.finance_dashboard')) 

    cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
    items = cur.fetchall()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    settings['brand_color'] = config['color']; settings['logo_url'] = config['logo']
    
    staff_list = get_staff_list(cur, comp_id)
    conn.close()

    if request.args.get('mode') == 'pdf': return render_template('office/pdf_quote.html', quote=quote, items=items, settings=settings)
    return render_template('office/view_quote_dashboard.html', quote=quote, items=items, settings=settings, staff=staff_list)

# --- 5. CONVERT QUOTE TO INVOICE ---
@office_bp.route('/office/quote/<int:quote_id>/convert')
def convert_to_invoice(quote_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    return redirect(url_for('office.office_dashboard'))

# --- 6. CONVERT QUOTE TO JOB ---
@office_bp.route('/office/quote/convert-job', methods=['POST'])
def convert_quote_to_job():
    if not check_office_access(): return redirect(url_for('auth.login'))
    quote_id = request.form.get('quote_id'); staff_id = request.form.get('staff_id'); schedule_date = request.form.get('schedule_date')
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT client_id, reference, notes FROM quotes WHERE id = %s", (quote_id,))
        quote = cur.fetchone()
        cur.execute("INSERT INTO jobs (company_id, staff_id, client_id, start_date, description, status, ref) VALUES (%s, %s, %s, %s, %s, 'Scheduled', %s)", (session['company_id'], staff_id, quote[0], schedule_date, f"Quote Work: {quote[1]}", f"Ref: {quote[1]}"))
        cur.execute("UPDATE quotes SET status = 'Converted' WHERE id = %s", (quote_id,))
        conn.commit(); flash(f"✅ Job Created!")
    except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")
    finally: conn.close()
    return redirect(url_for('office.office_dashboard'))

# --- 7. SERVICE DESK ---
@office_bp.route('/office/service-desk')
def service_desk():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT r.id, p.address_line1, r.issue_description, c.name, r.severity, r.status, r.created_at FROM service_requests r JOIN properties p ON r.property_id = p.id JOIN clients c ON r.client_id = c.id WHERE r.company_id = %s AND r.status != 'Completed' ORDER BY r.created_at DESC", (comp_id,))
    except:
        conn.rollback(); cur.execute("SELECT r.id, p.site_address, r.issue_description, c.name, r.severity, r.status, r.created_at FROM service_requests r JOIN properties p ON r.property_id = p.id JOIN clients c ON r.client_id = c.id WHERE r.company_id = %s AND r.status != 'Completed' ORDER BY r.created_at DESC", (comp_id,))
    rows = cur.fetchall()
    requests_list = []
    for r in rows:
        requests_list.append({'id': r[0], 'property_address': r[1], 'issue_description': r[2], 'client_name': r[3], 'severity': r[4], 'status': r[5], 'date': uk_date(r[6])})
    staff_members = get_staff_list(cur, comp_id)
    conn.close()
    return render_template('office/service_desk.html', requests=requests_list, staff=staff_members, brand_color=config['color'], logo_url=config['logo'])

# --- 8. CREATE WORK ORDER ---
@office_bp.route('/office/create-work-order', methods=['POST'])
def create_work_order():
    if not check_office_access(): return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO jobs (company_id, client_id, staff_id, start_date, description, status) VALUES (%s, %s, %s, %s, %s, 'Scheduled')", 
                   (session['company_id'], request.form.get('client_id'), request.form.get('assigned_staff_id'), request.form.get('schedule_date'), request.form.get('job_type')))
        cur.execute("UPDATE service_requests SET status = 'In Progress' WHERE id = %s", (request.form.get('request_id'),))
        conn.commit(); flash("✅ Work Order Created!")
    except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")
    finally: conn.close()
    return redirect(url_for('office.service_desk'))

# --- 9. STAFF MANAGEMENT ---
@office_bp.route('/office/staff', methods=['GET', 'POST'])
def staff_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    if request.method == 'POST':
        try:
            cur.execute("INSERT INTO staff (company_id, name, email, phone, position, status) VALUES (%s, %s, %s, %s, %s, 'Active')", (comp_id, request.form.get('name'), request.form.get('email'), request.form.get('phone'), request.form.get('role')))
            conn.commit(); flash("✅ Staff Added.")
        except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")
    cur.execute("SELECT id, name, email, phone, position AS role, status FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    cols = [desc[0] for desc in cur.description]
    staff = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
    return render_template('office/staff_management.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

# --- 7. OFFICE FLEET (RESTRICTED + RECEIPT UPLOADS) ---
@office_bp.route('/office/fleet', methods=['GET', 'POST'])
def fleet_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id) 
    conn = get_db(); cur = conn.cursor()
    date_fmt = get_date_fmt_str(comp_id)

    # 1. Ensure DB Schema for Receipts
    cur.execute("CREATE TABLE IF NOT EXISTS vehicle_crew (vehicle_id INTEGER, staff_id INTEGER, PRIMARY KEY(vehicle_id, staff_id))")
    
    # Auto-migration: Check if receipt_path exists, if not add it (Silent fail if exists)
    try:
        cur.execute("ALTER TABLE maintenance_logs ADD COLUMN IF NOT EXISTS receipt_path TEXT")
        conn.commit()
    except:
        conn.rollback() 

    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'assign_crew':
                v_id = request.form.get('vehicle_id'); crew_ids = request.form.getlist('crew_ids')
                cur.execute("DELETE FROM vehicle_crew WHERE vehicle_id = %s", (v_id,))
                for staff_id in crew_ids: cur.execute("INSERT INTO vehicle_crew (vehicle_id, staff_id) VALUES (%s, %s)", (v_id, staff_id))
                flash("✅ Crew Updated")
                
            elif action == 'add_log':
                # Handle File Upload for Receipts
                file_url = None
                if 'receipt_file' in request.files:
                    file = request.files['receipt_file']
                    if file and file.filename != '':
                        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                        filename = secure_filename(f"receipt_{comp_id}_{int(datetime.now().timestamp())}_{file.filename}")
                        file.save(os.path.join(UPLOAD_FOLDER, filename))
                        file_url = f"uploads/receipts/{filename}" # Relative path for DB

                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, type, description, date, cost, receipt_path) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (comp_id, request.form.get('vehicle_id'), request.form.get('log_type'), request.form.get('description'), request.form.get('date'), request.form.get('cost') or 0, file_url))
                flash("✅ Log & Receipt Added")
            
            conn.commit()
        except Exception as e: conn.rollback(); flash(f"Error: {e}")

    # Fetch Ops Data
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.status, s.name, v.assigned_driver_id, 
               v.mot_due, v.tax_due, v.insurance_due, v.tracker_url
        FROM vehicles v LEFT JOIN staff s ON v.assigned_driver_id = s.id 
        WHERE v.company_id = %s ORDER BY v.reg_plate
    """, (comp_id,))
    
    raw_vehicles = cur.fetchall(); vehicles = []; cur2 = conn.cursor()
    for row in raw_vehicles:
        v_id = row[0]
        cur2.execute("SELECT s.id, s.name, s.position FROM vehicle_crew vc JOIN staff s ON vc.staff_id = s.id WHERE vc.vehicle_id = %s", (v_id,))
        crew = [{'id': c[0], 'name': c[1], 'role': c[2]} for c in cur2.fetchall()]
        
        cur2.execute("SELECT date, type, description, cost, receipt_path FROM maintenance_logs WHERE vehicle_id = %s ORDER BY date DESC", (v_id,))
        history = [{'date': format_date(r[0], date_fmt), 'type': r[1], 'desc': r[2], 'cost': r[3], 'receipt': r[4]} for r in cur2.fetchall()]

        vehicles.append({
            'id': row[0], 'reg_number': row[1], 'make_model': row[2], 'status': row[3],
            'driver_name': row[4], 'assigned_driver_id': row[5],
            'mot_expiry': parse_date(row[6]), 
            'tax_expiry': parse_date(row[7]), 
            'ins_expiry': parse_date(row[8]),
            'tracker_url': row[9],
            'crew': crew, 'history': history
        })
        
    cur.execute("SELECT id, name, position as role FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    staff = [dict(zip(['id', 'name', 'role'], r)) for r in cur.fetchall()]
    cur2.close(); conn.close()
    
    return render_template('office/fleet_management.html', 
                         vehicles=vehicles, staff=staff, today=date.today(), date_fmt=date_fmt,
                         brand_color=config['color'], logo_url=config['logo'])

    # Fetch Data for Display
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.status, s.name, v.assigned_driver_id, 
               v.mot_due, v.tax_due, v.insurance_due, v.tracker_url, v.defect_notes
        FROM vehicles v LEFT JOIN staff s ON v.assigned_driver_id = s.id 
        WHERE v.company_id = %s ORDER BY v.reg_plate
    """, (comp_id,))
    
    vehicles = []
    rows = cur.fetchall()
    
    # Secondary cursor for lists
    cur2 = conn.cursor()
    
    for r in rows:
        v_id = r[0]
        # Get Crew
        cur2.execute("SELECT s.id, s.name FROM vehicle_crew vc JOIN staff s ON vc.staff_id = s.id WHERE vc.vehicle_id = %s", (v_id,))
        crew = [{'id': c[0], 'name': c[1]} for c in cur2.fetchall()]
        
        # Get History
        cur2.execute("SELECT date, type, description, cost FROM maintenance_logs WHERE vehicle_id = %s ORDER BY date DESC", (v_id,))
        history = [{'date': h[0], 'desc': h[2], 'cost': h[3]} for h in cur2.fetchall()]

        vehicles.append({
            'id': r[0], 'reg_number': r[1], 'make_model': r[2], 'status': r[3],
            'driver_name': r[4], 'assigned_driver_id': r[5],
            'mot_expiry': to_date(r[6]), # Convert to Object for Math
            'tax_expiry': to_date(r[7]), 
            'ins_expiry': to_date(r[8]),
            'tracker_url': r[9], 'defect_notes': r[10],
            'crew': crew, 'history': history
        })

    cur.execute("SELECT id, name FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    staff = [{'id': s[0], 'name': s[1]} for s in cur.fetchall()]
    
    conn.close()
    
    # Pointing to the correct Office Template
    return render_template('office/fleet_management.html', vehicles=vehicles, staff=staff, today=date.today())

# --- 11. CALENDAR ---
@office_bp.route('/office/calendar')
def office_calendar():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id)
    return render_template('office/calendar.html', brand_color=config['color'], logo_url=config['logo'])

@office_bp.route('/office/calendar/data')
def get_calendar_data():
    if not check_office_access(): return jsonify([])
    comp_id = session.get('company_id'); conn = get_db(); cur = conn.cursor()
    events = []
    try:
        cur.execute("SELECT j.id, j.ref, j.start_date, c.name, j.status, j.description FROM jobs j LEFT JOIN clients c ON j.client_id = c.id WHERE j.company_id = %s AND j.start_date IS NOT NULL", (comp_id,))
        for j in cur.fetchall():
            events.append({'title': f"{j[1]} - {j[3] or 'Client'}", 'start': str(j[2]), 'color': '#28a745' if j[4] == 'Completed' else '#0d6efd', 'url': f"/site/job/{j[0]}", 'allDay': True})
    except: pass
    conn.close()
    return jsonify(events)

# --- 12. CLIENTS & PROPERTIES ---
@office_bp.route('/client/<int:client_id>')
def view_client(client_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    return "Client View Placeholder" 

@office_bp.route('/client/<int:client_id>/add_property', methods=['POST'])
def add_property(client_id):
    return redirect(url_for('office.view_client', client_id=client_id))