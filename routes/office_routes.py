from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify
from db import get_db, get_site_config
from email_service import send_company_email
from datetime import datetime, date

office_bp = Blueprint('office', __name__)

# Allowed roles for Office Hub
ALLOWED_OFFICE_ROLES = ['Admin', 'SuperAdmin', 'Office']

# --- HELPER: CHECK PERMISSION ---
def check_office_access():
    if 'user_id' not in session: return False
    if session.get('role') not in ALLOWED_OFFICE_ROLES: return False
    return True

# --- HELPER: FORCE DATE OBJECT ---
def parse_date(d):
    if isinstance(d, str):
        try:
            return datetime.strptime(d, '%Y-%m-%d').date()
        except:
            return None
    return d

# --- 1. OFFICE DASHBOARD (OPERATIONAL) ---
@office_bp.route('/office-hub')
@office_bp.route('/office-hub.html')
def office_dashboard():
    # Strict check: Site Managers cannot see this dashboard
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    config = get_site_config(company_id)
    
    conn = get_db()
    cur = conn.cursor()
    
    # STAT 1: New Service Requests (Operational Focus)
    cur.execute("SELECT COUNT(*) FROM service_requests WHERE company_id = %s AND status != 'Completed'", (company_id,))
    pending_requests_count = cur.fetchone()[0]

    # STAT 2: Active Jobs Count
    cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id = %s AND status != 'Completed'", (company_id,))
    active_jobs_count = cur.fetchone()[0]

    # STAT 3: Pending Quotes List
    cur.execute("""
        SELECT q.id, c.name, q.reference, q.date, q.total, q.status 
        FROM quotes q LEFT JOIN clients c ON q.client_id = c.id
        WHERE q.company_id = %s AND q.status = 'Draft'
        ORDER BY q.id DESC LIMIT 10
    """, (company_id,))
    recent_quotes = cur.fetchall()

    conn.close()

    return render_template('office/office_dashboard.html', 
                           pending_requests_count=pending_requests_count,
                           active_jobs_count=active_jobs_count, 
                           quotes=recent_quotes,
                           brand_color=config['color'], 
                           logo_url=config['logo'])

# --- 2. CREATE QUOTE ---
@office_bp.route('/office/quote/new', methods=['GET', 'POST'])
def create_quote():
    allowed_roles = ['Admin', 'SuperAdmin', 'Office', 'Site Manager']
    if session.get('role') not in allowed_roles: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}

    if settings.get('vat_registered', 'no') == 'yes':
        tax_rate = float(settings.get('tax_rate', '20')) / 100
    else:
        tax_rate = 0.0

    if request.method == 'POST':
        try:
            client_mode = request.form.get('client_mode')
            client_id = None

            if client_mode == 'existing':
                client_id = request.form.get('existing_client_id')
            elif client_mode == 'new':
                new_name = request.form.get('new_client_name')
                new_email = request.form.get('new_client_email')
                new_address = request.form.get('new_client_address')
                cur.execute("""
                    INSERT INTO clients (company_id, name, email, address, status) 
                    VALUES (%s, %s, %s, %s, 'Active') RETURNING id
                """, (comp_id, new_name, new_email, new_address))
                client_id = cur.fetchone()[0]

            if not client_id: client_id = request.form.get('client_id') 
            if not client_id: raise Exception("No client selected.")

            ref = request.form.get('reference')
            notes = request.form.get('notes')
            
            cur.execute("""
                INSERT INTO quotes (company_id, client_id, reference, status, notes, date)
                VALUES (%s, %s, %s, 'Draft', %s, CURRENT_DATE) RETURNING id
            """, (comp_id, client_id, ref, notes))
            quote_id = cur.fetchone()[0]
            
            descriptions = request.form.getlist('desc[]')
            quantities = request.form.getlist('qty[]')
            prices = request.form.getlist('price[]')
            
            grand_subtotal = 0
            
            for i in range(len(descriptions)):
                if descriptions[i]: 
                    d = descriptions[i]
                    q = float(quantities[i]) if quantities[i] else 0
                    p = float(prices[i]) if prices[i] else 0
                    row_total = q * p
                    grand_subtotal += row_total
                    
                    cur.execute("""
                        INSERT INTO quote_items (quote_id, description, quantity, unit_price, total) 
                        VALUES (%s, %s, %s, %s, %s)
                    """, (quote_id, d, q, p, row_total))
            
            tax_amount = grand_subtotal * tax_rate
            final_total = grand_subtotal + tax_amount
            
            cur.execute("UPDATE quotes SET subtotal=%s, tax=%s, total=%s WHERE id=%s", (grand_subtotal, tax_amount, final_total, quote_id))
            conn.commit()
            
            flash(f"✅ Quote {ref} Created!")
            return redirect(url_for('office.view_quote', quote_id=quote_id))
            
        except Exception as e: conn.rollback(); flash(f"Error: {e}")
            
    cur.execute("SELECT COUNT(*) FROM quotes WHERE company_id = %s", (comp_id,))
    count = cur.fetchone()[0]
    new_ref = f"Q-{1000 + count + 1}"
    
    cur.execute("SELECT id, name FROM clients WHERE company_id = %s ORDER BY name", (comp_id,))
    clients = cur.fetchall()
    
    conn.close()
    return render_template('office/create_quote.html', 
                           clients=clients, 
                           new_ref=new_ref, 
                           today=date.today(), 
                           tax_rate=tax_rate, 
                           settings=settings,
                           brand_color=config['color'], 
                           logo_url=config['logo'])

# --- 3. VIEW QUOTE ---
@office_bp.route('/office/quote/<int:quote_id>')
def view_quote(quote_id):
    allowed_roles = ['Admin', 'SuperAdmin', 'Office', 'Site Manager']
    if session.get('role') not in allowed_roles: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    cur.execute("""
        SELECT q.id, c.name, c.address, c.email, q.reference, q.date, q.status, 
               q.subtotal, q.tax, q.total, q.notes
        FROM quotes q 
        JOIN clients c ON q.client_id = c.id
        WHERE q.id = %s AND q.company_id = %s
    """, (quote_id, comp_id))
    quote = cur.fetchone()

    if not quote: return "Quote not found or access denied", 404

    cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
    items = cur.fetchall()

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    settings['brand_color'] = config['color']
    settings['logo_url'] = config['logo']
    
    # ADDED: Get Staff list for "Approve & Schedule" Modal
    cur.execute("SELECT id, name, role FROM staff WHERE company_id = %s", (comp_id,))
    staff_list = [dict(zip(['id', 'name', 'role'], row)) for row in cur.fetchall()]

    conn.close()

    mode = request.args.get('mode')
    if mode == 'pdf':
        return render_template('office/pdf_quote.html', quote=quote, items=items, settings=settings)
    else:
        # Pass staff list to template
        return render_template('office/view_quote_dashboard.html', quote=quote, items=items, settings=settings, staff=staff_list)

# --- 4. CONVERT QUOTE TO INVOICE ---
@office_bp.route('/office/quote/<int:quote_id>/convert')
def convert_to_invoice(quote_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    cur.execute("SELECT client_id, reference, subtotal, tax, total, notes FROM quotes WHERE id = %s AND company_id = %s", (quote_id, comp_id))
    quote = cur.fetchone()
    
    if not quote: return "Quote not found", 404
    
    cur.execute("SELECT id FROM invoices WHERE quote_ref = %s AND company_id = %s", (quote[1], comp_id))
    if cur.fetchone():
        flash("⚠️ This quote has already been converted to an invoice.")
        return redirect(url_for('office.view_quote', quote_id=quote_id))

    cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id = %s", (comp_id,))
    count = cur.fetchone()[0]
    new_inv_ref = f"INV-{1000 + count + 1}"

    cur.execute("""
        INSERT INTO invoices (company_id, client_id, quote_ref, reference, date, due_date, status, subtotal, tax, total, notes)
        VALUES (%s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + 14, 'Unpaid', %s, %s, %s, %s)
        RETURNING id
    """, (comp_id, quote[0], quote[1], new_inv_ref, quote[2], quote[3], quote[4], quote[5]))
    inv_id = cur.fetchone()[0]

    cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
    items = cur.fetchall()
    
    for item in items:
        cur.execute("""
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
            VALUES (%s, %s, %s, %s, %s)
        """, (inv_id, item[0], item[1], item[2], item[3]))

    cur.execute("UPDATE quotes SET status = 'Accepted' WHERE id = %s", (quote_id,))
    conn.commit(); conn.close()
    
    flash(f"✅ Quote Converted! Invoice {new_inv_ref} Created.")
    return redirect(url_for('office.office_dashboard'))

# --- 5. CONVERT QUOTE TO JOB ---
@office_bp.route('/office/quote/convert-job', methods=['POST'])
def convert_quote_to_job():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    quote_id = request.form.get('quote_id')
    staff_id = request.form.get('staff_id')
    schedule_date = request.form.get('schedule_date')
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT client_id, reference, notes FROM quotes WHERE id = %s", (quote_id,))
        quote = cur.fetchone()
        
        # FIX: 'date' instead of 'scheduled_date'
        cur.execute("""
            INSERT INTO jobs (company_id, staff_id, client_id, date, type, status, reference, notes)
            VALUES (%s, %s, %s, %s, 'Quote Work', 'Scheduled', %s, %s)
        """, (session['company_id'], staff_id, quote[0], schedule_date, f"Ref: {quote[1]}", quote[2]))
        
        cur.execute("UPDATE quotes SET status = 'Converted' WHERE id = %s", (quote_id,))
        conn.commit()
        flash(f"✅ Job Created from Quote {quote[1]}!")
    except Exception as e:
        conn.rollback(); flash(f"❌ Error: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('office.office_dashboard'))

# --- 6. SERVICE DESK (FIXED) ---
@office_bp.route('/office/service-desk')
def service_desk():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    # !!! FIX: Changed 'p.address' to 'p.addr' !!!
    cur.execute("""
        SELECT r.id, p.addr, r.issue_description, c.name, r.severity, r.status, r.created_at
        FROM service_requests r
        JOIN properties p ON r.property_id = p.id
        JOIN clients c ON r.client_id = c.id
        WHERE r.company_id = %s AND r.status != 'Completed'
        ORDER BY r.created_at DESC
    """, (comp_id,))
    
    rows = cur.fetchall()
    requests_list = []
    for r in rows:
        requests_list.append({
            'id': r[0], 'property_address': r[1], 'issue_description': r[2],
            'client_name': r[3], 'severity': r[4], 'status': r[5], 'date': r[6]
        })
    
    cur.execute("SELECT id, name, role FROM staff WHERE company_id = %s AND status='Active'", (comp_id,))
    staff_members = [dict(zip(['id', 'name', 'role'], row)) for row in cur.fetchall()]
        
    conn.close()
    return render_template('office/service_desk.html', requests=requests_list, staff=staff_members, brand_color=config['color'], logo_url=config['logo'])

# --- 7. DISPATCH WORK ORDER ---
@office_bp.route('/office/create-work-order', methods=['POST'])
def create_work_order():
    if not check_office_access(): return redirect(url_for('auth.login'))
    request_id = request.form.get('request_id')
    staff_id = request.form.get('assigned_staff_id')
    date_val = request.form.get('schedule_date')
    job_type = request.form.get('job_type')
    notes = request.form.get('admin_notes')
    
    conn = get_db(); cur = conn.cursor()
    try:
        # FIX: 'date' instead of 'scheduled_date'
        cur.execute("""
            INSERT INTO jobs (company_id, request_id, staff_id, date, type, notes, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'Scheduled')
        """, (session['company_id'], request_id, staff_id, date_val, job_type, notes))
        cur.execute("UPDATE service_requests SET status = 'In Progress' WHERE id = %s", (request_id,))
        conn.commit(); flash("✅ Work Order Created & Dispatched!")
    except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")
    finally: conn.close()
    return redirect(url_for('office.service_desk'))

# --- 8. STAFF MANAGEMENT ---
@office_bp.route('/office/staff', methods=['GET', 'POST'])
def staff_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    if request.method == 'POST':
        name = request.form.get('name'); email = request.form.get('email')
        phone = request.form.get('phone'); role = request.form.get('role')
        try:
            cur.execute("INSERT INTO staff (company_id, name, email, phone, role, status) VALUES (%s, %s, %s, %s, %s, 'Active')", 
                        (comp_id, name, email, phone, role))
            conn.commit(); flash(f"✅ Staff Member {name} Added.")
        except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")
            
    cur.execute("SELECT * FROM staff WHERE company_id = %s ORDER BY name ASC", (comp_id,))
    cols = [desc[0] for desc in cur.description]
    staff = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
    return render_template('office/staff_management.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

# --- 9. FLEET MANAGEMENT (FIXED) ---
@office_bp.route('/office/fleet', methods=['GET', 'POST'])
def fleet_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    # --- HANDLE FORM SUBMISSIONS ---
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_vehicle':
            try:
                cur.execute("""
                    INSERT INTO vehicles (company_id, reg_plate, make_model, assigned_driver_id, mot_due, tax_due, insurance_due, service_due, tracker_url, daily_cost, status) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Active')
                """, (comp_id, request.form.get('reg_number'), request.form.get('make_model'), request.form.get('driver_id') or None, 
                      request.form.get('mot_expiry'), request.form.get('tax_due'), request.form.get('insurance_due'), 
                      request.form.get('service_due'), request.form.get('tracker_url'), request.form.get('daily_cost') or 0))
                conn.commit(); flash(f"✅ Vehicle Added.")
            except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")

        elif action == 'assign_crew':
            try:
                cur.execute("DELETE FROM vehicle_crews WHERE vehicle_id = %s", (request.form.get('vehicle_id'),))
                for s_id in request.form.getlist('crew_ids'):
                    cur.execute("INSERT INTO vehicle_crews (company_id, vehicle_id, staff_id) VALUES (%s, %s, %s)", (comp_id, request.form.get('vehicle_id'), s_id))
                conn.commit(); flash("✅ Gang Assigned")
            except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")

        elif action == 'add_log': 
            try:
                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, type, description, date, cost)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (comp_id, request.form.get('vehicle_id'), request.form.get('log_type'), request.form.get('description'), request.form.get('date'), request.form.get('cost') or 0))
                conn.commit(); flash("✅ Maintenance Record Added")
            except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")
                
        elif action == 'update_defects': 
            try:
                cur.execute("UPDATE vehicles SET defect_notes = %s, tracker_url = %s WHERE id = %s", (request.form.get('defect_notes'), request.form.get('tracker_url'), request.form.get('vehicle_id')))
                conn.commit(); flash("✅ Vehicle Details Updated")
            except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")

    # --- FETCH FLEET DATA (FIXED QUERY) ---
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.status, v.mot_due, v.tax_due, v.insurance_due, v.service_due, 
               v.tracker_url, v.defect_notes, s.name, v.assigned_driver_id, 
               COALESCE(v.daily_cost, 0), 
               COALESCE(s.pay_rate, 0) 
        FROM vehicles v 
        LEFT JOIN staff s ON v.assigned_driver_id = s.id 
        WHERE v.company_id = %s 
        ORDER BY v.reg_plate
    """, (comp_id,))
    
    raw_vehicles = cur.fetchall()
    vehicles = []
    
    for row in raw_vehicles:
        # 1. Fetch Maintenance History
        cur.execute("SELECT date, type, description, cost FROM maintenance_logs WHERE vehicle_id = %s ORDER BY date DESC", (row[0],))
        history = [{'date': r[0], 'type': r[1], 'desc': r[2], 'cost': r[3]} for r in cur.fetchall()]
        
        # 2. Fetch Crew
        cur.execute("""
            SELECT s.id, s.name, s.role, COALESCE(s.pay_rate, 0)
            FROM vehicle_crews vc
            JOIN staff s ON vc.staff_id = s.id
            WHERE vc.vehicle_id = %s
        """, (row[0],))
        crew = []
        crew_total_cost = 0
        for c in cur.fetchall():
            crew.append({'name': c[1], 'role': c[2]})
            crew_total_cost += float(c[3])
            
        # 3. Cost Calc (Safe access because query asks for 14 columns)
        labor_cost = (float(row[13]) + crew_total_cost) * 8 
        total_day_cost = float(row[12]) + labor_cost

        vehicles.append({
            'id': row[0], 'reg_number': row[1], 'make_model': row[2], 'status': row[3],
            'mot_expiry': parse_date(row[4]), 'tax_expiry': parse_date(row[5]),
            'ins_expiry': parse_date(row[6]), 'service_due': parse_date(row[7]),
            'tracker_url': row[8], 'defect_notes': row[9], 'driver_name': row[10],
            'daily_cost': row[12], 'crew': crew, 'history': history,
            'total_gang_cost': total_day_cost
        })
    
    cur.execute("SELECT id, name, role FROM staff WHERE company_id = %s AND status='Active'", (comp_id,))
    all_staff = [dict(zip(['id', 'name', 'role'], row)) for row in cur.fetchall()]
    
    conn.close()
    return render_template('office/fleet_management.html', vehicles=vehicles, staff=all_staff, today=date.today(), brand_color=config['color'], logo_url=config['logo'])

# --- 10. MASTER CALENDAR VIEW ---
@office_bp.route('/office/calendar')
def office_calendar():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    return render_template('office/calendar.html', brand_color=config['color'], logo_url=config['logo'])

# --- 11. CALENDAR DATA FEED (JSON) ---
@office_bp.route('/office/calendar/data')
def get_calendar_data():
    if not check_office_access(): return jsonify([])
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    events = []

    # A. Fetch JOBS
    try:
        # FIX: 'date' instead of 'scheduled_date'
        cur.execute("""
            SELECT j.id, j.ref, j.date, c.name, j.status
            FROM jobs j 
            LEFT JOIN clients c ON j.client_id = c.id
            WHERE j.company_id = %s AND j.date IS NOT NULL
        """, (comp_id,))
        jobs = cur.fetchall()
        for j in jobs:
            events.append({
                'title': f"{j[1]} - {j[3] or 'Client'}", 
                'start': str(j[2]),
                'color': '#28a745' if j[4] == 'Completed' else '#0d6efd',
                'url': f"/site/job/{j[0]}",
                'allDay': True
            })
    except Exception as e: print(f"Calendar Job Error: {e}")

    # B. Fetch VEHICLE DATES
    try:
        cur.execute("SELECT reg_plate, mot_due, tax_due, insurance_due, service_due FROM vehicles WHERE company_id = %s", (comp_id,))
        vehicles = cur.fetchall()
        for v in vehicles:
            reg = v[0]
            if v[1]: events.append({'title': f"MOT Due: {reg}", 'start': str(v[1]), 'color': '#dc3545', 'allDay': True})
            if v[2]: events.append({'title': f"Tax Due: {reg}", 'start': str(v[2]), 'color': '#ffc107', 'textColor': 'black', 'allDay': True})
            if v[3]: events.append({'title': f"Ins Due: {reg}", 'start': str(v[3]), 'color': '#fd7e14', 'allDay': True})
            if v[4]: events.append({'title': f"Service: {reg}", 'start': str(v[4]), 'color': '#6f42c1', 'allDay': True})
    except Exception as e: print(f"Calendar Fleet Error: {e}")

    conn.close()
    return jsonify(events)
    
# --- SEND RECEIPT (RESTORED) ---
@office_bp.route('/office/send-receipt/<int:transaction_id>')
def send_receipt(transaction_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    # In a real app, you would fetch the client email from the transaction
    user_email = "client@example.com" 
    
    subject = f"Receipt for Transaction #{transaction_id}"
    body = f"<h2>Transaction Receipt</h2><p>This is a confirmation for transaction #{transaction_id}.</p>"
    
    success, message = send_company_email(company_id, user_email, subject, body)
    
    if success: flash(f"✅ Email sent successfully to {user_email}!")
    else: flash(f"❌ Email Failed: {message}")
        
    return redirect(url_for('office.office_dashboard'))