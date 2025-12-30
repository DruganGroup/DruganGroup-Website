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

        elif action == 'add_log': # Add Service/Repair Record
            v_id = request.form.get('vehicle_id')
            l_type = request.form.get('log_type')
            desc = request.form.get('description')
            date = request.form.get('date')
            cost = request.form.get('cost') or 0
            try:
                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, type, description, date, cost)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (comp_id, v_id, l_type, desc, date, cost))
                conn.commit()
                flash("✅ Maintenance Record Added")
            except Exception as e:
                conn.rollback(); flash(f"❌ Error: {e}")
                
        elif action == 'update_defects': # Update Notes/Tracker
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
    
    from datetime import date # Need this for date calculations
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

        vehicles.append({
            'id': row[0],
            'reg_number': row[1], 'make_model': row[2], 'status': row[3],
            'mot_expiry': row[4], 'tax_expiry': row[5], 'ins_expiry': row[6], 'service_due': row[7],
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
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    # --- HANDLE CREW ASSIGNMENT ---
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_vehicle':
            # (Your existing add vehicle code...)
            reg = request.form.get('reg_number')
            model = request.form.get('make_model')
            driver = request.form.get('driver_id')
            mot = request.form.get('mot_expiry')
            cost = request.form.get('daily_cost') or 0
            try:
                cur.execute("""
                    INSERT INTO vehicles (company_id, reg_plate, make_model, assigned_driver_id, mot_due, daily_cost, status) 
                    VALUES (%s, %s, %s, %s, %s, %s, 'Active')
                """, (comp_id, reg, model, driver if driver else None, mot, cost))
                conn.commit()
                flash(f"✅ Vehicle {reg} Added.")
            except Exception as e:
                conn.rollback(); flash(f"❌ Error: {e}")

        elif action == 'assign_crew':
            vehicle_id = request.form.get('vehicle_id')
            crew_ids = request.form.getlist('crew_ids') # List of selected staff
            
            try:
                # 1. Clear existing crew for this vehicle
                cur.execute("DELETE FROM vehicle_crews WHERE vehicle_id = %s", (vehicle_id,))
                
                # 2. Add new crew
                for s_id in crew_ids:
                    cur.execute("INSERT INTO vehicle_crews (company_id, vehicle_id, staff_id) VALUES (%s, %s, %s)", (comp_id, vehicle_id, s_id))
                
                conn.commit()
                flash("✅ Gang Assigned Successfully")
            except Exception as e:
                conn.rollback(); flash(f"❌ Error: {e}")

    # --- FETCH FLEET DATA WITH COSTS ---
    # We join everything to calculate the daily cost dynamically
    cur.execute("""
        SELECT 
            v.id, v.reg_plate, v.make_model, v.status, v.mot_due, 
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
    
    for row in raw_vehicles:
        v_id = row[0]
        van_cost = float(row[7])
        driver_cost = float(row[8]) # Assuming hourly rate * 8 or similar? For now, we sum the rate.
        
        # Fetch Crew Members for this van
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
            
        # TOTAL DAY COST = Van + (Driver Rate * 8 hours) + (Crew Rate * 8 hours)
        # We assume 'pay_rate' is HOURLY. So we multiply labor by 8.
        # If pay_rate is Daily, remove the * 8.
        labor_cost = (driver_cost + crew_total_cost) * 8 
        total_day_cost = van_cost + labor_cost

        vehicles.append({
            'id': row[0],
            'reg_number': row[1],
            'make_model': row[2],
            'status': row[3],
            'mot_expiry': row[4],
            'driver_name': row[5],
            'driver_id': row[6],
            'daily_cost': row[7],
            'crew': crew_list,
            'total_gang_cost': total_day_cost
        })
    
    # Get Staff for Dropdowns
    cur.execute("SELECT id, name, role FROM staff WHERE company_id = %s AND status='Active'", (comp_id,))
    all_staff = [dict(zip(['id', 'name', 'role'], row)) for row in cur.fetchall()]
    
    conn.close()
    
    return render_template('office/fleet_management.html', vehicles=vehicles, staff=all_staff, brand_color=config['color'], logo_url=config['logo'])
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