from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify, send_file
from db import get_db, get_site_config
from datetime import datetime, date, timedelta
from services.enforcement import check_limit
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
    
    company_id = session.get('company_id')
    config = get_site_config(company_id)
    conn = get_db(); cur = conn.cursor()
    
    # 1. SALES PIPELINE
    cur.execute("""
        SELECT status, COUNT(*), SUM(total) 
        FROM quotes 
        WHERE company_id = %s 
        GROUP BY status
    """, (company_id,))
    rows = cur.fetchall()
    
    pipeline = {
        'Draft': {'count': 0, 'value': 0},
        'Sent': {'count': 0, 'value': 0},
        'Accepted': {'count': 0, 'value': 0},
        'Declined': {'count': 0, 'value': 0}
    }
    for status, count, total in rows:
        if status in pipeline:
            pipeline[status] = {'count': count, 'value': total or 0}

    # 2. LEADS
    cur.execute("SELECT COUNT(*) FROM clients WHERE company_id = %s AND status = 'Lead'", (company_id,))
    leads_count = cur.fetchone()[0]

    # 3. JOBS & INVOICE STATS (Updated Logic)
    cur.execute("""
        SELECT 
            COUNT(*) FILTER (WHERE status = 'Scheduled'),
            COUNT(*) FILTER (WHERE status = 'In Progress')
        FROM jobs 
        WHERE company_id = %s
    """, (company_id,))
    job_stats = cur.fetchone()
    jobs_scheduled = job_stats[0]
    jobs_active = job_stats[1]

    # --- NEW: Count Draft Invoices instead of Completed Jobs ---
    cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id = %s AND status = 'Draft'", (company_id,))
    invoices_to_review = cur.fetchone()[0]

    # 4. FETCH LISTS
    
    # RECENT QUOTES
    cur.execute("""
        SELECT q.id, c.name, q.reference, q.date, q.total, q.status 
        FROM quotes q 
        LEFT JOIN clients c ON q.client_id = c.id 
        WHERE q.company_id = %s AND q.status IN ('Draft', 'Sent') 
        ORDER BY q.date DESC LIMIT 6
    """, (company_id,))
    recent_quotes = [{'id': r[0], 'client': r[1], 'ref': r[2], 'date': format_date(r[3]), 'total': r[4], 'status': r[5]} for r in cur.fetchall()]

    # ACCEPTED QUOTES
    cur.execute("""
        SELECT q.id, c.name, q.reference, q.total 
        FROM quotes q 
        LEFT JOIN clients c ON q.client_id = c.id 
        WHERE q.company_id = %s 
        AND q.status = 'Accepted' 
        AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.quote_id = q.id)
        ORDER BY q.date DESC
    """, (company_id,))
    accepted_quotes = [{'id': r[0], 'client': r[1], 'ref': r[2], 'total': r[3]} for r in cur.fetchall()]
    
    # --- NEW: DRAFT INVOICES LIST (To Review & Send) ---
    cur.execute("""
        SELECT i.id, i.reference, c.name, i.total, j.description 
        FROM invoices i 
        JOIN clients c ON i.client_id = c.id 
        LEFT JOIN jobs j ON i.job_id = j.id
        WHERE i.company_id = %s 
        AND i.status = 'Draft' 
        ORDER BY i.date DESC
    """, (company_id,))
    
    # We pass this as 'draft_invoices' instead of 'completed_jobs'
    draft_invoices = [{
        'id': r[0], 
        'ref': r[1], 
        'client': r[2], 
        'total': r[3], 
        'desc': r[4] or 'Invoice Generated from App'
    } for r in cur.fetchall()]

    # LIVE OPS
    try:
        cur.execute("""
            SELECT s.name, t.clock_in, j.site_address
            FROM staff_timesheets t
            JOIN staff s ON t.staff_id = s.id
            LEFT JOIN jobs j ON j.engineer_id = s.id AND j.status = 'In Progress'
            WHERE s.company_id = %s 
            AND t.date = CURRENT_DATE 
            AND t.clock_out IS NULL
        """, (company_id,))
        live_ops = []
        for r in cur.fetchall():
            location = r[2] if r[2] else "Head Office / Available"
            live_ops.append({'staff': r[0], 'address': location, 'duration': 'Active'})
    except Exception:
        live_ops = []

    # ALERTS
    cur.execute("SELECT COUNT(*) FROM service_requests WHERE company_id = %s AND status != 'Completed'", (company_id,))
    pending_requests = cur.fetchone()[0]

    conn.close()
    
    return render_template('office/office_dashboard.html', 
                           pipeline=pipeline,
                           leads_count=leads_count,
                           jobs_scheduled=jobs_scheduled,
                           jobs_active=jobs_active,
                           invoices_to_review=invoices_to_review, # <--- Updated Variable
                           recent_quotes=recent_quotes,
                           accepted_quotes=accepted_quotes,
                           draft_invoices=draft_invoices,         # <--- Updated List
                           live_ops=live_ops,
                           pending_requests=pending_requests,
                           brand_color=config['color'], 
                           logo_url=config['logo'])
# =========================================================
# CALENDAR & SCHEDULING (Updated for Crew Assignment)
# =========================================================

@office_bp.route('/office/calendar')
def office_calendar():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    # 1. GET UNSCHEDULED JOBS (Now fetching the Pre-Assigned Vehicle from the Quote)
    cur.execute("""
        SELECT j.id, j.ref, c.name, j.description, COALESCE(p.postcode, 'No Postcode'), j.vehicle_id 
        FROM jobs j 
        JOIN clients c ON j.client_id = c.id
        LEFT JOIN properties p ON j.property_id = p.id
        WHERE j.company_id = %s AND j.status IN ('Accepted', 'Pending') AND j.start_date IS NULL
    """, (comp_id,))
    
    unscheduled = []
    for r in cur.fetchall():
        unscheduled.append({
            'id': r[0], 'ref': r[1], 'client': r[2], 'desc': r[3], 'postcode': r[4], 
            'pre_vehicle_id': r[5] # <--- This carries the van choice from the quote
        })

    # 2. GET ACTIVE VANS (With Assigned Driver & Crew Gang)
    # We build a dictionary of vans so the frontend knows exactly who belongs to which van
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.assigned_driver_id
        FROM vehicles v 
        WHERE v.company_id = %s AND v.status = 'Active' 
        ORDER BY v.reg_plate
    """, (comp_id,))
    
    fleet_rows = cur.fetchall()
    fleet = []
    
    for v in fleet_rows:
        v_id, reg, model, driver_id = v
        
        # Fetch the Crew (Gang) assigned to this vehicle
        cur.execute("SELECT staff_id FROM vehicle_crew WHERE vehicle_id = %s", (v_id,))
        crew_ids = [row[0] for row in cur.fetchall()]
        
        fleet.append({
            'id': v_id, 
            'name': f"{reg} ({model})", 
            'driver_id': driver_id,  # The default Lead
            'crew_ids': crew_ids     # The default Gang
        })

    # 3. GET ALL ACTIVE STAFF
    cur.execute("SELECT id, name, position FROM staff WHERE company_id = %s AND status = 'Active' ORDER BY name", (comp_id,))
    staff = [{'id': r[0], 'name': r[1], 'role': r[2]} for r in cur.fetchall()]

    # 4. Settings
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    
    return render_template('office/calendar.html', 
                           unscheduled_jobs=unscheduled, 
                           fleet=fleet, 
                           staff=staff, 
                           settings=settings)
                           
@office_bp.route('/office/calendar/schedule-job', methods=['POST'])
def schedule_job():
    if not check_office_access(): return jsonify({'status': 'error'}), 403
    
    data = request.json
    job_id = data.get('job_id')
    date_str = data.get('date')
    vehicle_id = data.get('vehicle_id')
    lead_id = data.get('lead_id')   # The Driver / Lead Engineer
    crew_ids = data.get('crew_ids', []) # List of Crew IDs
    comp_id = session.get('company_id')

    conn = get_db(); cur = conn.cursor()
    try:
        # 1. UPDATE THE JOB
        # We explicitly link the Lead Engineer (so it shows in their app)
        cur.execute("""
            UPDATE jobs 
            SET start_date = %s, engineer_id = %s, vehicle_id = %s, status = 'Scheduled' 
            WHERE id = %s AND company_id = %s
        """, (date_str, lead_id, vehicle_id, job_id, comp_id))
        
        # 2. UPDATE THE VEHICLE (Sync the Van to this Job)
        # We set the Van's driver to the Lead Engineer chosen for this job
        cur.execute("UPDATE vehicles SET assigned_driver_id = %s WHERE id = %s", (lead_id, vehicle_id))
        
        # 3. UPDATE THE CREW (Sync the Crew to the Van)
        # This ensures that when the Lead clicks "Start Shift", these crew members are clocked in
        
        # A. Clear old crew for this van
        cur.execute("DELETE FROM vehicle_crew WHERE vehicle_id = %s", (vehicle_id,))
        
        # B. Add new crew members (excluding the lead, to avoid duplicates)
        for staff_id in crew_ids:
            if str(staff_id) != str(lead_id): 
                cur.execute("INSERT INTO vehicle_crew (vehicle_id, staff_id) VALUES (%s, %s)", (vehicle_id, staff_id))
        
        conn.commit()
        return jsonify({'status': 'success'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        conn.close()
        
@office_bp.route('/office/calendar/data')
def get_calendar_data():
    if not check_office_access(): return jsonify([])
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    events = []
    
    try:
        # Fetch Scheduled Jobs
        cur.execute("""
            SELECT j.id, j.ref, j.start_date, c.name, j.status, p.address_line1 
            FROM jobs j 
            LEFT JOIN clients c ON j.client_id = c.id 
            LEFT JOIN properties p ON j.property_id = p.id
            WHERE j.company_id = %s AND j.start_date IS NOT NULL
        """, (comp_id,))
        
        for j in cur.fetchall():
            # Green for Completed, Blue for Scheduled
            color = '#198754' if j[4] == 'Completed' else '#0d6efd'
            
            events.append({
                'id': j[0],
                'title': f"{j[1]} - {j[3]}", # Shows: "JOB-101 - Client Name"
                'start': str(j[2]),
                'color': color,
                'url': f"/office/job/{j[0]}/files", # Clicking opens the job pack
                'allDay': True,
                'extendedProps': {'address': j[5]}
            })
            
    except Exception as e:
        print(f"Calendar Data Error: {e}")
        
    conn.close()
    return jsonify(events)

@office_bp.route('/office/calendar/reschedule-job', methods=['POST'])
def reschedule_job():
    if not check_office_access(): return jsonify({'status': 'error'}), 403
    
    data = request.json
    conn = get_db(); cur = conn.cursor()
    try:
        # THE FIX: We add ", status = 'Scheduled'" to the query.
        # This ensures that dragging a job from the sidebar (or moving it) 
        # instantly marks it as Scheduled in the database.
        cur.execute("""
            UPDATE jobs 
            SET start_date = %s, status = 'Scheduled' 
            WHERE id = %s AND company_id = %s
        """, (data['date'], data['job_id'], session.get('company_id')))
        
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        conn.rollback(); return jsonify({'status': 'error', 'message': str(e)})
    finally: conn.close()
        
# =========================================================
# 2. STAFF & FLEET
# =========================================================

@office_bp.route('/office/staff', methods=['GET', 'POST'])
def staff_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    # Auto-migration for license path (just in case)
    try: 
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS license_path TEXT")
        conn.commit()
    except: 
        conn.rollback()

    if request.method == 'POST':
        action = request.form.get('action')
        
        # --- 1. ADD NEW STAFF ---
        if action == 'add_staff':
            allowed, msg = check_limit(comp_id, 'max_users')
            if not allowed:
                flash(msg, "error")
                return redirect(url_for('office.staff_list'))
                
            name = request.form.get('name')
            email = request.form.get('email')
            phone = request.form.get('phone')
            role = request.form.get('role')
            
            # File Upload Logic
            file_path = None
            if 'license_file' in request.files:
                f = request.files['license_file']
                if f and f.filename != '':
                    os.makedirs('static/uploads/licenses', exist_ok=True)
                    filename = secure_filename(f"license_{comp_id}_{int(datetime.now().timestamp())}_{f.filename}")
                    full_sys_path = os.path.join('static/uploads/licenses', filename)
                    f.save(full_sys_path)
                    file_path = f"uploads/licenses/{filename}"

            try:
                # A. Insert Staff
                cur.execute("""
                    INSERT INTO staff (company_id, name, email, phone, position, status, license_path) 
                    VALUES (%s, %s, %s, %s, %s, 'Active', %s) 
                    RETURNING id
                """, (comp_id, name, email, phone, role, file_path))
                staff_id = cur.fetchone()[0]

                # B. Create Login User
                raw_password = generate_secure_password()
                hashed_pw = generate_password_hash(raw_password)
                login_email = email if email else f"staff{staff_id}_{comp_id}@businessbetter.co.uk"
                
                cur.execute("""
                    INSERT INTO users (company_id, name, email, password_hash, role) 
                    VALUES (%s, %s, %s, %s, %s)
                """, (comp_id, name, login_email, hashed_pw, 'Staff'))
                
                # C. AUDIT LOG (Inside the same transaction)
                admin_name = session.get('user_name', 'Admin')
                cur.execute("""
                    INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                    VALUES (%s, 'STAFF_ADDED', %s, %s, %s, CURRENT_TIMESTAMP)
                """, (comp_id, name, f"New Staff Member ({role}) created", admin_name))

                # D. SAVE ALL
                conn.commit()
                flash(f"✅ Staff Added & Login Created! Password: {raw_password}")

            except Exception as e:
                conn.rollback()
                flash(f"Error adding staff: {e}", "error")

        # --- 2. EDIT STAFF ---
        elif action == 'edit_staff':
            sid = request.form.get('staff_id')
            name = request.form.get('name')
            email = request.form.get('email')
            phone = request.form.get('phone')
            role = request.form.get('role')
            status = request.form.get('status')
            
            # File Upload Logic (Edit Mode)
            file_path = None
            if 'license_file' in request.files:
                f = request.files['license_file']
                if f and f.filename != '':
                    filename = secure_filename(f"license_{comp_id}_{int(datetime.now().timestamp())}_{f.filename}")
                    f.save(os.path.join('static/uploads/licenses', filename))
                    file_path = f"uploads/licenses/{filename}"

            try:
                # A. Update Staff Record
                if file_path:
                    cur.execute("""
                        UPDATE staff SET name=%s, email=%s, phone=%s, position=%s, status=%s, license_path=%s 
                        WHERE id=%s AND company_id=%s
                    """, (name, email, phone, role, status, file_path, sid, comp_id))
                else:
                    cur.execute("""
                        UPDATE staff SET name=%s, email=%s, phone=%s, position=%s, status=%s 
                        WHERE id=%s AND company_id=%s
                    """, (name, email, phone, role, status, sid, comp_id))
                
                # B. Update User Login Name (Keep them synced)
                cur.execute("UPDATE users SET name=%s WHERE email=%s AND company_id=%s", (name, email, comp_id))
                
                # C. AUDIT LOG (Edit)
                cur.execute("""
                    INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                    VALUES (%s, 'STAFF_UPDATE', %s, 'Profile updated', %s, CURRENT_TIMESTAMP)
                """, (comp_id, name, session.get('user_name', 'Admin')))

                # D. SAVE ALL
                conn.commit()
                flash("✅ Staff Profile Updated")

            except Exception as e:
                conn.rollback()
                flash(f"Error updating staff: {e}", "error")

    # --- FETCH LIST ---
    cur.execute("SELECT id, name, email, phone, position AS role, status, license_path FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    cols = [desc[0] for desc in cur.description]
    staff = [dict(zip(cols, row)) for row in cur.fetchall()]
    
    conn.close()
    return render_template('office/staff_management.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

@office_bp.route('/office/fleet', methods=['GET', 'POST'])
def fleet_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    # Ensure helper table exists
    cur.execute("CREATE TABLE IF NOT EXISTS vehicle_crew (vehicle_id INTEGER, staff_id INTEGER, PRIMARY KEY(vehicle_id, staff_id))")
    conn.commit()
    
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            # --- ACTION: ASSIGN CREW ---
            if action == 'assign_crew':
                v_id = request.form.get('vehicle_id')
                driver_id = request.form.get('driver_id')
                crew_ids = request.form.getlist('crew_ids')
                
                # Handle Driver ID (convert 'None' string to DB NULL)
                driver_val = driver_id if driver_id and driver_id != 'None' else None

                # 1. GET OLD STATE (For Audit)
                cur.execute("SELECT s.name FROM vehicles v LEFT JOIN staff s ON v.assigned_driver_id = s.id WHERE v.id = %s", (v_id,))
                res = cur.fetchone()
                old_driver = res[0] if res else "None"

                cur.execute("SELECT s.name FROM vehicle_crew vc JOIN staff s ON vc.staff_id = s.id WHERE vc.vehicle_id = %s", (v_id,))
                old_crew = [r[0] for r in cur.fetchall()]

                # 2. PERFORM UPDATES (Driver & Crew)
                cur.execute("UPDATE vehicles SET assigned_driver_id = %s WHERE id = %s AND company_id = %s", (driver_val, v_id, comp_id))
                
                # Reset Crew
                cur.execute("DELETE FROM vehicle_crew WHERE vehicle_id = %s", (v_id,))
                for staff_id in crew_ids:
                    if str(staff_id) != str(driver_val): 
                        cur.execute("INSERT INTO vehicle_crew (vehicle_id, staff_id) VALUES (%s, %s)", (v_id, staff_id))
                
                # Save Dates & Settings
                daily = request.form.get('daily_cost')
                mot = request.form.get('mot_expiry') or None
                tax = request.form.get('tax_expiry') or None
                ins = request.form.get('ins_expiry') or None

                if daily is not None:
                      cur.execute("""
                        UPDATE vehicles 
                        SET daily_cost=%s, tracker_url=%s, telematics_provider=%s, tracking_device_id=%s,
                            mot_expiry=%s, tax_expiry=%s, ins_expiry=%s 
                        WHERE id=%s AND company_id=%s
                    """, (daily, request.form.get('tracker_url'), request.form.get('telematics_provider'), 
                          request.form.get('tracking_device_id'), mot, tax, ins, v_id, comp_id))

                # --- FIX START: Define new_driver before using it ---
                new_driver = "None"
                if driver_val:
                    cur.execute("SELECT name FROM staff WHERE id = %s", (driver_val,))
                    row = cur.fetchone()
                    if row: new_driver = row[0]
                # --- FIX END ---

                # 3. AUDIT LOG
                changes = []
                if old_driver != new_driver: changes.append(f"Driver: {old_driver} -> {new_driver}")
                if len(old_crew) != len(crew_ids): changes.append("Crew list updated")
                log_details = " | ".join(changes) if changes else "Vehicle settings/dates updated"

                try:
                    admin_name = session.get('user_name', 'Admin')
                    cur.execute("""
                        INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                        VALUES (%s, 'FLEET_UPDATE', %s, %s, %s, CURRENT_TIMESTAMP)
                    """, (comp_id, f"Vehicle ID {v_id}", log_details, admin_name))
                except Exception as e:
                    print(f"Audit Error: {e}")

                flash("✅ Crew & Settings Updated")
                
            # --- ACTION: ADD MAINTENANCE LOG ---
            elif action == 'add_log':
                file_url = None
                cost = request.form.get('cost')
                desc = request.form.get('description')
                date_val = request.form.get('date')
                
                if 'receipt_file' in request.files:
                    f = request.files['receipt_file']
                    if f and f.filename != '':
                        allowed, msg = check_limit(comp_id, 'max_storage')
                        if not allowed:
                            flash(msg, "error")
                            return redirect(url_for('office.fleet_list'))

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
                
                cur.execute("INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at) VALUES (%s, 'FLEET_LOG', %s, %s, %s, CURRENT_TIMESTAMP)",
                            (comp_id, f"Vehicle {request.form.get('vehicle_id')}", f"Added {request.form.get('log_type')} log: £{cost}", session.get('user_name', 'Admin')))
                flash("✅ Log Added")
            
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            flash(f"Error: {e}")

    # --- FETCH DATA FOR DISPLAY ---
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.status, s.name, v.assigned_driver_id, 
               v.mot_expiry, v.tax_expiry, v.ins_expiry, v.tracker_url
        FROM vehicles v 
        LEFT JOIN staff s ON v.assigned_driver_id = s.id 
        WHERE v.company_id = %s 
        ORDER BY v.reg_plate
    """, (comp_id,))
    
    raw = cur.fetchall()
    vehicles = []
    cur2 = conn.cursor()
    
    for row in raw:
        v_id = row[0]
        cur2.execute("SELECT s.id, s.name, s.position FROM vehicle_crew vc JOIN staff s ON vc.staff_id = s.id WHERE vc.vehicle_id = %s", (v_id,))
        crew = [{'id': c[0], 'name': c[1], 'role': c[2]} for c in cur2.fetchall()]
        
        cur2.execute("SELECT date, type, description, cost, receipt_path FROM maintenance_logs WHERE vehicle_id = %s ORDER BY date DESC", (v_id,))
        history = [{'date': format_date(r[0]), 'type': r[1], 'desc': r[2], 'cost': r[3], 'receipt': r[4]} for r in cur2.fetchall()]
        
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
    
    conn.close()
    
    return render_template('office/fleet_management.html', 
                           vehicles=vehicles, 
                           staff=staff, 
                           today=date.today(), 
                           date_fmt='%d/%m/%Y', 
                           brand_color=config['color'], 
                           logo_url=config['logo'])

# 3. SERVICE DESK (With Compliance Alerts)
# =========================================================

@office_bp.route('/office/service-desk', methods=['GET', 'POST'])
def service_desk():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    if 'ServiceDesk' not in session.get('modules', []):
        flash("🔒 Upgrade Required: This feature is locked on your current plan.", "warning")
        return redirect(url_for('office.office_dashboard'))
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

# =========================================================
# QUOTE SAVING & LOGIC (The Fix for Ghost Data)
# =========================================================

@office_bp.route('/office/quote/save', methods=['POST'])
def save_quote():
    if not check_office_access(): return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    
    data = request.json
    quote_id = data.get('quote_id')
    client_id = data.get('client_id')
    vehicle_id = data.get('vehicle_id')
    items = data.get('items', [])
    
    conn = get_db(); cur = conn.cursor()
    
    try:
        # 1. GENERATE REFERENCE (If New)
        if not quote_id:
            cur.execute("SELECT COUNT(*) FROM quotes WHERE company_id = %s", (session['company_id'],))
            count = cur.fetchone()[0]
            ref = f"Q-{1000 + count + 1}"
            
            cur.execute("""
                INSERT INTO quotes (company_id, client_id, reference, date, status, vehicle_id)
                VALUES (%s, %s, %s, CURRENT_DATE, 'Draft', %s)
                RETURNING id
            """, (session['company_id'], client_id, ref, vehicle_id))
            quote_id = cur.fetchone()[0]
        else:
            # Update existing header
            cur.execute("UPDATE quotes SET client_id = %s, vehicle_id = %s WHERE id = %s", (client_id, vehicle_id, quote_id))

        # --- THE FIX: WIPE OLD ITEMS FIRST ---
        # This prevents "Ghost Data" by deleting previous items before saving the new ones
        cur.execute("DELETE FROM quote_items WHERE quote_id = %s", (quote_id,))
        # -------------------------------------

        # 2. INSERT NEW ITEMS
        total_quote_value = 0.0
        
        for item in items:
            # Skip empty rows to prevent blank lines
            if not item['description'] and not item['price']:
                continue
                
            qty = float(item.get('quantity', 0))
            price = float(item.get('unit_price', 0))
            line_total = qty * price
            total_quote_value += line_total
            
            cur.execute("""
                INSERT INTO quote_items (quote_id, description, quantity, unit_price, total)
                VALUES (%s, %s, %s, %s, %s)
            """, (quote_id, item['description'], qty, price, line_total))

        # 3. AUTO-ADD VAN COST (Smart Logic)
        if vehicle_id:
            # Calculate Gang Cost (Van + Driver + Crew)
            cur.execute("""
                SELECT 
                    (v.daily_cost + 
                     COALESCE((SELECT s.pay_rate FROM staff s WHERE s.id = v.assigned_driver_id), 0) +
                     COALESCE((SELECT SUM(s.pay_rate) FROM vehicle_crew vc JOIN staff s ON vc.staff_id = s.id WHERE vc.vehicle_id = v.id), 0)
                    ) as total_daily_cost,
                    v.reg_plate
                FROM vehicles v
                WHERE v.id = %s
            """, (vehicle_id,))
            
            row = cur.fetchone()
            if row:
                van_cost = float(row[0])
                reg = row[1]
                
                # Check if "Labor & Logistics" is already in the list (prevents double charging)
                already_added = any("Labor & Logistics" in i['description'] for i in items)
                
                if not already_added:
                    desc = f"Labor & Logistics: {reg} (Driver + Crew)"
                    cur.execute("""
                        INSERT INTO quote_items (quote_id, description, quantity, unit_price, total)
                        VALUES (%s, %s, 1, %s, %s)
                    """, (quote_id, desc, van_cost, van_cost))
                    total_quote_value += van_cost

        # 4. UPDATE TOTAL
        cur.execute("UPDATE quotes SET total = %s WHERE id = %s", (total_quote_value, quote_id))
        
        conn.commit()
        return jsonify({'status': 'success', 'quote_id': quote_id})

    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        conn.close()

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

@office_bp.route('/office/upload-center', methods=['POST'])
def universal_upload():
    if not check_office_access(): return jsonify({'error': 'Unauthorized'}), 403
    
    comp_id = session.get('company_id')
    
    # 1. CHECK FOR FORCED JOB CONTEXT (The Fix)
    # If uploaded from a specific Job Page, use that Job ID.
    forced_job_ref = request.form.get('job_ref')
    forced_job_id = None
    
    conn = get_db(); cur = conn.cursor()
    
    if forced_job_ref:
        cur.execute("SELECT id FROM jobs WHERE ref = %s AND company_id = %s", (forced_job_ref, comp_id))
        row = cur.fetchone()
        if row: forced_job_id = row[0]

    # 2. SAVE FILE
    file = request.files.get('file')
    if not file: return jsonify({'error': 'No file'}), 400

    save_dir = os.path.join('static', 'uploads', str(comp_id), 'inbox')
    os.makedirs(save_dir, exist_ok=True)
    
    filename = secure_filename(f"{int(datetime.now().timestamp())}_{file.filename}")
    full_path = os.path.join(save_dir, filename)
    file.save(full_path)
    db_path = f"uploads/{comp_id}/inbox/{filename}"
    
    # 3. RUN AI SCAN (Readex)
    if not universal_sort_document:
        # Fallback if AI is broken: Just save as expense linked to job
        if forced_job_id:
            cur.execute("INSERT INTO job_expenses (company_id, job_id, description, cost, date, receipt_path) VALUES (%s, %s, %s, 0, CURRENT_DATE, %s)", 
                        (comp_id, forced_job_id, "Manual Upload (AI Offline)", db_path))
            conn.commit(); conn.close()
            return redirect(request.referrer)
        return jsonify({'status': 'success', 'message': 'File uploaded (AI disabled)', 'data': {}})

    scan = universal_sort_document(full_path)
    
    if not scan['success']:
        conn.close()
        return jsonify({'status': 'error', 'message': scan.get('error')})

    result = scan['result']
    doc_type = result.get('doc_type')
    data = result.get('data', {})
    
    msg = "File Processed"
    
    try:
        # 4. HANDLE FUEL RECEIPTS
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

        # 5. HANDLE INVOICES / MATERIALS (Linked to Job)
        elif doc_type == 'supplier_invoice' or forced_job_id:
            # Use Forced ID if available, otherwise trust AI
            final_job_id = forced_job_id 
            
            # If no forced ID, try to find one from the AI data
            if not final_job_id and data.get('job_ref'):
                ref = data.get('job_ref')
                cur.execute("SELECT id FROM jobs WHERE ref ILIKE %s AND company_id=%s", (f"%{ref}%", comp_id))
                row = cur.fetchone()
                if row: final_job_id = row[0]
            
            desc = f"Invoice: {data.get('supplier_name', 'Unknown Supplier')}"
            cost = data.get('total') or 0
            doc_date = data.get('date') or date.today()

            cur.execute("""
                INSERT INTO job_expenses (company_id, job_id, description, cost, date, receipt_path) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (comp_id, final_job_id, desc, cost, doc_date, db_path))
            
            msg = f"Invoice Filed. Linked to Job: {forced_job_ref if forced_job_id else 'Unassigned'}"

        conn.commit()
        
        # If we came from a job page, go back there
        if forced_job_ref:
            return redirect(f"/office/job/{forced_job_id}/files")
            
        return jsonify({'status': 'success', 'doc_type': doc_type, 'message': msg, 'data': data})

    except Exception as e:
        conn.rollback(); return jsonify({'status': 'error', 'message': str(e)})
    finally:
        conn.close()

@office_bp.route('/office/client/<int:client_id>/enable-portal', methods=['POST'])
def enable_portal(client_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    try:
        # 1. Fetch Client
        cur.execute("SELECT name, email FROM clients WHERE id = %s AND company_id = %s", (client_id, comp_id))
        client = cur.fetchone()
        
        if not client or not client[1]: 
            flash("❌ Client needs email.", "error")
            return redirect(url_for('office.view_client', client_id=client_id))

        client_name, client_email = client

        # 2. Generate Credentials
        raw_password = generate_secure_password()
        hashed_password = generate_password_hash(raw_password)
        cur.execute("UPDATE clients SET password_hash = %s WHERE id = %s", (hashed_password, client_id))
        
        # 3. Fetch Company Name & Settings (THE FIX)
        # We explicitly get the name saved in settings for THIS company ID
        cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
        settings = {row[0]: row[1] for row in cur.fetchall()}
        
        # Fallback only if settings are empty, otherwise use the exact saved name
        company_name = settings.get('company_name', 'Your Service Provider')
        
        # --- WHITE LABEL LINK LOGIC ---
        # If the company name contains "Drugan", use your custom domain
        # Everyone else (ACME, etc) uses the generic SaaS domain
        if "drugan" in company_name.lower():
            base_domain = "https://www.drugangroup.co.uk"
        else:
            base_domain = "https://www.businessbetter.co.uk"
            
        login_link = f"{base_domain}/portal/login/{comp_id}"
        # ------------------------------

        if 'smtp_host' in settings:
            msg = MIMEMultipart()
            msg['From'] = settings.get('smtp_email')
            msg['To'] = client_email
            msg['Subject'] = f"{company_name} - Portal Invitation"

            body = f"""
            <div style="font-family: sans-serif; padding: 20px; border: 1px solid #ddd; border-radius: 8px;">
                <h2 style="color: #333;">Welcome to the Portal</h2>
                <p>Hello {client_name},</p>
                <p><strong>{company_name}</strong> has invited you to their secure client portal.</p>
                <p>You can use this portal to view quotes, pay invoices, and download certificates.</p>
                
                <p style="margin: 25px 0;">
                    <a href="{login_link}" style="background-color: #0d6efd; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                        Open Client Portal
                    </a>
                </p>
                
                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; color: #555;">
                    <strong>Login Details:</strong><br>
                    Email: {client_email}<br>
                    Password: {raw_password}
                </div>
            </div>
            """
            
            msg.attach(MIMEText(body, 'html'))

            server = smtplib.SMTP(settings['smtp_host'], int(settings['smtp_port']))
            server.starttls()
            server.login(settings['smtp_email'], settings['smtp_password'])
            server.send_message(msg)
            server.quit()
            flash(f"✅ Invite sent to {client_email}")
        else:
            flash("⚠️ Password generated, but Email Failed (SMTP Settings missing)", "warning")
            
        conn.commit()
    except Exception as e: 
        conn.rollback(); flash(f"Error: {e}", "error")
    finally: 
        conn.close()
    
    return redirect(f"/client/{client_id}")
   
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
    
@office_bp.route('/office/quotes')
def quotes_dashboard():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    config = get_site_config(comp_id)
    
    # Fetch All Quotes
    cur.execute("""
        SELECT q.id, q.reference, c.name, q.date, q.total, q.status, q.job_title
        FROM quotes q
        LEFT JOIN clients c ON q.client_id = c.id
        WHERE q.company_id = %s
        ORDER BY q.id DESC
    """, (comp_id,))
    
    quotes = [{
        'id': r[0], 'ref': r[1], 'client': r[2], 
        'date': format_date(r[3]), 'total': r[4], 
        'status': r[5], 'title': r[6]
    } for r in cur.fetchall()]
    
    conn.close()
    # Note: Ensure you have a 'quotes_dashboard.html' or redirect to a generic list
    # For now, we will render the same view but you might want to create a specific template later
    return render_template('office/office_dashboard.html', 
                           recent_quotes=quotes, # Re-using the variable name to show list
                           brand_color=config['color'], logo_url=config['logo'])
                           
@office_bp.route('/office/job/<int:job_id>/files')
def job_dashboard(job_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    # 1. FETCH JOB DETAILS (Fixed Columns)
    cur.execute("""
        SELECT 
            j.ref, 
            j.description, 
            COALESCE(p.address_line1, j.site_address, 'No Address Logged'), 
            j.status, 
            j.quote_id, 
            COALESCE(j.quote_total, 0),
            c.name
        FROM jobs j 
        LEFT JOIN clients c ON j.client_id = c.id
        LEFT JOIN properties p ON j.property_id = p.id
        WHERE j.id = %s AND j.company_id = %s
    """, (job_id, comp_id))
    
    job_row = cur.fetchone()
    if not job_row: conn.close(); return "Job not found", 404
    
    # Dictionary Mapping (Safe & Clean)
    job = {
        'id': job_id,
        'ref': job_row[0],
        'desc': job_row[1],
        'address': job_row[2], # <-- This is the fixed address
        'status': job_row[3],
        'client': job_row[6] or "Unknown Client" # <-- This is the fixed client name
    }
    quote_id, quote_total = job_row[4], float(job_row[5])

    # 2. FINANCIALS (Calculations)
    cur.execute("SELECT COALESCE(SUM(total_amount), 0) FROM invoices WHERE job_id = %s AND status != 'Void'", (job_id,))
    total_billed = float(cur.fetchone()[0])
    cur.execute("SELECT COALESCE(SUM(cost), 0) FROM job_expenses WHERE job_id = %s", (job_id,))
    expenses = float(cur.fetchone()[0])
    cur.execute("SELECT COALESCE(SUM(quantity * unit_price), 0) FROM job_materials WHERE job_id = %s", (job_id,))
    materials_cost = float(cur.fetchone()[0])
    cur.execute("SELECT COALESCE(SUM(t.total_hours * s.pay_rate), 0) FROM staff_timesheets t JOIN staff s ON t.staff_id = s.id WHERE t.job_id = %s", (job_id,))
    labour = float(cur.fetchone()[0])
    
    total_cost = expenses + materials_cost + labour
    profit = quote_total - total_cost
    budget_remaining = quote_total - total_cost

    # 3. FILES LIST (Invoices, Expenses, Materials, Timesheets)
    files = []
    
    # Invoices
    cur.execute("SELECT id, ref, total_amount, date_created FROM invoices WHERE job_id = %s ORDER BY date_created DESC", (job_id,))
    for r in cur.fetchall(): files.append(('Client Invoice', r[1], float(r[2]), str(r[3]), 'invoice', r[0]))

    # Expenses
    cur.execute("SELECT description, cost, date, receipt_path, id FROM job_expenses WHERE job_id = %s ORDER BY date DESC", (job_id,))
    for r in cur.fetchall(): files.append(('Expense Receipt', r[0], float(r[1]), str(r[2]), r[3] or 'No Link', r[4]))
        
    # Materials
    cur.execute("SELECT description, quantity, unit_price, date_added, id FROM job_materials WHERE job_id = %s ORDER BY date_added DESC", (job_id,))
    for r in cur.fetchall(): files.append(('Site Material', f"{r[1]}x {r[0]}", float(r[1])*float(r[2]), str(r[3]), 'Material', r[4]))

    # Timesheets (Fixed 'total_hours')
    cur.execute("SELECT t.id, s.name, t.total_hours, s.pay_rate, t.date FROM staff_timesheets t JOIN staff s ON t.staff_id = s.id WHERE t.job_id = %s ORDER BY t.date DESC", (job_id,))
    for r in cur.fetchall(): 
        hours = float(r[2]) if r[2] else 0.0
        cost = hours * float(r[3])
        files.append(('Timesheet', f"Labor: {r[1]} ({hours} hrs)", cost, str(r[4]), 'No Link', r[0]))

    cur.execute("SELECT id, name FROM staff WHERE company_id = %s AND status='Active'", (comp_id,))
    staff = cur.fetchall()
    conn.close()
    
    return render_template('office/job_files.html', 
                           job=job, # Passing the dictionary
                           quote_id=quote_id, quote_total=quote_total, 
                           total_billed=total_billed, total_cost=total_cost, profit=profit, 
                           budget_remaining=budget_remaining, files=files, staff=staff, today=date.today())
                           
@office_bp.route('/office/quote/delete/<int:quote_id>')
def delete_quote(quote_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    try:
        # 1. Delete Items first (Foreign Key cleanup)
        cur.execute("DELETE FROM quote_items WHERE quote_id = %s", (quote_id,))
        
        # 2. Delete the Quote Header
        cur.execute("DELETE FROM quotes WHERE id = %s AND company_id = %s", (quote_id, session.get('company_id')))
        
        conn.commit()
        flash("🗑️ Quote deleted successfully.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error deleting quote: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('office.office_dashboard'))
    
    # --- OFFICE: FLEET MANAGER ---
@office_bp.route('/office/fleet', methods=['GET', 'POST'])
def office_fleet():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    # Check if user has access (Office or Admin/SuperAdmin)
    if session.get('role') not in ['Office', 'Admin', 'SuperAdmin', 'Manager']:
        return redirect(url_for('office.office_dashboard'))

    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    # --- HANDLE POST (Assign Driver/Crew or Add Log) ---
    if request.method == 'POST':
        action = request.form.get('action')
        
        try:
            if action == 'assign_crew':
                veh_id = request.form.get('vehicle_id')
                driver_id = request.form.get('driver_id')
                
                # If "None" is selected, convert to None type for DB
                if driver_id == 'None': driver_id = None

                # Update Driver
                cur.execute("UPDATE vehicles SET assigned_driver_id = %s WHERE id = %s AND company_id = %s", 
                           (driver_id, veh_id, comp_id))
                
                # Update Crew
                crew_ids = request.form.getlist('crew_ids')
                cur.execute("DELETE FROM vehicle_crew WHERE vehicle_id = %s", (veh_id,))
                for staff_id in crew_ids:
                    cur.execute("INSERT INTO vehicle_crew (vehicle_id, staff_id) VALUES (%s, %s)", (veh_id, staff_id))
                
                flash("✅ Crew and Driver updated.")

            elif action == 'add_log':
                # (Keep your existing Log/Receipt logic here if you have it)
                # This part likely handles the receipt upload in your current file
                pass 

            conn.commit()
        except Exception as e:
            conn.rollback()
            flash(f"Error: {e}")

    # --- GET REQUEST: FETCH DATA ---
    # UPDATED QUERY: Now selects mot_expiry and tax_expiry
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.status, 
               v.assigned_driver_id, s.name as driver_name,
               v.mot_expiry, v.tax_expiry
        FROM vehicles v
        LEFT JOIN staff s ON v.assigned_driver_id = s.id
        WHERE v.company_id = %s
        ORDER BY v.reg_plate
    """, (comp_id,))
    
    vehicles_raw = cur.fetchall()
    vehicles = []
    
    for r in vehicles_raw:
        v_id = r[0]
        
        # Fetch Crew
        cur.execute("""
            SELECT s.id, s.name 
            FROM vehicle_crew vc
            JOIN staff s ON vc.staff_id = s.id
            WHERE vc.vehicle_id = %s
        """, (v_id,))
        crew = [{'id': c[0], 'name': c[1]} for c in cur.fetchall()]

        # Fetch History/Logs (for the receipts tab)
        # Assuming you have a maintenance_logs table logic here
        # (I am keeping this minimal to prevent crashing, add your logs query if needed)
        history = [] 

        vehicles.append({
            'id': v_id,
            'reg_number': r[1],      # Maps reg_plate -> reg_number
            'make_model': r[2],
            'status': r[3],
            'assigned_driver_id': r[4],
            'driver_name': r[5],
            'mot_expiry': r[6],      # NOW EXISTS
            'tax_expiry': r[7],      # NOW EXISTS
            'crew': crew,
            'history': history
        })

    # Fetch Staff for dropdowns
    cur.execute("SELECT id, name FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    staff = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]
    
    conn.close()

    # We pass 'today' so your date_check macro works
    return render_template('office/fleet_management.html', 
                           vehicles=vehicles, 
                           staff=staff,
                           today=datetime.now().date())
                           
# CHANGE THE ROUTE LINE TO THIS (Remove '/office'):
@office_bp.route('/client/delete/<int:client_id>') 
def delete_client(client_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM clients WHERE id = %s AND company_id = %s", (client_id, session.get('company_id')))
        conn.commit()
        flash("🗑️ Client deleted successfully.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error deleting client: {e}", "error")
    finally:
        conn.close()
        
    # Redirect to the client list, not the dashboard
    return redirect('/clients')