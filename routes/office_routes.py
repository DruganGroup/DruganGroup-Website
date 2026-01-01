from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify
from db import get_db, get_site_config
from datetime import datetime, date, timedelta
from werkzeug.utils import secure_filename
import os

office_bp = Blueprint('office', __name__)
ALLOWED_OFFICE_ROLES = ['Admin', 'SuperAdmin', 'Office']
UPLOAD_FOLDER = 'static/uploads/receipts'

# --- 1. CONFIG & HELPERS (These were missing!) ---
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
    'Default': '%d/%m/%Y' 
}

def check_office_access():
    if 'user_id' not in session: return False
    if session.get('role') not in ALLOWED_OFFICE_ROLES: return False
    return True

def get_date_fmt_str(company_id):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'company_country'", (company_id,))
        row = cur.fetchone(); conn.close()
        return COUNTRY_FORMATS.get(row[0] if row else 'Default', COUNTRY_FORMATS['Default'])
    except: return COUNTRY_FORMATS['Default']

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

def parse_date(d):
    """Parses string to Date Object for Math"""
    if isinstance(d, str):
        try: return datetime.strptime(d, '%Y-%m-%d').date()
        except: return None
    return d

def get_staff_list(cur, company_id):
    try:
        cur.execute("SELECT id, name, email, phone, position AS role, status FROM staff WHERE company_id = %s ORDER BY name", (company_id,))
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except: return []

# --- 2. OFFICE DASHBOARD ---
@office_bp.route('/office-hub')
@office_bp.route('/office-hub.html')
def office_dashboard():
    if not check_office_access(): return redirect(url_for('auth.login'))
    company_id = session.get('company_id'); config = get_site_config(company_id)
    conn = get_db(); cur = conn.cursor(); date_fmt = get_date_fmt_str(company_id)
    
    cur.execute("SELECT COUNT(*) FROM service_requests WHERE company_id = %s AND status != 'Completed'", (company_id,))
    pending = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id = %s AND status != 'Completed'", (company_id,))
    active = cur.fetchone()[0]

    cur.execute("SELECT q.id, c.name, q.reference, q.date, q.total, q.status FROM quotes q LEFT JOIN clients c ON q.client_id = c.id WHERE q.company_id = %s AND q.status = 'Draft' ORDER BY q.id DESC LIMIT 5", (company_id,))
    quotes = [(r[0], r[1], r[2], format_date(r[3], date_fmt), r[4], r[5]) for r in cur.fetchall()]

    cur.execute("SELECT j.id, j.ref, j.site_address, c.name, j.description, j.start_date FROM jobs j LEFT JOIN clients c ON j.client_id = c.id WHERE j.company_id = %s AND j.status = 'Completed' ORDER BY j.start_date DESC", (company_id,))
    completed = [{'id': r[0], 'ref': r[1], 'address': r[2], 'client': r[3], 'desc': r[4], 'date': format_date(r[5], date_fmt)} for r in cur.fetchall()]

    try:
        cur.execute("SELECT j.id, j.ref, j.site_address, s.name, j.start_date FROM jobs j LEFT JOIN staff s ON j.staff_id = s.id WHERE j.company_id = %s AND j.status = 'In Progress'", (company_id,))
        live = []
        now = datetime.now()
        for r in cur.fetchall():
            st = r[4]; dur = "Just Started"
            if st:
                if isinstance(st, str): 
                    try: st = datetime.strptime(st, '%Y-%m-%d %H:%M:%S')
                    except: pass
                elif isinstance(st, date) and not isinstance(st, datetime): st = datetime.combine(st, datetime.min.time())
                if isinstance(st, datetime):
                    diff = now - st
                    dur = f"{diff.seconds // 3600}h {(diff.seconds % 3600) // 60}m"
            live.append({'id': r[0], 'ref': r[1], 'address': r[2], 'staff': r[3], 'duration': dur})
    except: live = []

    conn.close()
    return render_template('office/office_dashboard.html', pending_requests_count=pending, active_jobs_count=active, quotes=quotes, completed_jobs=completed, live_ops=live, brand_color=config['color'], logo_url=config['logo'])

# --- 3. INVOICE GENERATION ---
@office_bp.route('/office/job/<int:job_id>/invoice', methods=['POST'])
def generate_invoice_from_job(job_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT client_id, ref, description, start_date FROM jobs WHERE id = %s", (job_id,))
        job = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id = %s", (comp_id,))
        new_ref = f"INV-{1000 + cur.fetchone()[0] + 1}"
        cur.execute("INSERT INTO invoices (company_id, client_id, quote_ref, reference, date, due_date, status, subtotal, tax, total, notes) VALUES (%s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + 14, 'Unpaid', 0, 0, 0, %s) RETURNING id", (comp_id, job[0], job[1], new_ref, f"From Job {job[1]}"))
        inv_id = cur.fetchone()[0]
        cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) VALUES (%s, %s, 1, 0, 0)", (inv_id, f"Work Completed: {job[2]}"))
        cur.execute("UPDATE jobs SET status = 'Invoiced' WHERE id = %s", (job_id,))
        conn.commit(); flash(f"✅ Invoice {new_ref} Generated!")
        return redirect(url_for('finance.finance_dashboard')) 
    except Exception as e: conn.rollback(); flash(f"❌ Error: {e}"); return redirect(url_for('office.office_dashboard'))
    finally: conn.close()

# --- 4. CREATE QUOTE ---
@office_bp.route('/office/quote/new', methods=['GET', 'POST'])
def create_quote():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,)); settings = {row[0]: row[1] for row in cur.fetchall()}
    if request.method == 'POST':
        try:
            client_id = request.form.get('client_id')
            if request.form.get('client_mode') == 'new':
                cur.execute("INSERT INTO clients (company_id, name, email, address, status) VALUES (%s, %s, %s, %s, 'Active') RETURNING id", (comp_id, request.form.get('new_client_name'), request.form.get('new_client_email'), request.form.get('new_client_address')))
                client_id = cur.fetchone()[0]
            cur.execute("INSERT INTO quotes (company_id, client_id, reference, status, notes, date) VALUES (%s, %s, %s, 'Draft', %s, CURRENT_DATE) RETURNING id", (comp_id, client_id, request.form.get('reference'), request.form.get('notes')))
            quote_id = cur.fetchone()[0]
            descs = request.form.getlist('desc[]'); qtys = request.form.getlist('qty[]'); prices = request.form.getlist('price[]'); sub = 0
            for i in range(len(descs)):
                if descs[i]:
                    tot = float(qtys[i]) * float(prices[i]); sub += tot
                    cur.execute("INSERT INTO quote_items (quote_id, description, quantity, unit_price, total) VALUES (%s, %s, %s, %s, %s)", (quote_id, descs[i], qtys[i], prices[i], tot))
            tax = sub * (float(settings.get('tax_rate', '20'))/100 if settings.get('vat_registered','no')=='yes' else 0)
            cur.execute("UPDATE quotes SET subtotal=%s, tax=%s, total=%s WHERE id=%s", (sub, tax, sub+tax, quote_id))
            conn.commit(); return redirect(url_for('office.view_quote', quote_id=quote_id))
        except: conn.rollback()
    cur.execute("SELECT COUNT(*) FROM quotes WHERE company_id = %s", (comp_id,)); count = cur.fetchone()[0]
    cur.execute("SELECT id, name FROM clients WHERE company_id = %s ORDER BY name", (comp_id,)); clients = cur.fetchall(); conn.close()
    return render_template('office/create_quote.html', clients=clients, new_ref=f"Q-{1000+count+1}", today=date.today(), tax_rate=0, settings=settings, brand_color=config['color'], logo_url=config['logo'])

# --- 5. VIEW QUOTE ---
@office_bp.route('/office/quote/<int:quote_id>')
def view_quote(quote_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT q.id, c.name, c.address, c.email, q.reference, q.date, q.status, q.subtotal, q.tax, q.total, q.notes FROM quotes q JOIN clients c ON q.client_id = c.id WHERE q.id = %s AND q.company_id = %s", (quote_id, comp_id))
    quote = cur.fetchone()
    if not quote: return redirect(url_for('office.office_dashboard'))
    cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,)); items = cur.fetchall()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,)); settings = {row[0]: row[1] for row in cur.fetchall()}
    settings['brand_color'] = config['color']; settings['logo_url'] = config['logo']
    if request.args.get('mode') == 'pdf': return render_template('office/pdf_quote.html', quote=quote, items=items, settings=settings)
    return render_template('office/view_quote_dashboard.html', quote=quote, items=items, settings=settings, staff=[])

# --- 6. CONVERT ACTIONS ---
@office_bp.route('/office/quote/<int:quote_id>/convert')
def convert_to_invoice(quote_id):
    return redirect(url_for('office.office_dashboard'))

@office_bp.route('/office/quote/convert-job', methods=['POST'])
def convert_quote_to_job():
    if not check_office_access(): return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO jobs (company_id, staff_id, client_id, start_date, description, status, ref) VALUES (%s, %s, %s, %s, %s, 'Scheduled', %s)", (session['company_id'], request.form.get('staff_id'), request.form.get('quote_id'), request.form.get('schedule_date'), f"Quote Work", f"Ref"))
        conn.commit(); flash(f"✅ Job Created!")
    except: conn.rollback()
    finally: conn.close()
    return redirect(url_for('office.office_dashboard'))

# --- 7. OFFICE FLEET (RESTRICTED + RECEIPTS) ---
@office_bp.route('/office/fleet', methods=['GET', 'POST'])
def fleet_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id) 
    conn = get_db(); cur = conn.cursor()
    
    # 1. NOW DEFINED: Get Dynamic Format
    date_fmt = get_date_fmt_str(comp_id)

    # 2. Ensure DB Schema
    cur.execute("CREATE TABLE IF NOT EXISTS vehicle_crew (vehicle_id INTEGER, staff_id INTEGER, PRIMARY KEY(vehicle_id, staff_id))")
    try:
        cur.execute("ALTER TABLE maintenance_logs ADD COLUMN IF NOT EXISTS receipt_path TEXT")
        conn.commit()
    except: conn.rollback()

    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'assign_crew':
                v_id = request.form.get('vehicle_id'); crew_ids = request.form.getlist('crew_ids')
                cur.execute("DELETE FROM vehicle_crew WHERE vehicle_id = %s", (v_id,))
                for staff_id in crew_ids: cur.execute("INSERT INTO vehicle_crew (vehicle_id, staff_id) VALUES (%s, %s)", (v_id, staff_id))
                flash("✅ Crew Updated")
                
            elif action == 'add_log':
                # Handle File Upload
                file_url = None
                if 'receipt_file' in request.files:
                    file = request.files['receipt_file']
                    if file and file.filename != '':
                        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                        filename = secure_filename(f"receipt_{comp_id}_{int(datetime.now().timestamp())}_{file.filename}")
                        file.save(os.path.join(UPLOAD_FOLDER, filename))
                        file_url = f"uploads/receipts/{filename}"

                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, type, description, date, cost, receipt_path) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (comp_id, request.form.get('vehicle_id'), request.form.get('log_type'), request.form.get('description'), request.form.get('date'), request.form.get('cost') or 0, file_url))
                flash("✅ Log & Receipt Added")
            
            # NOTE: 'add_vehicle' REMOVED to satisfy restriction
            
            conn.commit()
        except Exception as e: conn.rollback(); flash(f"Error: {e}")

    # Fetch Data
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
            'mot_expiry': parse_date(row[6]), # Keep Object for Math
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

# --- 8. SERVICE DESK ---
@office_bp.route('/office/service-desk')
def service_desk():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor(); date_fmt = get_date_fmt_str(comp_id)
    try: cur.execute("SELECT r.id, p.address_line1, r.issue_description, c.name, r.severity, r.status, r.created_at FROM service_requests r JOIN properties p ON r.property_id = p.id JOIN clients c ON r.client_id = c.id WHERE r.company_id = %s AND r.status != 'Completed' ORDER BY r.created_at DESC", (comp_id,))
    except: cur.execute("SELECT r.id, p.site_address, r.issue_description, c.name, r.severity, r.status, r.created_at FROM service_requests r JOIN properties p ON r.property_id = p.id JOIN clients c ON r.client_id = c.id WHERE r.company_id = %s AND r.status != 'Completed' ORDER BY r.created_at DESC", (comp_id,))
    rows = cur.fetchall(); requests_list = []
    for r in rows: requests_list.append({'id': r[0], 'property_address': r[1], 'issue_description': r[2], 'client_name': r[3], 'severity': r[4], 'status': r[5], 'date': format_date(r[6], date_fmt)}) 
    staff = get_staff_list(cur, comp_id); conn.close()
    return render_template('office/service_desk.html', requests=requests_list, staff=staff, brand_color=config['color'], logo_url=config['logo'])

@office_bp.route('/office/create-work-order', methods=['POST'])
def create_work_order():
    if not check_office_access(): return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("INSERT INTO jobs (company_id, client_id, staff_id, start_date, description, status) VALUES (%s, %s, %s, %s, %s, 'Scheduled')", (session['company_id'], request.form.get('client_id'), request.form.get('assigned_staff_id'), request.form.get('schedule_date'), request.form.get('job_type')))
    cur.execute("UPDATE service_requests SET status = 'In Progress' WHERE id = %s", (request.form.get('request_id'),))
    conn.commit(); conn.close(); return redirect(url_for('office.service_desk'))

# --- 9. STAFF ---
@office_bp.route('/office/staff', methods=['GET', 'POST'])
def staff_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); config = get_site_config(comp_id); conn = get_db(); cur = conn.cursor()
    if request.method == 'POST':
        cur.execute("INSERT INTO staff (company_id, name, email, phone, position, status) VALUES (%s, %s, %s, %s, %s, 'Active')", (comp_id, request.form.get('name'), request.form.get('email'), request.form.get('phone'), request.form.get('role')))
        conn.commit()
    cur.execute("SELECT id, name, email, phone, position AS role, status FROM staff WHERE company_id = %s ORDER BY name", (comp_id,)); cols = [desc[0] for desc in cur.description]; staff = [dict(zip(cols, row)) for row in cur.fetchall()]; conn.close()
    return render_template('office/staff_management.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

# --- 10. CALENDAR ---
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

@office_bp.route('/client/<int:client_id>')
def view_client(client_id): return "Client View Placeholder" 

@office_bp.route('/client/<int:client_id>/add_property', methods=['POST'])
def add_property(client_id): return redirect(url_for('office.view_client', client_id=client_id))