from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from email_service import send_company_email
from datetime import datetime, date

office_bp = Blueprint('office', __name__)

# Allowed roles for Office Hub (STRICT - Does NOT include Site Manager)
ALLOWED_OFFICE_ROLES = ['Admin', 'SuperAdmin', 'Office']

# --- HELPER: CHECK PERMISSION ---
def check_office_access():
    if 'user_id' not in session: return False
    if session.get('role') not in ALLOWED_OFFICE_ROLES: return False
    return True

# --- HELPER: FORCE DATE OBJECT ---
def parse_date(d):
    """Converts string dates from DB into Python Date objects for math"""
    if isinstance(d, str):
        try:
            return datetime.strptime(d, '%Y-%m-%d').date()
        except:
            return None
    return d

# --- DASHBOARD ---
@office_bp.route('/office-hub')
@office_bp.route('/office-hub.html')
def office_dashboard():
    # Strict check: Site Managers cannot see this dashboard
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    config = get_site_config(company_id)
    
    conn = get_db()
    cur = conn.cursor()
    
    # 1. Ensure Quote Tables Exist (Run Once)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS quotes (
            id SERIAL PRIMARY KEY, company_id INTEGER, client_id INTEGER,
            date DATE DEFAULT CURRENT_DATE, reference TEXT, status TEXT DEFAULT 'Draft',
            subtotal DECIMAL(10,2), tax DECIMAL(10,2), total DECIMAL(10,2),
            notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS quote_items (
            id SERIAL PRIMARY KEY, quote_id INTEGER, description TEXT,
            quantity DECIMAL(10,2), unit_price DECIMAL(10,2), total DECIMAL(10,2),
            FOREIGN KEY (quote_id) REFERENCES quotes(id) ON DELETE CASCADE
        );
    """)
    conn.commit()

    # 2. Financials
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,))
    income = cur.fetchone()[0] or 0.0
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Expense'", (company_id,))
    expense = cur.fetchone()[0] or 0.0
    
    # 3. Recent Transactions
    cur.execute("SELECT id, date, type, category, description, amount, reference FROM transactions WHERE company_id = %s ORDER BY date DESC LIMIT 10", (company_id,))
    transactions = cur.fetchall()

    # 4. Recent Quotes (ADDED THIS SECTION)
    cur.execute("""
        SELECT q.id, c.name, q.reference, q.date, q.total, q.status 
        FROM quotes q LEFT JOIN clients c ON q.client_id = c.id
        WHERE q.company_id = %s ORDER BY q.id DESC LIMIT 10
    """, (company_id,))
    recent_quotes = cur.fetchall()

    conn.close()

    return render_template('office/office_dashboard.html', 
                           total_income=income, 
                           total_expense=expense, 
                           transactions=transactions,
                           quotes=recent_quotes, # Passed to template
                           brand_color=config['color'], 
                           logo_url=config['logo'])

# --- CREATE QUOTE (UPDATED WITH SMART CLIENT & PERMISSIONS) ---
@office_bp.route('/office/quote/new', methods=['GET', 'POST'])
def create_quote():
    # PERMISSION FIX: Allow Site Managers just for this route
    allowed_roles = ['Admin', 'SuperAdmin', 'Office', 'Site Manager']
    if session.get('role') not in allowed_roles: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    # Fetch Settings for VAT Logic
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings_rows = cur.fetchall()
    settings = {row[0]: row[1] for row in settings_rows}

    # Calculate Tax Rate
    if settings.get('vat_registered', 'no') == 'yes':
        tax_rate = float(settings.get('tax_rate', '20')) / 100
    else:
        tax_rate = 0.0

    if request.method == 'POST':
        try:
            # --- SMART CLIENT LOGIC START ---
            client_mode = request.form.get('client_mode')
            client_id = None

            if client_mode == 'existing':
                client_id = request.form.get('existing_client_id')
            elif client_mode == 'new':
                # Create Client Instantly
                new_name = request.form.get('new_client_name')
                new_email = request.form.get('new_client_email')
                new_address = request.form.get('new_client_address')
                cur.execute("""
                    INSERT INTO clients (company_id, name, email, address, status) 
                    VALUES (%s, %s, %s, %s, 'Active') RETURNING id
                """, (comp_id, new_name, new_email, new_address))
                client_id = cur.fetchone()[0]

            if not client_id: 
                # Fallback to standard dropdown if JS failed
                client_id = request.form.get('client_id') 

            if not client_id: raise Exception("No client selected.")
            # --- SMART CLIENT LOGIC END ---
            
            ref = request.form.get('reference')
            notes = request.form.get('notes')
            
            # Insert Header
            cur.execute("""
                INSERT INTO quotes (company_id, client_id, reference, status, notes, date)
                VALUES (%s, %s, %s, 'Draft', %s, CURRENT_DATE) RETURNING id
            """, (comp_id, client_id, ref, notes))
            quote_id = cur.fetchone()[0]
            
            # Process Line Items
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
            
            # Calculate Final Totals
            tax_amount = grand_subtotal * tax_rate
            final_total = grand_subtotal + tax_amount
            
            cur.execute("UPDATE quotes SET subtotal=%s, tax=%s, total=%s WHERE id=%s", (grand_subtotal, tax_amount, final_total, quote_id))
            conn.commit()
            
            flash(f"✅ Quote {ref} Created!")
            return redirect(url_for('office.view_quote', quote_id=quote_id))
            
        except Exception as e: conn.rollback(); flash(f"Error: {e}")
            
    # GET Request: Prepare Form
    cur.execute("SELECT COUNT(*) FROM quotes WHERE company_id = %s", (comp_id,))
    count = cur.fetchone()[0]
    new_ref = f"Q-{1000 + count + 1}"
    
    # Get Clients
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

# --- SERVICE DESK ---
@office_bp.route('/office/service-desk')
def service_desk():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT r.id, p.address, r.issue_description, c.name, r.severity, r.status, r.created_at
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

# --- DISPATCH LOGIC ---
@office_bp.route('/office/create-work-order', methods=['POST'])
def create_work_order():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    request_id = request.form.get('request_id')
    staff_id = request.form.get('assigned_staff_id')
    date_val = request.form.get('schedule_date')
    job_type = request.form.get('job_type')
    notes = request.form.get('admin_notes')
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO jobs (company_id, request_id, staff_id, scheduled_date, type, notes, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'Scheduled')
        """, (session['company_id'], request_id, staff_id, date_val, job_type, notes))
        
        cur.execute("UPDATE service_requests SET status = 'In Progress' WHERE id = %s", (request_id,))
        conn.commit()
        flash("✅ Work Order Created & Dispatched!")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}")
    finally:
        conn.close()
    return redirect(url_for('office.service_desk'))

# --- STAFF MANAGEMENT ---
@office_bp.route('/office/staff', methods=['GET', 'POST'])
def staff_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        role = request.form.get('role')
        
        try:
            cur.execute("INSERT INTO staff (company_id, name, email, phone, role, status) VALUES (%s, %s, %s, %s, %s, 'Active')", 
                        (comp_id, name, email, phone, role))
            conn.commit()
            flash(f"✅ Staff Member {name} Added.")
        except Exception as e:
            conn.rollback()
            flash(f"❌ Error: {e}")
            
    cur.execute("SELECT * FROM staff WHERE company_id = %s ORDER BY name ASC", (comp_id,))
    cols = [desc[0] for desc in cur.description]
    staff = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
    
    return render_template('office/staff_management.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

# --- FLEET MANAGEMENT (FULL DASHBOARD) ---
@office_bp.route('/office/fleet', methods=['GET', 'POST'])
def fleet_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    # --- HANDLE FORM SUBMISSIONS ---
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_vehicle':
            reg = request.form.get('reg_number')
            model = request.form.get('make_model')
            driver = request.form.get('driver_id')
            mot = request.form.get('mot_expiry')
            tax = request.form.get('tax_due')
            ins = request.form.get('insurance_due')
            serv = request.form.get('service_due')
            tracker = request.form.get('tracker_url')
            cost = request.form.get('daily_cost') or 0
            
            try:
                cur.execute("""
                    INSERT INTO vehicles (company_id, reg_plate, make_model, assigned_driver_id, mot_due, tax_due, insurance_due, service_due, tracker_url, daily_cost, status) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Active')
                """, (comp_id, reg, model, driver if driver else None, mot, tax, ins, serv, tracker, cost))
                conn.commit()
                flash(f"✅ Vehicle {reg} Added.")
            except Exception as e:
                conn.rollback(); flash(f"❌ Error: {e}")

        elif action == 'assign_crew':
            vehicle_id = request.form.get('vehicle_id')
            crew_ids = request.form.getlist('crew_ids')
            try:
                cur.execute("DELETE FROM vehicle_crews WHERE vehicle_id = %s", (vehicle_id,))
                for s_id in crew_ids:
                    cur.execute("INSERT INTO vehicle_crews (company_id, vehicle_id, staff_id) VALUES (%s, %s, %s)", (comp_id, vehicle_id, s_id))
                conn.commit()
                flash("✅ Gang Assigned Successfully")
            except Exception as e:
                conn.rollback(); flash(f"❌ Error: {e}")

        elif action == 'add_log': 
            v_id = request.form.get('vehicle_id')
            l_type = request.form.get('log_type')
            desc = request.form.get('description')
            log_date = request.form.get('date')
            cost = request.form.get('cost') or 0
            try:
                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, type, description, date, cost)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (comp_id, v_id, l_type, desc, log_date, cost))
                conn.commit()
                flash("✅ Maintenance Record Added")
            except Exception as e:
                conn.rollback(); flash(f"❌ Error: {e}")
                
        elif action == 'update_defects': 
            v_id = request.form.get('vehicle_id')
            notes = request.form.get('defect_notes')
            tracker = request.form.get('tracker_url')
            try:
                cur.execute("UPDATE vehicles SET defect_notes = %s, tracker_url = %s WHERE id = %s", (notes, tracker, v_id))
                conn.commit()
                flash("✅ Vehicle Details Updated")
            except Exception as e:
                conn.rollback(); flash(f"❌ Error: {e}")

    # --- FETCH FLEET DATA ---
    cur.execute("""
        SELECT 
            v.id, v.reg_plate, v.make_model, v.status, 
            v.mot_due, v.tax_due, v.insurance_due, v.service_due, 
            v.tracker_url, v.defect_notes,
            s.name as driver_name, v.assigned_driver_id, 
            COALESCE(v.daily_cost, 0) as van_cost,
            COALESCE(s.pay_rate, 0) as driver_cost
        FROM vehicles v 
        LEFT JOIN staff s ON v.assigned_driver_id = s.id 
        WHERE v.company_id = %s
        ORDER BY v.reg_plate
    """, (comp_id,))
    
    raw_vehicles = cur.fetchall()
    vehicles = []
    
    today = date.today()

    for row in raw_vehicles:
        v_id = row[0]
        
        # 1. Fetch Maintenance History
        cur.execute("SELECT date, type, description, cost FROM maintenance_logs WHERE vehicle_id = %s ORDER BY date DESC", (v_id,))
        history = [{'date': r[0], 'type': r[1], 'desc': r[2], 'cost': r[3]} for r in cur.fetchall()]
        
        # 2. Fetch Crew
        cur.execute("""
            SELECT s.id, s.name, s.role, COALESCE(s.pay_rate, 0)
            FROM vehicle_crews vc
            JOIN staff s ON vc.staff_id = s.id
            WHERE vc.vehicle_id = %s
        """, (v_id,))
        crew = cur.fetchall()
        
        crew_list = []
        crew_total_cost = 0
        for c in crew:
            crew_list.append({'name': c[1], 'role': c[2]})
            crew_total_cost += float(c[3])
            
        # 3. Cost Calc
        labor_cost = (float(row[13]) + crew_total_cost) * 8 
        total_day_cost = float(row[12]) + labor_cost

        # 4. BUILD OBJECT & PARSE DATES
        vehicles.append({
            'id': row[0],
            'reg_number': row[1], 'make_model': row[2], 'status': row[3],
            'mot_expiry': parse_date(row[4]),
            'tax_expiry': parse_date(row[5]),
            'ins_expiry': parse_date(row[6]),
            'service_due': parse_date(row[7]),
            'tracker_url': row[8], 'defect_notes': row[9],
            'driver_name': row[10], 'driver_id': row[11],
            'daily_cost': row[12],
            'crew': crew_list,
            'total_gang_cost': total_day_cost,
            'history': history
        })
    
    cur.execute("SELECT id, name, role FROM staff WHERE company_id = %s AND status='Active'", (comp_id,))
    all_staff = [dict(zip(['id', 'name', 'role'], row)) for row in cur.fetchall()]
    
    conn.close()
    
    return render_template('office/fleet_management.html', vehicles=vehicles, staff=all_staff, today=today, brand_color=config['color'], logo_url=config['logo'])

# --- SEND RECEIPT ---
@office_bp.route('/office/send-receipt/<int:transaction_id>')
def send_receipt(transaction_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    user_email = "client@example.com"
    
    subject = f"Receipt for Transaction #{transaction_id}"
    body = f"<h2>Transaction Receipt</h2><p>This is a confirmation for transaction #{transaction_id}.</p>"
    
    success, message = send_company_email(company_id, user_email, subject, body)
    
    if success: flash(f"✅ Email sent successfully to {user_email}!")
    else: flash(f"❌ Email Failed: {message}")
        
    return redirect(url_for('office.office_dashboard'))
    
# --- 3. VIEW QUOTE (UPDATED PERMISSIONS) ---
@office_bp.route('/office/quote/<int:quote_id>')
def view_quote(quote_id):
    # PERMISSION FIX: Allow Site Managers just for this route
    allowed_roles = ['Admin', 'SuperAdmin', 'Office', 'Site Manager']
    if session.get('role') not in allowed_roles: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id) # Gets logo & color
    conn = get_db(); cur = conn.cursor()

    # 1. Fetch Quote Header
    cur.execute("""
        SELECT q.id, c.name, c.address, c.email, q.reference, q.date, q.status, 
               q.subtotal, q.tax, q.total, q.notes
        FROM quotes q 
        JOIN clients c ON q.client_id = c.id
        WHERE q.id = %s AND q.company_id = %s
    """, (quote_id, comp_id))
    quote = cur.fetchone()

    if not quote:
        return "Quote not found or access denied", 404

    # 2. Fetch Line Items
    cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
    items = cur.fetchall()

    # 3. Fetch Company Settings (To know which Template Style to use)
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    # Merge basic config (logo/color) into settings for easier access in template
    settings['brand_color'] = config['color']
    settings['logo_url'] = config['logo']

    conn.close()

    # 4. Mode Switch: Are we viewing the Dashboard Wrapper or the raw PDF?
    mode = request.args.get('mode')
    
    if mode == 'pdf':
        # Render the actual document (Print View)
        return render_template('office/pdf_quote.html', quote=quote, items=items, settings=settings)
    else:
        # Render the Dashboard Wrapper (Buttons + Iframe)
        return render_template('office/view_quote_dashboard.html', quote=quote, settings=settings)
        
        # --- 4. CONVERT QUOTE TO INVOICE ---
@office_bp.route('/office/quote/<int:quote_id>/convert')
def convert_to_invoice(quote_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    # 1. Fetch Quote Data
    cur.execute("SELECT client_id, reference, subtotal, tax, total, notes FROM quotes WHERE id = %s AND company_id = %s", (quote_id, comp_id))
    quote = cur.fetchone()
    
    if not quote: return "Quote not found", 404
    
    # 2. Check if already converted
    cur.execute("SELECT id FROM invoices WHERE quote_ref = %s AND company_id = %s", (quote[1], comp_id))
    if cur.fetchone():
        flash("⚠️ This quote has already been converted to an invoice.")
        return redirect(url_for('office.view_quote', quote_id=quote_id))

    # 3. Generate New Invoice Reference (INV-1001, etc.)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id SERIAL PRIMARY KEY, company_id INTEGER, client_id INTEGER, quote_ref TEXT,
            reference TEXT, date DATE DEFAULT CURRENT_DATE, due_date DATE,
            status TEXT DEFAULT 'Unpaid', subtotal DECIMAL(10,2), tax DECIMAL(10,2), total DECIMAL(10,2),
            notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoice_items (
            id SERIAL PRIMARY KEY, invoice_id INTEGER, description TEXT,
            quantity DECIMAL(10,2), unit_price DECIMAL(10,2), total DECIMAL(10,2),
            FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        );
    """)
    
    cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id = %s", (comp_id,))
    count = cur.fetchone()[0]
    new_inv_ref = f"INV-{1000 + count + 1}"

    # 4. Insert Invoice Header
    # Default due date = Today + 14 days (You can change this logic later)
    cur.execute("""
        INSERT INTO invoices (company_id, client_id, quote_ref, reference, date, due_date, status, subtotal, tax, total, notes)
        VALUES (%s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + 14, 'Unpaid', %s, %s, %s, %s)
        RETURNING id
    """, (comp_id, quote[0], quote[1], new_inv_ref, quote[2], quote[3], quote[4], quote[5]))
    inv_id = cur.fetchone()[0]

    # 5. Copy Line Items
    cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
    items = cur.fetchall()
    
    for item in items:
        cur.execute("""
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
            VALUES (%s, %s, %s, %s, %s)
        """, (inv_id, item[0], item[1], item[2], item[3]))

    # 6. Mark Quote as Accepted
    cur.execute("UPDATE quotes SET status = 'Accepted' WHERE id = %s", (quote_id,))
    
    conn.commit()
    conn.close()
    
    flash(f"✅ Quote Converted! Invoice {new_inv_ref} Created.")
    # For now, we redirect back to the quote, or we can build an Invoice View next.
    return redirect(url_for('office.office_dashboard'))