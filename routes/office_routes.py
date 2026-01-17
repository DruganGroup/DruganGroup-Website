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
ALLOWED_OFFICE_ROLES = ['Admin', 'SuperAdmin', 'Office', 'Manager']
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

    # 3. JOBS & INVOICE STATS
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

    # Count Draft Invoices
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
    
    # DRAFT INVOICES LIST
    cur.execute("""
        SELECT i.id, i.reference, c.name, i.total, j.description 
        FROM invoices i 
        JOIN clients c ON i.client_id = c.id 
        LEFT JOIN jobs j ON i.job_id = j.id
        WHERE i.company_id = %s 
        AND i.status = 'Draft' 
        ORDER BY i.date DESC
    """, (company_id,))
    
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
                           invoices_to_review=invoices_to_review, 
                           recent_quotes=recent_quotes,
                           accepted_quotes=accepted_quotes,
                           draft_invoices=draft_invoices,        
                           live_ops=live_ops,
                           pending_requests=pending_requests,
                           brand_color=config['color'], 
                           logo_url=config['logo'])

# =========================================================
# 2. CALENDAR & SCHEDULING
# =========================================================

@office_bp.route('/office/calendar')
def office_calendar():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    # 1. GET UNSCHEDULED JOBS
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
            'pre_vehicle_id': r[5] 
        })

    # 2. GET ACTIVE VANS
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
        cur.execute("SELECT staff_id FROM vehicle_crew WHERE vehicle_id = %s", (v_id,))
        crew_ids = [row[0] for row in cur.fetchall()]
        
        fleet.append({
            'id': v_id, 
            'name': f"{reg} ({model})", 
            'driver_id': driver_id,
            'crew_ids': crew_ids
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
    lead_id = data.get('lead_id')   
    crew_ids = data.get('crew_ids', []) 
    comp_id = session.get('company_id')

    conn = get_db(); cur = conn.cursor()
    try:
        # 1. UPDATE THE JOB
        cur.execute("""
            UPDATE jobs 
            SET start_date = %s, engineer_id = %s, vehicle_id = %s, status = 'Scheduled' 
            WHERE id = %s AND company_id = %s
        """, (date_str, lead_id, vehicle_id, job_id, comp_id))
        
        # 2. UPDATE THE VEHICLE
        cur.execute("UPDATE vehicles SET assigned_driver_id = %s WHERE id = %s", (lead_id, vehicle_id))
        
        # 3. UPDATE THE CREW
        cur.execute("DELETE FROM vehicle_crew WHERE vehicle_id = %s", (vehicle_id,))
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
        cur.execute("""
            SELECT j.id, j.ref, j.start_date, c.name, j.status, p.address_line1 
            FROM jobs j 
            LEFT JOIN clients c ON j.client_id = c.id 
            LEFT JOIN properties p ON j.property_id = p.id
            WHERE j.company_id = %s AND j.start_date IS NOT NULL
        """, (comp_id,))
        
        for j in cur.fetchall():
            color = '#198754' if j[4] == 'Completed' else '#0d6efd'
            events.append({
                'id': j[0],
                'title': f"{j[1]} - {j[3]}", 
                'start': str(j[2]),
                'color': color,
                'url': f"/office/job/{j[0]}/files",
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
# 3. STAFF & FLEET
# =========================================================

@office_bp.route('/office/staff', methods=['GET', 'POST'])
def staff_list():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    
    try: 
        cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS license_path TEXT")
        conn.commit()
    except: 
        conn.rollback()

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_staff':
            allowed, msg = check_limit(comp_id, 'max_users')
            if not allowed:
                flash(msg, "error")
                return redirect(url_for('office.staff_list'))
                
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

            try:
                cur.execute("""
                    INSERT INTO staff (company_id, name, email, phone, position, status, license_path) 
                    VALUES (%s, %s, %s, %s, %s, 'Active', %s) 
                    RETURNING id
                """, (comp_id, name, email, phone, role, file_path))
                staff_id = cur.fetchone()[0]

                raw_password = generate_secure_password()
                hashed_pw = generate_password_hash(raw_password)
                login_email = email if email else f"staff{staff_id}_{comp_id}@businessbetter.co.uk"
                
                cur.execute("""
                    INSERT INTO users (company_id, name, email, password_hash, role) 
                    VALUES (%s, %s, %s, %s, %s)
                """, (comp_id, name, login_email, hashed_pw, 'Staff'))
                
                admin_name = session.get('user_name', 'Admin')
                cur.execute("""
                    INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                    VALUES (%s, 'STAFF_ADDED', %s, %s, %s, CURRENT_TIMESTAMP)
                """, (comp_id, name, f"New Staff Member ({role}) created", admin_name))

                conn.commit()
                flash(f"✅ Staff Added & Login Created! Password: {raw_password}")

            except Exception as e:
                conn.rollback()
                flash(f"Error adding staff: {e}", "error")

        elif action == 'edit_staff':
            sid = request.form.get('staff_id')
            name = request.form.get('name')
            email = request.form.get('email')
            phone = request.form.get('phone')
            role = request.form.get('role')
            status = request.form.get('status')
            
            file_path = None
            if 'license_file' in request.files:
                f = request.files['license_file']
                if f and f.filename != '':
                    filename = secure_filename(f"license_{comp_id}_{int(datetime.now().timestamp())}_{f.filename}")
                    f.save(os.path.join('static/uploads/licenses', filename))
                    file_path = f"uploads/licenses/{filename}"

            try:
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
                
                cur.execute("UPDATE users SET name=%s WHERE email=%s AND company_id=%s", (name, email, comp_id))
                
                cur.execute("""
                    INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                    VALUES (%s, 'STAFF_UPDATE', %s, 'Profile updated', %s, CURRENT_TIMESTAMP)
                """, (comp_id, name, session.get('user_name', 'Admin')))

                conn.commit()
                flash("✅ Staff Profile Updated")

            except Exception as e:
                conn.rollback()
                flash(f"Error updating staff: {e}", "error")

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
    
    cur.execute("CREATE TABLE IF NOT EXISTS vehicle_crew (vehicle_id INTEGER, staff_id INTEGER, PRIMARY KEY(vehicle_id, staff_id))")
    conn.commit()
    
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'assign_crew':
                v_id = request.form.get('vehicle_id')
                driver_id = request.form.get('driver_id')
                crew_ids = request.form.getlist('crew_ids')
                driver_val = driver_id if driver_id and driver_id != 'None' else None

                cur.execute("SELECT s.name FROM vehicles v LEFT JOIN staff s ON v.assigned_driver_id = s.id WHERE v.id = %s", (v_id,))
                res = cur.fetchone()
                old_driver = res[0] if res else "None"

                cur.execute("SELECT s.name FROM vehicle_crew vc JOIN staff s ON vc.staff_id = s.id WHERE vc.vehicle_id = %s", (v_id,))
                old_crew = [r[0] for r in cur.fetchall()]

                cur.execute("UPDATE vehicles SET assigned_driver_id = %s WHERE id = %s AND company_id = %s", (driver_val, v_id, comp_id))
                
                cur.execute("DELETE FROM vehicle_crew WHERE vehicle_id = %s", (v_id,))
                for staff_id in crew_ids:
                    if str(staff_id) != str(driver_val): 
                        cur.execute("INSERT INTO vehicle_crew (vehicle_id, staff_id) VALUES (%s, %s)", (v_id, staff_id))
                
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

                new_driver = "None"
                if driver_val:
                    cur.execute("SELECT name FROM staff WHERE id = %s", (driver_val,))
                    row = cur.fetchone()
                    if row: new_driver = row[0]

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

# =========================================================
# 4. CLIENTS & PROPERTIES (FIXED: ID Order & Duplicates Removed)
# =========================================================
@office_bp.route('/office/client/<int:client_id>')
def view_client(client_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Client
    cur.execute("SELECT id, name, email, phone, address FROM clients WHERE id = %s", (client_id,))
    c_row = cur.fetchone()
    
    if not c_row: 
        conn.close()
        return "Client not found", 404
        
    client = {
        'id': c_row[0], 'name': c_row[1], 'email': c_row[2], 'phone': c_row[3], 'address': c_row[4]
    }

    # 2. Fetch Properties (Explicit Column Order for Template Sync)
    # INDEX MAP:
    # 0: id, 1: address, 2: postcode, 3: tenant_name, 4: key_code
    # 5: gas, 6: eicr, 7: pat, 8: epc
    cur.execute("""
        SELECT 
            id, address_line1, postcode, 
            tenant_name, key_code,
            gas_expiry, eicr_expiry, pat_expiry, epc_expiry
        FROM properties 
        WHERE client_id = %s AND status != 'Archived'
        ORDER BY address_line1 ASC
    """, (client_id,))
    properties = cur.fetchall()
    
    # 3. Fetch Invoices
    cur.execute("SELECT id, reference, total_amount, status, date_created FROM invoices WHERE client_id = %s ORDER BY date_created DESC", (client_id,))
    invoices = cur.fetchall()
    
    conn.close()
    
    return render_template('office/client_details.html', 
                           client=client, 
                           properties=properties, 
                           invoices=invoices, 
                           current_date=date.today())

# --- THE ADD PROPERTY ROUTE (Matches Form Action) ---
@office_bp.route('/office/client/<int:client_id>/add-property', methods=['POST'])
def add_property_to_client(client_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO properties (company_id, client_id, address_line1, postcode, tenant_name, tenant_phone, key_code, gas_expiry, eicr_expiry, pat_expiry, epc_expiry, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Active')
        """, (session['company_id'], client_id, request.form.get('address'), request.form.get('postcode'), 
              request.form.get('tenant_name'), request.form.get('tenant_phone'), request.form.get('key_code'),
              request.form.get('gas_expiry') or None, request.form.get('eicr_expiry') or None, 
              request.form.get('pat_expiry') or None, request.form.get('epc_expiry') or None))
        conn.commit(); flash("✅ Property Added", "success")
    except Exception as e: conn.rollback(); flash(f"Error: {e}", "error")
    finally: conn.close()
    return redirect(f"/office/client/{client_id}")

@office_bp.route('/office/property/update', methods=['POST'])
def office_update_property():
    if not check_office_access(): return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE properties SET address_line1=%s, postcode=%s, tenant_name=%s, tenant_phone=%s, key_code=%s,
                                  gas_expiry=%s, eicr_expiry=%s, pat_expiry=%s, epc_expiry=%s
            WHERE id=%s
        """, (request.form.get('address'), request.form.get('postcode'), request.form.get('tenant_name'), request.form.get('tenant_phone'),
              request.form.get('key_code'), request.form.get('gas_expiry') or None, request.form.get('eicr_expiry') or None,
              request.form.get('pat_expiry') or None, request.form.get('epc_expiry') or None, request.form.get('property_id')))
        conn.commit(); flash("✅ Property Updated", "success")
    except Exception as e: conn.rollback(); flash(f"Error: {e}", "error")
    finally: conn.close()
    return redirect(f"/office/client/{request.form.get('client_id')}")

@office_bp.route('/office/property/<int:property_id>')
def view_property_office(property_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Property & Client
    cur.execute("""
        SELECT p.id, p.address_line1, p.postcode, p.tenant_name, p.tenant_phone, p.key_code,
               p.gas_expiry, p.eicr_expiry, p.pat_expiry, p.epc_expiry, c.name, c.id
        FROM properties p JOIN clients c ON p.client_id = c.id WHERE p.id = %s
    """, (property_id,))
    prop = cur.fetchone()
    if not prop: return "Property not found", 404
    
    # 2. Fetch Jobs
    cur.execute("SELECT id, ref, status, description, start_date FROM jobs WHERE property_id = %s ORDER BY start_date DESC", (property_id,))
    jobs = cur.fetchall()

    # 3. FETCH CERTIFICATES (This was missing)
    cur.execute("""
        SELECT id, type, status, date_issued, pdf_path 
        FROM certificates 
        WHERE property_id = %s 
        ORDER BY date_issued DESC
    """, (property_id,))
    certs = cur.fetchall()

    conn.close()
    return render_template('office/property_view.html', prop=prop, jobs=jobs, certs=certs, today=date.today())

@office_bp.route('/client/delete/<int:client_id>') 
def delete_client(client_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("DELETE FROM clients WHERE id = %s AND company_id = %s", (client_id, session.get('company_id')))
        conn.commit(); flash("🗑️ Client deleted", "success")
    except: conn.rollback(); flash("Error deleting client", "error")
    finally: conn.close()
    return redirect('/office-hub')

# --- API: FETCH CLIENT PROPERTIES ---
@office_bp.route('/api/client/<int:client_id>/properties')
def get_client_properties_api(client_id):
    if 'user_id' not in session: return jsonify([])
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, address_line1, postcode FROM properties WHERE client_id = %s", (client_id,))
    props = [{'id': r[0], 'address': f"{r[1]}, {r[2]}"} for r in cur.fetchall()]
    conn.close()
    return jsonify(props)

# =========================================================
# 5. SERVICE DESK & CERTIFICATES
# =========================================================

@office_bp.route('/office/service-desk', methods=['GET', 'POST'])
def service_desk():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        try:
            if request.form.get('action') == 'complete':
                cur.execute("UPDATE service_requests SET status = 'Completed' WHERE id = %s", (request.form.get('request_id'),))
            elif request.form.get('action') == 'delete':
                cur.execute("DELETE FROM service_requests WHERE id = %s", (request.form.get('request_id'),))
            conn.commit()
        except: conn.rollback()

    cur.execute("SELECT sr.id, sr.issue_description, sr.severity, sr.status, sr.created_at, c.name, p.address_line1 FROM service_requests sr LEFT JOIN clients c ON sr.client_id = c.id LEFT JOIN properties p ON sr.property_id = p.id WHERE sr.company_id = %s AND sr.status != 'Completed' ORDER BY sr.created_at DESC", (comp_id,))
    rows = cur.fetchall()
    requests = [{'id': r[0], 'issue_description': r[1], 'severity': r[2], 'status': r[3], 'date': format_date(r[4]), 'client_name': r[5] or 'N/A', 'property_address': r[6] or 'General', 'is_alert': False} for r in rows]

    cur.execute("SELECT id, name FROM staff WHERE company_id = %s", (comp_id,))
    staff = [{'id': s[0], 'name': s[1]} for s in cur.fetchall()]
    conn.close()
    return render_template('office/service_desk.html', requests=requests, staff=staff, brand_color=config['color'], logo_url=config['logo'])

@office_bp.route('/office/create-work-order', methods=['POST'])
def create_work_order():
    if not check_office_access(): return redirect('/login')
    req_id = request.form.get('request_id')
    staff_id = request.form.get('assigned_staff_id')
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT property_id, client_id, issue_description FROM service_requests WHERE id = %s", (req_id,))
        row = cur.fetchone()
        if row:
            import random
            job_ref = f"JOB-{row[0]}-{random.randint(100,999)}"
            cur.execute("INSERT INTO jobs (company_id, client_id, property_id, engineer_id, start_date, status, description, ref) VALUES (%s, %s, %s, %s, %s, 'Scheduled', %s, %s)",
                       (session['company_id'], row[1], row[0], staff_id, request.form.get('schedule_date'), 'In Progress', row[2], job_ref))
            cur.execute("UPDATE service_requests SET status = 'In Progress' WHERE id = %s", (req_id,))
            conn.commit(); flash("✅ Job Created", "success")
    except Exception as e: conn.rollback(); flash(f"Error: {e}", "error")
    finally: conn.close()
    return redirect('/office/service-desk')

@office_bp.route('/office/cert/gas/create')
def create_gas_cert():
    if not check_office_access(): return redirect(url_for('auth.login'))
    prop_id = request.args.get('prop_id')
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT p.address_line1, p.postcode, c.name, c.email FROM properties p JOIN clients c ON p.client_id = c.id WHERE p.id = %s", (prop_id,))
    row = cur.fetchone()
    conn.close()
    prop_data = {'id': prop_id, 'address': f"{row[0]}, {row[1]}", 'client': row[2], 'client_email': row[3]} if row else {}
    return render_template('office/certs/uk/cp12.html', prop=prop_data, today=date.today(), next_year_date=date.today() + timedelta(days=365))

@office_bp.route('/office/cert/gas/save', methods=['POST'])
def save_gas_cert():
    if not check_office_access(): return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    data = request.json
    conn = get_db(); cur = conn.cursor()
    comp_id = session.get('company_id')
    
    try:
        # 1. Generate PDF
        ref = f"CP12-{data.get('prop_id')}-{int(datetime.now().timestamp())}"
        filename = f"{ref}.pdf"
        
        # Fetch details for PDF context
        cur.execute("SELECT p.address_line1, p.postcode, c.name, c.email FROM properties p JOIN clients c ON p.client_id = c.id WHERE p.id = %s", (data.get('prop_id'),))
        p_row = cur.fetchone()
        
        client_email = p_row[3]
        prop_info = {'address': f"{p_row[0]}, {p_row[1]}", 'client': p_row[2], 'client_email': client_email, 'id': data.get('prop_id')}
        
        pdf_context = {'prop': prop_info, 'data': data, 'signature_url': data.get('signature_img'), 'next_year_date': data.get('next_date'), 'today': date.today().strftime('%d/%m/%Y')}
        generate_pdf('office/certs/uk/cp12.html', pdf_context, filename)
        
        db_path = f"generated_pdfs/{filename}" # Relative path for DB

        # 2. Save to Certificates Table (So it shows on Property Page)
        cur.execute("""
            INSERT INTO certificates (company_id, property_id, type, status, data, engineer_name, date_issued, expiry_date, pdf_path)
            VALUES (%s, %s, 'Gas Safety', 'Valid', %s, %s, CURRENT_DATE, %s, %s)
        """, (comp_id, data.get('prop_id'), json.dumps(data), session.get('user_name'), data.get('next_date'), db_path))

        # 3. Update Property Expiry Date
        if data.get('next_date'):
            cur.execute("UPDATE properties SET gas_expiry = %s WHERE id = %s", (data.get('next_date'), data.get('prop_id')))
        
        # 4. EMAIL THE CLIENT (The Missing Link)
        if client_email:
            try:
                # Assuming you have a helper function 'send_email_with_attachment'
                # If not, we use the basic sender from site_routes but adapted for attachments
                # For now, let's log that we tried.
                print(f"📧 Sending CP12 to {client_email}...")
                
                # To actually send, you need an email service function here.
                # If you have 'send_email_notification', it might process HTML but not attachments yet.
                # I will leave this placeholder so the code doesn't crash:
                pass 
            except Exception as mail_err:
                print(f"Email failed: {mail_err}")

        conn.commit()
        return jsonify({'success': True, 'redirect_url': url_for('office.view_property_office', property_id=data.get('prop_id'))})

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@office_bp.route('/office/cert/eicr/create')
def create_eicr_cert():
    if not check_office_access(): return redirect(url_for('auth.login'))
    prop_id = request.args.get('prop_id')
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT p.address_line1, p.city, p.postcode, c.name FROM properties p JOIN clients c ON p.client_id = c.id WHERE p.id = %s", (prop_id,))
    row = cur.fetchone()
    conn.close()
    prop_data = {'id': prop_id, 'address': f"{row[0]}, {row[1]}", 'client': row[3]} if row else {}
    return render_template('office/certs/uk/eicr.html', prop=prop_data, next_five_years=date.today() + timedelta(days=365*5))

@office_bp.route('/office/cert/eicr/save', methods=['POST'])
def save_eicr_cert():
    if not check_office_access(): return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    data = request.json
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO certificates (company_id, property_id, type, status, data, engineer_name, date_issued, expiry_date) VALUES (%s, %s, 'EICR', %s, %s, %s, CURRENT_DATE, %s)",
                   (session.get('company_id'), data.get('prop_id'), data.get('status', 'Issued'), json.dumps(data), session.get('user_name', 'Engineer'), data.get('next_inspection_date')))
        if data.get('status') == 'Issued' and data.get('next_inspection_date'):
            cur.execute("UPDATE properties SET eicr_expiry = %s WHERE id = %s", (data.get('next_inspection_date'), data.get('prop_id')))
        conn.commit(); return jsonify({'success': True, 'message': 'EICR Saved', 'redirect_url': url_for('office.office_dashboard')})
    except Exception as e: conn.rollback(); return jsonify({'success': False, 'error': str(e)})
    finally: conn.close()

# =========================================================
# 5. QUOTES & JOBS
# =========================================================

@office_bp.route('/office/quotes')
def quotes_dashboard():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT q.id, q.reference, c.name, q.date, q.total, q.status FROM quotes q LEFT JOIN clients c ON q.client_id = c.id WHERE q.company_id = %s ORDER BY q.id DESC", (session.get('company_id'),))
    quotes = [{'id': r[0], 'ref': r[1], 'client': r[2], 'date': format_date(r[3]), 'total': r[4], 'status': r[5]} for r in cur.fetchall()]
    conn.close()
    return render_template('office/office_dashboard.html', recent_quotes=quotes, brand_color='#333', logo_url='')

@office_bp.route('/office/quote/save', methods=['POST'])
def save_quote():
    if not check_office_access(): return jsonify({'status': 'error'}), 403
    data = request.json
    conn = get_db(); cur = conn.cursor()
    try:
        quote_id = data.get('quote_id')
        if not quote_id:
            cur.execute("INSERT INTO quotes (company_id, client_id, reference, date, status, vehicle_id) VALUES (%s, %s, 'Q-NEW', CURRENT_DATE, 'Draft', %s) RETURNING id", 
                       (session['company_id'], data['client_id'], data['vehicle_id']))
            quote_id = cur.fetchone()[0]
        else:
            cur.execute("UPDATE quotes SET client_id=%s, vehicle_id=%s WHERE id=%s", (data['client_id'], data['vehicle_id'], quote_id))
        
        cur.execute("DELETE FROM quote_items WHERE quote_id = %s", (quote_id,))
        total = 0
        for item in data.get('items', []):
            if not item.get('description'): continue
            t = float(item['quantity']) * float(item['unit_price'])
            total += t
            cur.execute("INSERT INTO quote_items (quote_id, description, quantity, unit_price, total) VALUES (%s, %s, %s, %s, %s)", (quote_id, item['description'], item['quantity'], item['unit_price'], t))
        
        # Add Van Cost
        if data.get('vehicle_id'):
            cur.execute("SELECT (daily_cost + COALESCE((SELECT pay_rate FROM staff WHERE id=assigned_driver_id),0)), reg_plate FROM vehicles WHERE id=%s", (data['vehicle_id'],))
            row = cur.fetchone()
            if row:
                cur.execute("INSERT INTO quote_items (quote_id, description, quantity, unit_price, total) VALUES (%s, %s, 1, %s, %s)", (quote_id, f"Logistics: {row[1]}", float(row[0]), float(row[0])))
                total += float(row[0])

        cur.execute("UPDATE quotes SET total = %s WHERE id = %s", (total, quote_id))
        conn.commit(); return jsonify({'status': 'success', 'quote_id': quote_id})
    except Exception as e: conn.rollback(); return jsonify({'status': 'error', 'message': str(e)})
    finally: conn.close()

@office_bp.route('/office/quote/delete/<int:quote_id>')
def delete_quote(quote_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("DELETE FROM quote_items WHERE quote_id = %s", (quote_id,))
        cur.execute("DELETE FROM quotes WHERE id = %s", (quote_id,))
        conn.commit(); flash("Deleted", "success")
    except: conn.rollback()
    finally: conn.close()
    return redirect('/office-hub')

@office_bp.route('/office/job/create', methods=['POST'])
def create_job():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    comp_id = session.get('company_id')
    
    try:
        client_id = request.form.get('client_id')
        description = request.form.get('description')
        start_date = request.form.get('start_date') or None  # FIX 1: Default to None (Unscheduled)
        vehicle_id = request.form.get('vehicle_id') or None
        est_days = request.form.get('days') or 1
        property_id = request.form.get('property_id') or None

        # FIX 2: LOGIC LINK - If Van is selected, finding the Driver
        engineer_id = None
        if vehicle_id:
            cur.execute("SELECT assigned_driver_id FROM vehicles WHERE id = %s", (vehicle_id,))
            row = cur.fetchone()
            if row and row[0]:
                engineer_id = row[0]

        # Generate Reference
        cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id = %s", (comp_id,))
        count = cur.fetchone()[0]
        ref = f"JOB-{1000 + count + 1}"

        cur.execute("""
            INSERT INTO jobs (
                company_id, client_id, property_id, engineer_id, vehicle_id, 
                ref, description, status, start_date, estimated_days
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pending', %s, %s)
            RETURNING id
        """, (comp_id, client_id, property_id, engineer_id, vehicle_id, ref, description, start_date, est_days))
        
        new_job_id = cur.fetchone()[0]
        conn.commit()
        
        flash(f"✅ Job {ref} Created Successfully", "success")
        return redirect(f"/office/job/{new_job_id}/files")

    except Exception as e:
        conn.rollback()
        flash(f"Error creating job: {e}", "error")
        return redirect(request.referrer or '/clients')
    finally:
        conn.close()
                           
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
    
    if not universal_sort_document: return jsonify({'status': 'success', 'message': 'File uploaded (AI Disabled)'})
    scan = universal_sort_document(full_path)
    if not scan['success']: return jsonify({'status': 'error', 'message': scan.get('error')})
    return jsonify({'status': 'success', 'data': scan['result']})

@office_bp.route('/office/upgrade-certs-db')
def upgrade_certs_db():
    if 'user_id' not in session: return "Not logged in"
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS certificates (id SERIAL PRIMARY KEY, company_id INTEGER, property_id INTEGER, type VARCHAR(20), status VARCHAR(20), data JSONB, engineer_name VARCHAR(100), date_issued DATE, expiry_date DATE, pdf_path TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.commit()
        return "✅ SUCCESS"
    except Exception as e: conn.rollback(); return f"Error: {e}"
    finally: conn.close()
    
    # =========================================================
# 6. RAMS & COMPLIANCE (Auto-Gen & Setup)
# =========================================================

# --- 🛠️ STEP 1: RUN THIS URL ONCE TO CREATE THE TABLE ---
# Visit: https://your-app-url.com/office/setup/rams-db
@office_bp.route('/office/setup/rams-db')
def setup_rams_db():
    if not check_office_access(): return "Unauthorized", 403
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS job_rams (
                id SERIAL PRIMARY KEY,
                job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
                company_id INTEGER,
                hazards JSONB,
                ppe JSONB,
                method_statement TEXT,
                risk_level VARCHAR(20),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                pdf_path TEXT
            );
        """)
        conn.commit()
        return "✅ RAMS Database Table Created Successfully! You can now generate RAMS."
    except Exception as e:
        conn.rollback()
        return f"❌ Error creating table: {e}"
    finally:
        conn.close()

# --- RAMS CREATION ROUTE ---
@office_bp.route('/office/job/<int:job_id>/rams/create')
def create_rams(job_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # Fetch Job Details
    cur.execute("""
        SELECT j.description, j.ref, c.name, p.address_line1 
        FROM jobs j
        JOIN clients c ON j.client_id = c.id
        LEFT JOIN properties p ON j.property_id = p.id
        WHERE j.id = %s
    """, (job_id,))
    job = cur.fetchone()
    conn.close()

    if not job: return "Job not found", 404

    desc = job[0].lower() if job[0] else ""
    
    # --- SMART AUTO-GEN LOGIC ---
    detected_hazards = ['Slips, Trips & Falls'] 
    detected_ppe = ['Safety Boots', 'Hi-Vis Vest']

    if any(x in desc for x in ['roof', 'gutter', 'ladder', 'height', 'ceiling']):
        detected_hazards.append('Working at Height')
        detected_ppe.append('Hard Hat')
        
    if any(x in desc for x in ['wire', 'socket', 'fuse', 'electric', 'light']):
        detected_hazards.append('Electricity')
        detected_ppe.append('Insulated Gloves')
        
    if any(x in desc for x in ['drill', 'hammer', 'break', 'demolish']):
        detected_hazards.append('Dust & Fumes')
        detected_hazards.append('Noise')
        detected_ppe.extend(['Dust Mask', 'Ear Defenders'])
        
    if any(x in desc for x in ['pipe', 'leak', 'water', 'plumb']):
        detected_hazards.append('Water Pressure')

    default_method = (
        f"1. Arrive at site ({job[3]}) and report to client ({job[2]}).\n"
        "2. Cordon off work area and display warning signs.\n"
        "3. Inspect tools and equipment before use.\n"
        f"4. Carry out works: {job[0]}.\n"
        "5. Clean up area, remove waste, and handover to client."
    )

    context = {
        'job_id': job_id,
        'ref': job[1],
        'client': job[2],
        'address': job[3],
        'hazards': detected_hazards,
        'ppe': list(set(detected_ppe)),
        'method': default_method
    }

    return render_template('office/rams/create_rams.html', data=context)

# --- SAVE RAMS ROUTE ---
@office_bp.route('/office/job/<int:job_id>/rams/save', methods=['POST'])
def save_rams(job_id):
    if not check_office_access(): return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.form
    hazards = request.form.getlist('hazards')
    ppe = request.form.getlist('ppe')
    method = data.get('method_statement')
    
    conn = get_db(); cur = conn.cursor()
    
    try:
        # Generate PDF Name
        pdf_filename = f"RAMS_{data['ref']}_{int(datetime.now().timestamp())}.pdf"
        
        pdf_context = {
            'ref': data['ref'],
            'date': date.today().strftime('%d/%m/%Y'),
            'client': data['client'],
            'address': data['address'],
            'hazards': hazards,
            'ppe': ppe,
            'method': method,
            'assessor': session.get('user_name', 'Office Admin')
        }
        
        # Ensure you have the PDF template file ready
        generate_pdf('office/rams/rams_pdf_template.html', pdf_context, pdf_filename)
        
        # Save to DB
        cur.execute("""
            INSERT INTO job_rams (job_id, company_id, hazards, ppe, method_statement, pdf_path)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (job_id, session['company_id'], json.dumps(hazards), json.dumps(ppe), method, f"generated_pdfs/{pdf_filename}"))
        
        conn.commit()
        flash("✅ RAMS Generated & Saved", "success")
        return redirect(f"/office/job/{job_id}/files")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error generating RAMS: {e}", "error")
        return redirect(f"/office/job/{job_id}/rams/create")
    finally:
        conn.close()
        
@office_bp.route('/office/job/create')
def create_job_view():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    # 1. Get IDs safely
    client_id = request.args.get('client_id')
    property_id = request.args.get('property_id')
    
    if not client_id or not property_id:
        flash("Missing Client or Property ID", "danger")
        return redirect(url_for('office.dashboard'))

    conn = get_db()
    cur = conn.cursor()

    # 2. Fetch Client
    cur.execute("SELECT id, name, email, phone FROM clients WHERE id = %s", (client_id,))
    client = cur.fetchone()

    # 3. Fetch Property
    cur.execute("SELECT id, address_line1, postcode FROM properties WHERE id = %s", (property_id,))
    prop = cur.fetchone()

    # 4. Fetch Vehicles
    cur.execute("SELECT * FROM vehicles WHERE status = 'Active' OR status IS NULL")
    vehicles = cur.fetchall()

    conn.close()

    if not client or not prop:
        flash("Client or Property not found", "danger")
        return redirect(url_for('office.dashboard'))

    # 5. Prepare Data
    client_data = {'id': client[0], 'name': client[1], 'email': client[2]}
    prop_data = {'id': prop[0], 'address_line1': prop[1], 'postcode': prop[2]}

    return render_template('office/job/create_job.html', 
                           client=client_data, 
                           property=prop_data, 
                           vehicles=vehicles)
                           
                           # --- DANGER: SYSTEM RESET TOOL ---
@office_bp.route('/office/admin/system-reset')
def system_reset():
    if session.get('role') != 'SuperAdmin': return "Unauthorized", 403
    
    conn = get_db()
    cur = conn.cursor()
    try:
        # 1. Clear Child Tables (Items, Logs, Files)
        cur.execute("DELETE FROM invoice_items")
        cur.execute("DELETE FROM quote_items")
        cur.execute("DELETE FROM job_expenses")
        cur.execute("DELETE FROM job_materials")
        cur.execute("DELETE FROM job_evidence")
        cur.execute("DELETE FROM job_rams")
        cur.execute("DELETE FROM staff_timesheets")
        
        # 2. Clear Main Transaction Tables
        cur.execute("DELETE FROM invoices")
        cur.execute("DELETE FROM jobs")
        cur.execute("DELETE FROM quotes")
        
        # 3. Reset Sequences (Optional, makes IDs start at 1 again)
        # cur.execute("ALTER SEQUENCE jobs_id_seq RESTART WITH 1")
        # cur.execute("ALTER SEQUENCE invoices_id_seq RESTART WITH 1")
        
        conn.commit()
        return "<h1>✅ System Wiped Clean.</h1><p>Jobs, Quotes, and Invoices deleted. <a href='/office-hub'>Back to Dashboard</a></p>"
    except Exception as e:
        conn.rollback()
        return f"Error resetting: {e}"
    finally:
        conn.close()