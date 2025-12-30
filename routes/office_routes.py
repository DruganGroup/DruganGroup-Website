from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from email_service import send_company_email

office_bp = Blueprint('office', __name__)

# Allowed roles for Office Hub
ALLOWED_OFFICE_ROLES = ['Admin', 'SuperAdmin', 'Office']

# --- HELPER: CHECK PERMISSION ---
def check_office_access():
    if 'user_id' not in session: return False
    if session.get('role') not in ALLOWED_OFFICE_ROLES: return False
    return True

# --- DASHBOARD ---
@office_bp.route('/office-hub')
@office_bp.route('/office-hub.html')
def office_dashboard():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    config = get_site_config(company_id)
    
    conn = get_db()
    cur = conn.cursor()
    
    # Financials
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,))
    income = cur.fetchone()[0] or 0.0
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Expense'", (company_id,))
    expense = cur.fetchone()[0] or 0.0
    
    # Recent Transactions
    cur.execute("SELECT id, date, type, category, description, amount, reference FROM transactions WHERE company_id = %s ORDER BY date DESC LIMIT 10", (company_id,))
    transactions = cur.fetchall()
    conn.close()

    return render_template('office/office_dashboard.html', 
                           total_income=income, total_expense=expense, transactions=transactions,
                           brand_color=config['color'], logo_url=config['logo'])

# --- SERVICE DESK ---
@office_bp.route('/office/service-desk')
def service_desk():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    
    conn = get_db()
    cur = conn.cursor()
    
    # Fetch Requests
    # Note: We filter by 'Active' status on staff to ensure we only dispatch to current employees
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
    
    # Fetch Staff for the Dispatch Dropdown
    # Uses the 'role' column you just added via the database fix
    cur.execute("SELECT id, name, role FROM staff WHERE company_id = %s AND status='Active'", (comp_id,))
    staff_members = [dict(zip(['id', 'name', 'role'], row)) for row in cur.fetchall()]
        
    conn.close()
    return render_template('office/service_desk.html', requests=requests_list, staff=staff_members, brand_color=config['color'], logo_url=config['logo'])

# --- DISPATCH LOGIC (Create Work Order) ---
@office_bp.route('/office/create-work-order', methods=['POST'])
def create_work_order():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    request_id = request.form.get('request_id')
    staff_id = request.form.get('assigned_staff_id')
    date = request.form.get('schedule_date')
    job_type = request.form.get('job_type')
    notes = request.form.get('admin_notes')
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO jobs (company_id, request_id, staff_id, scheduled_date, type, notes, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'Scheduled')
        """, (session['company_id'], request_id, staff_id, date, job_type, notes))
        
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
        # Add New Staff
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
            
    # View Staff
    cur.execute("SELECT * FROM staff WHERE company_id = %s ORDER BY name ASC", (comp_id,))
    cols = [desc[0] for desc in cur.description]
    staff = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
    
    return render_template('office/staff_management.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

# --- FLEET MANAGEMENT (CORRECTED COLUMNS) ---
@office_bp.route('/office/fleet', methods=['GET', 'POST'])
def fleet_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'POST':
        # Add New Vehicle
        # Mapping HTML Form names -> Database Column names
        reg = request.form.get('reg_number')       # DB: reg_plate
        model = request.form.get('make_model')     # DB: make_model
        driver = request.form.get('driver_id')     # DB: assigned_driver_id
        mot = request.form.get('mot_expiry')       # DB: mot_due
        
        try:
            # We use 'reg_plate' and 'assigned_driver_id' to match Finance DB
            cur.execute("""
                INSERT INTO vehicles (company_id, reg_plate, make_model, assigned_driver_id, mot_due, status) 
                VALUES (%s, %s, %s, %s, %s, 'Active')
            """, (comp_id, reg, model, driver if driver else None, mot))
            conn.commit()
            flash(f"✅ Vehicle {reg} Added.")
        except Exception as e:
            conn.rollback()
            flash(f"❌ Error: {e}")
            
    # View Fleet (Joined with Staff Name)
    # Mapping DB Columns -> Template Variables
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.status, v.mot_due, s.name as driver_name, v.assigned_driver_id 
        FROM vehicles v 
        LEFT JOIN staff s ON v.assigned_driver_id = s.id 
        WHERE v.company_id = %s
    """, (comp_id,))
    
    # We manually map these so the template doesn't break
    vehicles = []
    for row in cur.fetchall():
        vehicles.append({
            'id': row[0],
            'reg_number': row[1],      # Template expects reg_number
            'make_model': row[2],
            'status': row[3],
            'mot_expiry': row[4],      # Template expects mot_expiry
            'driver_name': row[5],
            'driver_id': row[6]
        })
    
    # Get Staff for Dropdown
    cur.execute("SELECT id, name FROM staff WHERE company_id = %s", (comp_id,))
    drivers = cur.fetchall()
    
    conn.close()
    
    return render_template('office/fleet_management.html', vehicles=vehicles, drivers=drivers, brand_color=config['color'], logo_url=config['logo'])

# --- SEND RECEIPT ---
@office_bp.route('/office/send-receipt/<int:transaction_id>')
def send_receipt(transaction_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    user_email = "client@example.com" # Placeholder
    
    subject = f"Receipt for Transaction #{transaction_id}"
    body = f"<h2>Transaction Receipt</h2><p>This is a confirmation for transaction #{transaction_id}.</p>"
    
    success, message = send_company_email(company_id, user_email, subject, body)
    
    if success: flash(f"✅ Email sent successfully to {user_email}!")
    else: flash(f"❌ Email Failed: {message}")
        
    return redirect(url_for('office.office_dashboard'))