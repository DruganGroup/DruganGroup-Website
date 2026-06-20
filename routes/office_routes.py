from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify, send_file
from db import get_db, get_site_config
from datetime import datetime, date, timedelta
from services.enforcement import check_limit
import json

# Custom Services
from services.pdf_generator import generate_pdf
try:
    from services.ai_assistant import scan_receipt
except ImportError:
    scan_receipt = None

office_bp = Blueprint('office', __name__)
ALLOWED_OFFICE_ROLES = ['Admin', 'SuperAdmin', 'Office', 'Manager']

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
    except:
        return str(d)

@office_bp.route('/office/service-desk')
def service_desk():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    # --- SMART MIGRATIONS ---
    migrations = [
        "ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS priority VARCHAR(50) DEFAULT 'Medium';",
        "ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS photo_path TEXT;",
        "ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS partner_company_id INTEGER;",
        "ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS parent_request_id INTEGER;",
        "ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS partner_address_snapshot VARCHAR(255);",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS partner_code VARCHAR(20);",
        """CREATE TABLE IF NOT EXISTS company_partners (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            partner_id INTEGER,
            status VARCHAR(20) DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company_id, partner_id)
        );""",
        "ALTER TABLE company_partners ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'Pending';"
    ]
    
    for query in migrations:
        try:
            cur.execute(query)
            conn.commit()
        except:
            conn.rollback()

    # 1. FETCH SERVICE REQUESTS (TICKETS)
    # Modified to show if it's from a partner
    cur.execute("""
        SELECT sr.id, sr.priority, 
               COALESCE(p.address_line1, sr.partner_address_snapshot), 
               sr.issue_description, 
               COALESCE(c.name, 'Partner Network Job'), 
               sr.status, sr.photo_path, sr.created_at,
               sr.partner_company_id,
               sr.parent_request_id
        FROM service_requests sr
        LEFT JOIN properties p ON sr.property_id = p.id
        LEFT JOIN clients c ON sr.client_id = c.id
        WHERE sr.company_id = %s AND sr.status != 'Completed'
        ORDER BY sr.created_at DESC
    """, (comp_id,))
    
    raw_reqs = cur.fetchall()
    requests = []
    for r in raw_reqs:
        requests.append({
            'id': r[0], 'severity': r[1], 'property_address': r[2],
            'issue_description': r[3], 'client_name': r[4], 'status': r[5],
            'photo_path': r[6], 'date': r[7].strftime('%d/%m/%Y %H:%M') if r[7] else ''
        })

    # 2. FETCH COMPLIANCE ALERTS
    cur.execute("""
        SELECT p.id, p.address_line1, p.postcode, c.name,
               p.gas_expiry, p.eicr_expiry, p.epc_expiry, p.pat_expiry
        FROM properties p
        LEFT JOIN clients c ON p.client_id = c.id
        WHERE p.company_id = %s
          AND (
               (p.gas_expiry IS NOT NULL AND p.gas_expiry <= CURRENT_DATE + INTERVAL '30 days') OR
               (p.eicr_expiry IS NOT NULL AND p.eicr_expiry <= CURRENT_DATE + INTERVAL '30 days') OR
               (p.epc_expiry IS NOT NULL AND p.epc_expiry <= CURRENT_DATE + INTERVAL '30 days') OR
               (p.pat_expiry IS NOT NULL AND p.pat_expiry <= CURRENT_DATE + INTERVAL '30 days')
          )
        ORDER BY p.gas_expiry ASC NULLS LAST
    """, (comp_id,))
    
    expiring_props = []
    for row in cur.fetchall():
        expiring_props.append({
            'prop_id': row[0], 'address': f"{row[1]}, {row[2]}", 'client': row[3],
            'client_id': row[3], # Need actual client_id for quote generation, wait, let's fix this
            'gas': row[4], 'eicr': row[5], 'epc': row[6], 'pat': row[7]
        })
        
    # Re-fetch with client_id
    cur.execute("""
        SELECT p.id, p.address_line1, p.postcode, c.name, c.id,
               p.gas_expiry, p.eicr_expiry, p.epc_expiry, p.pat_expiry
        FROM properties p
        LEFT JOIN clients c ON p.client_id = c.id
        WHERE p.company_id = %s
          AND (
               (p.gas_expiry IS NOT NULL AND p.gas_expiry <= CURRENT_DATE + INTERVAL '30 days') OR
               (p.eicr_expiry IS NOT NULL AND p.eicr_expiry <= CURRENT_DATE + INTERVAL '30 days') OR
               (p.epc_expiry IS NOT NULL AND p.epc_expiry <= CURRENT_DATE + INTERVAL '30 days') OR
               (p.pat_expiry IS NOT NULL AND p.pat_expiry <= CURRENT_DATE + INTERVAL '30 days')
          )
        ORDER BY p.gas_expiry ASC NULLS LAST
    """, (comp_id,))
    
    expiring_props = []
    for row in cur.fetchall():
        expiring_props.append({
            'prop_id': row[0], 'address': f"{row[1]}, {row[2]}", 'client': row[3],
            'client_id': row[4],
            'gas': row[5], 'eicr': row[6], 'epc': row[7], 'pat': row[8]
        })

    # 3. FETCH STAFF FOR DISPATCH MODAL
    cur.execute("SELECT id, name FROM staff WHERE company_id=%s AND status='Active'", (comp_id,))
    staff = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]

    # 4. FETCH ACTIVE PARTNERS FOR B2B DISPATCH MODAL
    cur.execute("""
        SELECT cp.id, c.name, c.id as partner_comp_id
        FROM company_partners cp
        JOIN companies c ON c.id = cp.partner_id
        WHERE cp.company_id = %s AND cp.status = 'Active'
        UNION
        SELECT cp.id, c.name, c.id as partner_comp_id
        FROM company_partners cp
        JOIN companies c ON c.id = cp.company_id
        WHERE cp.partner_id = %s AND cp.status = 'Active'
    """, (comp_id, comp_id))
    active_partners = [{'name': r[1], 'id': r[2]} for r in cur.fetchall()]

    conn.close()
    
    from datetime import datetime
    now_func = datetime.now
    
    return render_template('office/service_desk.html', 
                           requests=requests, 
                           expiring_props=expiring_props,
                           staff=staff,
                           active_partners=active_partners,
                           brand_color=config['color'], 
                           logo=config['logo'],
                           now=now_func)

@office_bp.route('/office/dispatch-to-partner', methods=['POST'])
def dispatch_to_partner():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    req_id = request.form.get('request_id')
    partner_id = request.form.get('partner_company_id')
    
    if not partner_id:
        flash("❌ No partner selected.", "error")
        return redirect(url_for('office.service_desk'))
        
    conn = get_db(); cur = conn.cursor()
    try:
        # 1. Fetch original request details
        cur.execute("""
            SELECT sr.issue_description, sr.priority, sr.photo_path, p.address_line1
            FROM service_requests sr
            JOIN properties p ON sr.property_id = p.id
            WHERE sr.id = %s AND sr.company_id = %s
        """, (req_id, comp_id))
        row = cur.fetchone()
        
        if not row:
            flash("❌ Request not found.", "error")
            return redirect(url_for('office.service_desk'))
            
        desc, priority, photo, address = row
        
        # 2. Insert into Partner's Service Requests
        cur.execute("""
            INSERT INTO service_requests (
                company_id, issue_description, priority, status, photo_path, 
                partner_address_snapshot, parent_request_id, partner_company_id
            ) VALUES (%s, %s, %s, 'Pending', %s, %s, %s, %s)
        """, (partner_id, desc, priority, photo, address, req_id, comp_id))
        
        # 3. Update my request status
        cur.execute("UPDATE service_requests SET status = 'Sent to Partner' WHERE id = %s", (req_id,))
        
        # 4. Notify Partner via Email (From the dispatching tenant to the partner)
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'company_email'", (partner_id,))
        partner_email_row = cur.fetchone()
        
        if partner_email_row and partner_email_row[0]:
            partner_email = partner_email_row[0]
            my_company_name = session.get('company_name', 'A partner company')
            
            subject = f"New Partner Job Dispatched: {priority} Priority"
            body = f"Hello,<br><br><strong>{my_company_name}</strong> has dispatched a new service request to your network.<br><br><strong>Priority:</strong> {priority}<br><strong>Description:</strong> {desc}<br><strong>Location:</strong> {address}<br><br>Please check your Service Desk to view and action this request.<br><br>Thank you."
            
            from tasks import send_tenant_email_task
            send_tenant_email_task.delay(
                company_id=comp_id,
                recipient_email=partner_email,
                subject=subject,
                body_html=body
            )

        conn.commit()
        flash("✅ Job successfully dispatched to partner network!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error dispatching to partner: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('office.service_desk'))

@office_bp.route('/office-hub')
def office_dashboard():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    # --- GET SETTINGS ---
    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'date_format'", (comp_id,))
    row = cur.fetchone()
    user_date_fmt = row[0] if row and row[0] else '%d/%m/%Y'

    # --- HELPER: Date Formatter ---
    def process_date(date_val, fmt):
        if not date_val: return "TBC", None, None
        dt = date_val
        if isinstance(date_val, str):
            try: dt = datetime.strptime(date_val[:10], '%Y-%m-%d')
            except: return str(date_val), None, None
        return dt.strftime(fmt), dt.strftime('%d'), dt.strftime('%b')

    # --- COUNTERS ---
    cur.execute("SELECT COUNT(*) FROM service_requests WHERE company_id=%s AND status='Pending'", (comp_id,))
    leads_count = cur.fetchone()[0]
    
    cur.execute("""SELECT COUNT(*) FROM quotes WHERE company_id=%s AND status IN ('Draft', 'Sent', 'Pending', 'Accepted')""", (comp_id,))
    pending_quotes = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id=%s AND status='Scheduled'", (comp_id,))
    active_jobs = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id=%s AND status='Unpaid'", (comp_id,))
    unpaid_inv = cur.fetchone()[0]

    # --- LISTS ---
    
    # 1. NEW REQUESTS (Now includes client_id for the button)
    cur.execute("""
        SELECT r.id, c.name, c.phone, r.created_at, r.issue_description, r.client_id
        FROM service_requests r
        JOIN clients c ON r.client_id = c.id
        WHERE r.company_id = %s AND r.status = 'Pending'
        ORDER BY r.created_at DESC LIMIT 5
    """, (comp_id,))
    
    incoming_requests = []
    for r in cur.fetchall():
        fmt_date, _, _ = process_date(r[3], user_date_fmt)
        incoming_requests.append({
            'id': r[0], 
            'client_name': r[1], 
            'phone': r[2], 
            'date_added': fmt_date,
            'desc': r[4],
            'client_id': r[5]  # Critical for the Review button
        })
        
    # 4. RECENT QUOTES (The Missing List)
    cur.execute("""
        SELECT q.id, q.reference, c.name, q.total, q.status, q.date
        FROM quotes q
        JOIN clients c ON q.client_id = c.id
        WHERE q.company_id = %s AND q.status IN ('Draft', 'Sent', 'Pending', 'Accepted')
        ORDER BY q.date DESC LIMIT 5
    """, (comp_id,))
    
    recent_quotes = []
    for r in cur.fetchall():
        fmt_date = format_date(r[5], user_date_fmt)
        recent_quotes.append({
            'id': r[0], 'ref': r[1], 'client_name': r[2], 
            'total': r[3], 'status': r[4], 'date': fmt_date
        })

    # 2. UPCOMING JOBS
    cur.execute("""
        SELECT j.id, j.ref, j.site_address, c.name, j.start_date, j.status 
        FROM jobs j 
        LEFT JOIN clients c ON j.client_id = c.id 
        WHERE j.company_id = %s AND j.status = 'Scheduled' 
        ORDER BY j.start_date ASC LIMIT 5
    """, (comp_id,))
    
    upcoming_jobs = []
    for r in cur.fetchall():
        fmt_full, day_num, month_abbr = process_date(r[4], user_date_fmt)
        upcoming_jobs.append({
            'id': r[0], 'ref': r[1], 'address': r[2], 'client_name': r[3],
            'start_date_fmt': fmt_full, 'day': day_num, 'month': month_abbr
        })

    # 3. UNINVOICED JOBS
    cur.execute("""
        SELECT j.id, j.ref, c.name, j.quote_total
        FROM jobs j
        LEFT JOIN invoices i ON j.id = i.job_id
        LEFT JOIN clients c ON j.client_id = c.id
        WHERE j.company_id = %s AND j.status = 'Completed' AND i.id IS NULL
        ORDER BY j.start_date DESC LIMIT 5
    """, (comp_id,))
    
    uninvoiced_jobs = []
    for r in cur.fetchall():
        uninvoiced_jobs.append({'id': r[0], 'ref': r[1], 'client_name': r[2], 'total': r[3]})

    # --- PIPELINE ---
    cur.execute("SELECT status, COUNT(*), SUM(total) FROM quotes WHERE company_id=%s GROUP BY status", (comp_id,))
    pipe_raw = cur.fetchall()
    pipeline = {
        'Draft': {'count': 0, 'value': 0},
        'Sent': {'count': 0, 'value': 0},
        'Accepted': {'count': 0, 'value': 0},
        'Rejected': {'count': 0, 'value': 0}
    }
    for r in pipe_raw:
        if r[0] in pipeline:
            pipeline[r[0]]['count'] = r[1]
            pipeline[r[0]]['value'] = float(r[2] or 0)

    # Dropdowns
    cur.execute("SELECT id, name FROM clients WHERE company_id=%s ORDER BY name", (comp_id,))
    clients = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]
    
    cur.execute("SELECT id, reg_plate FROM vehicles WHERE company_id=%s AND status='Active'", (comp_id,))
    vehicles = [{'id': r[0], 'reg': r[1]} for r in cur.fetchall()]

    conn.close()

    return render_template('office/office_dashboard.html',
                           leads_count=leads_count,
                           pending_quotes=pending_quotes,
                           active_jobs=active_jobs,
                           unpaid_inv=unpaid_inv,
                           incoming_requests=incoming_requests,
                           upcoming_jobs=upcoming_jobs,
                           uninvoiced_jobs=uninvoiced_jobs,
                           recent_quotes=recent_quotes,
                           pipeline=pipeline,
                           clients=clients,
                           vehicles=vehicles)

@office_bp.route('/office/live-ops', methods=['GET', 'POST'])
def live_ops():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_crew':
            vehicle_id = request.form.get('vehicle_id')
            driver_id = request.form.get('driver_id')
            crew_ids = request.form.getlist('crew_ids')
            
            try:
                cur.execute("DELETE FROM vehicle_crews WHERE vehicle_id = %s", (vehicle_id,))
                
                if driver_id and driver_id != 'None':
                    cur.execute("UPDATE vehicles SET assigned_driver_id = %s WHERE id = %s", (driver_id, vehicle_id))
                else:
                    cur.execute("UPDATE vehicles SET assigned_driver_id = NULL WHERE id = %s", (vehicle_id,))

                for staff_id in crew_ids:
                    if staff_id != driver_id: 
                        cur.execute("INSERT INTO vehicle_crews (company_id, vehicle_id, staff_id) VALUES (%s, %s, %s)", (comp_id, vehicle_id, staff_id))
                
                conn.commit()
                flash("✅ Crew logistics updated.", "success")
            except Exception as e:
                conn.rollback(); flash(f"Error updating crew: {e}", "error")
            
            return redirect(url_for('office.live_ops'))

    # Fetch Data
    today = date.today()
    
    # LOGIC UPDATE: We fetch the LATEST attendance record for today.
    # We grab both clock_in and clock_out from that specific record.
    cur.execute("""
        SELECT 
            s.id, s.name, s.position, s.profile_photo, 
            vc.vehicle_id, 
            (SELECT clock_in FROM staff_attendance WHERE staff_id = s.id AND date = %s ORDER BY clock_in DESC LIMIT 1) as latest_in,
            (SELECT clock_out FROM staff_attendance WHERE staff_id = s.id AND date = %s ORDER BY clock_in DESC LIMIT 1) as latest_out,
            j.ref, j.site_address, v.reg_plate
        FROM staff s
        LEFT JOIN jobs j ON s.id = j.engineer_id AND j.status = 'In Progress'
        LEFT JOIN vehicle_crews vc ON s.id = vc.staff_id
        LEFT JOIN vehicles v ON vc.vehicle_id = v.id
        WHERE s.company_id = %s
        ORDER BY s.name ASC
    """, (today, today, comp_id))
    
    staff_status = []
    for r in cur.fetchall():
        latest_clock_in = r[5]
        latest_clock_out = r[6]
        
        # STRICT STATUS LOGIC
        # 1. Default: Offline
        status = 'Offline'
        location_text = "Not working today"

        if latest_clock_in:
            # They have clocked in at least once today
            
            if latest_clock_out is None:
                # NO clock out time found -> They are currently working
                status = 'Online'
                location_text = f"Clocked in at {format_date(latest_clock_in, '%H:%M')}"
                if r[7]: 
                    status = 'On Job'
                    location_text = f"Working on {r[7]}"
            else:
                # They HAVE a clock out time -> They are finished
                status = 'Offline'
                location_text = f"Shift Finished (Out: {format_date(latest_clock_out, '%H:%M')})"
        
        staff_status.append({
            'id': r[0], 'name': r[1], 'role': r[2], 'photo': r[3],
            'vehicle_id': r[4], 
            'clock_in': format_date(latest_clock_in, "%H:%M") if latest_clock_in else "-",
            'job_ref': r[7], 
            'location': location_text,
            'van': r[9], 'status': status
        })

    cur.execute("SELECT id, reg_plate, make_model, assigned_driver_id, tracker_url FROM vehicles WHERE company_id = %s", (comp_id,))
    fleet = []
    for v in cur.fetchall():
        fleet.append({'id': v[0], 'reg': v[1], 'model': v[2], 'driver_id': v[3], 'tracker_url': v[4]})

    conn.close()
    return render_template('office/live_ops.html', staff=staff_status, all_staff=staff_status, fleet=fleet, brand_color=config['color'], logo_url=config['logo'])
                           

@office_bp.route('/office/calendar')
def office_calendar():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    # 1. FETCH FLEET (Fixed 'None' logic)
    # COALESCE(v.assigned_driver_id, 0) ensures we don't send 'None' to HTML
    cur.execute("""
        SELECT v.id, v.reg_plate, COALESCE(v.assigned_driver_id, 0), 
               (SELECT json_agg(vc.staff_id) FROM vehicle_crews vc WHERE vc.vehicle_id = v.id)
        FROM vehicles v 
        WHERE v.company_id = %s
    """, (comp_id,))
    
    fleet = []
    for v in cur.fetchall():
        fleet.append({
            'id': v[0],
            'name': v[1],
            'driver_id': v[2], # Will be 0 if no driver, easier to handle in JS
            'crew_ids': v[3] if v[3] else []
        })

    # 2. FETCH STAFF
    # Removed "status='Active'" filter just in case your test staff aren't marked 'Active'
    cur.execute("""
        SELECT id, name, role 
        FROM staff 
        WHERE company_id=%s 
        ORDER BY name ASC
    """, (comp_id,))
    
    staff = [{'id': s[0], 'name': s[1], 'role': s[2] or 'Staff'} for s in cur.fetchall()]

    # 3. FETCH UNSCHEDULED JOBS
    cur.execute("""
        SELECT j.id, j.ref, c.name, j.description, p.postcode, j.vehicle_id, j.estimated_days
        FROM jobs j
        JOIN clients c ON j.client_id = c.id
        LEFT JOIN properties p ON j.property_id = p.id
        WHERE j.company_id = %s 
          AND (j.start_date IS NULL OR j.status = 'Pending')
        ORDER BY j.created_at DESC
    """, (comp_id,))
    
    unscheduled = []
    for j in cur.fetchall():
        days = j[6] if j[6] and j[6] > 0 else 1
        unscheduled.append({
            'id': j[0],
            'ref': j[1],
            'client': j[2],
            'desc': (j[3] or "")[:50] + "...", 
            'postcode': j[4] or "No Address",
            'pre_vehicle_id': j[5],
            'days': days,
            'duration_iso': f"P{days}D"
        })

    conn.close()

    return render_template('office/calendar.html',
                           config=config,
                           fleet=fleet,
                           staff=staff,
                           unscheduled_jobs=unscheduled)

@office_bp.route('/api/calendar/events')
def get_calendar_events():
    if not check_office_access(): return jsonify([])
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    cur.execute("""
        SELECT j.id, c.name, j.site_address, j.start_date, j.estimated_days, j.ref, j.status 
        FROM jobs j
        JOIN clients c ON j.client_id = c.id
        WHERE j.company_id = %s
    """, (comp_id,))
    
    events = []
    for r in cur.fetchall():
        start = r[3]
        end = start + timedelta(days=int(r[4] or 1))
        
        color = '#3788d8'
        if r[6] == 'Completed': color = '#28a745'
        elif r[6] == 'In Progress': color = '#ffc107'
        
        events.append({
            'id': r[0],
            'title': f"{r[1]} - {r[5]}",
            'start': start.isoformat(),
            'end': end.isoformat(),
            'color': color,
            'url': f"/office/job/{r[0]}/files"
        })
        
    conn.close()
    return jsonify(events)
    
# =========================================================
# 4. CALENDAR API ENDPOINTS (The "Engine" Room)
# =========================================================

@office_bp.route('/office/calendar/schedule-job', methods=['POST'])
def schedule_job():
    if not check_office_access(): return jsonify({'status': 'error', 'message': 'Auth failed'}), 401
    
    try:
        data = request.get_json()
        
        comp_id = session.get('company_id')
        job_id = data.get('job_id')
        date_str = data.get('date')
        vehicle_id = data.get('vehicle_id')
        lead_id = data.get('lead_id')
        force = data.get('force', False)
        
        if not job_id or not date_str:
            return jsonify({'status': 'error', 'message': 'Missing Data'}), 400

        conn = get_db(); cur = conn.cursor()
        
        # Conflict Checking Logic
        if not force:
            # Check if this job has estimated_days
            cur.execute("SELECT estimated_days FROM jobs WHERE id = %s", (job_id,))
            j_row = cur.fetchone()
            j_days = int(j_row[0] or 1)
            new_start = datetime.strptime(date_str, '%Y-%m-%d').date()
            new_end = new_start + timedelta(days=j_days - 1)
            
            # Check Vehicle Conflicts
            if vehicle_id:
                cur.execute("""
                    SELECT id, ref, start_date, estimated_days 
                    FROM jobs 
                    WHERE company_id = %s AND vehicle_id = %s AND id != %s AND status IN ('Scheduled', 'In Progress')
                """, (comp_id, vehicle_id, job_id))
                for r in cur.fetchall():
                    ex_start = r[2]
                    if isinstance(ex_start, datetime): ex_start = ex_start.date()
                    elif isinstance(ex_start, str): ex_start = datetime.strptime(ex_start, '%Y-%m-%d').date()
                    ex_end = ex_start + timedelta(days=int(r[3] or 1) - 1)
                    if (new_start <= ex_end) and (ex_start <= new_end):
                        conn.close()
                        return jsonify({'status': 'conflict', 'message': f'Vehicle is already assigned to {r[1]} on these dates.'})

            # Check Engineer Conflicts
            if lead_id:
                cur.execute("""
                    SELECT id, ref, start_date, estimated_days 
                    FROM jobs 
                    WHERE company_id = %s AND engineer_id = %s AND id != %s AND status IN ('Scheduled', 'In Progress')
                """, (comp_id, lead_id, job_id))
                for r in cur.fetchall():
                    ex_start = r[2]
                    if isinstance(ex_start, datetime): ex_start = ex_start.date()
                    elif isinstance(ex_start, str): ex_start = datetime.strptime(ex_start, '%Y-%m-%d').date()
                    ex_end = ex_start + timedelta(days=int(r[3] or 1) - 1)
                    if (new_start <= ex_end) and (ex_start <= new_end):
                        conn.close()
                        return jsonify({'status': 'conflict', 'message': f'Engineer is already assigned to {r[1]} on these dates.'})

                # Check Leave Conflicts
                cur.execute("""
                    SELECT start_date, end_date, reason
                    FROM staff_leave
                    WHERE company_id = %s AND staff_id = %s AND status = 'Approved'
                """, (comp_id, lead_id))
                for r in cur.fetchall():
                    l_start = r[0]
                    if isinstance(l_start, str): l_start = datetime.strptime(l_start, '%Y-%m-%d').date()
                    l_end = r[1]
                    if isinstance(l_end, str): l_end = datetime.strptime(l_end, '%Y-%m-%d').date()
                    if (new_start <= l_end) and (l_start <= new_end):
                        conn.close()
                        return jsonify({'status': 'conflict', 'message': f'Engineer is on leave ({r[2]}) during these dates.'})
        
        # 1. Update Job
        cur.execute("""
            UPDATE jobs 
            SET start_date = %s, vehicle_id = %s, engineer_id = %s, status = 'Scheduled'
            WHERE id = %s AND company_id = %s
        """, (date_str, vehicle_id, lead_id, job_id, comp_id))

        # 2. Update Job Crew (Optional: If you track crew per job)
        # Assuming you just need the job updated for now.
        
        conn.commit()
        conn.close()
        
        return jsonify({'status': 'success'})

    except Exception as e:
        print(f"ERROR in schedule_job: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@office_bp.route('/office/inbox')
def inbox():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    folder = request.args.get('folder', 'Inbox')
    
    conn = get_db(); cur = conn.cursor()
    
    try:
        # Ensure folder column exists
        cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS folder VARCHAR(20) DEFAULT 'Inbox';")
        conn.commit()
        
        cur.execute("""
            SELECT id, msg_id, sender, subject, body, date, client_id, status 
            FROM emails 
            WHERE company_id = %s AND folder = %s 
            ORDER BY date DESC LIMIT 50
        """, (comp_id, folder))
        
        emails = []
        for r in cur.fetchall():
            emails.append({
                'id': r[0], 'msg_id': r[1], 'sender': r[2], 'subject': r[3],
                'body': r[4], 'date': r[5], 'client_id': r[6], 'status': r[7]
            })
            
        # Get counts
        cur.execute("SELECT COUNT(*) FROM emails WHERE company_id = %s AND folder = 'Inbox'", (comp_id,))
        inbox_count = cur.fetchone()[0]
    except Exception as e:
        emails = []
        inbox_count = 0
    finally:
        conn.close()
        
    return render_template('office/inbox.html', emails=emails, current_folder=folder, inbox_count=inbox_count)

@office_bp.route('/office/api/client_files')
def api_client_files():
    if not check_office_access(): return jsonify({'error': 'Unauthorized'}), 401
    
    email = request.args.get('email')
    if not email: return jsonify([])
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    try:
        # Find client_id by email
        cur.execute("SELECT id FROM clients WHERE email = %s AND company_id = %s", (email, comp_id))
        client_row = cur.fetchone()
        
        if not client_row:
            return jsonify([])
            
        client_id = client_row[0]
        
        # Fetch files from job_evidence related to this client
        cur.execute("""
            SELECT f.id, f.file_type, f.filepath, j.ref
            FROM job_evidence f
            JOIN jobs j ON f.job_id = j.id
            WHERE j.client_id = %s AND j.company_id = %s
            ORDER BY f.uploaded_at DESC LIMIT 20
        """, (client_id, comp_id))
        
        files = []
        for r in cur.fetchall():
            # Extract filename from path
            path = r[2] or ""
            filename = path.split('/')[-1] if '/' in path else path
            files.append({
                'id': r[0],
                'type': r[1],
                'path': path,
                'name': f"{r[3]} - {filename}"
            })
            
        return jsonify(files)
    except Exception as e:
        print(f"Error fetching client files: {e}")
        return jsonify([])
    finally:
        conn.close()

@office_bp.route('/office/inbox/sync')
def sync_emails():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    from services.imap_engine import fetch_emails
    fetched = fetch_emails(comp_id)
    if fetched:
        flash(f"Successfully synced {len(fetched)} new emails.", "success")
    else:
        flash("No new emails found or IMAP not configured.", "info")
    return redirect(url_for('office.inbox'))

@office_bp.route('/office/api/email/<int:email_id>/summarize')
def api_email_summarize(email_id):
    if not check_office_access(): return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db(); cur = conn.cursor()
    try:
        comp_id = session.get('company_id')
        cur.execute("SELECT body FROM emails WHERE id = %s AND company_id = %s", (email_id, comp_id))
        row = cur.fetchone()
        if not row: return jsonify({'error': 'Email not found'}), 404
        
        body = row[0]
        
        # 1. Fetch AI Keys
        cur.execute("SELECT key, value FROM settings WHERE company_id = %s AND key IN ('openai_api_key', 'anthropic_api_key', 'google_ai_key')", (comp_id,))
        keys = {r[0]: r[1] for r in cur.fetchall()}
        
        from utils.encryption import get_encryptor
        encryptor = get_encryptor()
        
        summary = "AI summarization is not configured. Please add an OpenAI, Anthropic, or Google AI API key in Settings > Integrations."
        
        if keys.get('openai_api_key'):
            try:
                import openai
                client = openai.OpenAI(api_key=encryptor.decrypt(keys['openai_api_key']))
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant. Summarize the following client email in 1-2 short sentences."},
                        {"role": "user", "content": body}
                    ]
                )
                summary = resp.choices[0].message.content
            except Exception as e:
                summary = f"OpenAI Error: {e}"
                
        elif keys.get('anthropic_api_key'):
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=encryptor.decrypt(keys['anthropic_api_key']))
                resp = client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=150,
                    messages=[
                        {"role": "user", "content": f"Summarize the following client email in 1-2 short sentences:\n\n{body}"}
                    ]
                )
                summary = resp.content[0].text
            except Exception as e:
                summary = f"Anthropic Error: {e}"
                
        elif keys.get('google_ai_key'):
            try:
                import google.generativeai as genai
                genai.configure(api_key=encryptor.decrypt(keys['google_ai_key']))
                model = genai.GenerativeModel('gemini-1.5-flash')
                resp = model.generate_content(f"Summarize the following client email in 1-2 short sentences:\n\n{body}")
                summary = resp.text
            except Exception as e:
                summary = f"Google AI Error: {e}"
                
        return jsonify({'summary': summary})
    finally:
        conn.close()

@office_bp.route('/office/inbox/send', methods=['POST'])
def send_office_email():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    to_email = request.form.get('to_email')
    subject = request.form.get('subject')
    body = request.form.get('body')
    
    if not to_email or not subject or not body:
        flash("❌ All fields are required to send an email.", "error")
        return redirect(url_for('office.inbox'))
        
    # Check for attachments
    from werkzeug.utils import secure_filename
    import os
    
    local_file = request.files.get('local_attachment')
    db_file_path = request.form.get('db_attachment')
    
    attachment_path = None
    if local_file and local_file.filename:
        filename = secure_filename(local_file.filename)
        temp_dir = os.path.join(current_app.static_folder, 'uploads', 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, filename)
        local_file.save(temp_path)
        attachment_path = temp_path
    elif db_file_path:
        # Convert web path to absolute path
        clean_path = db_file_path.lstrip('/')
        if clean_path.startswith('static/'):
            clean_path = clean_path.replace('static/', '', 1)
        attachment_path = os.path.join(current_app.static_folder, clean_path)
        
    from email_service import send_company_email
    success, msg = send_company_email(comp_id, to_email, subject, body, pdf_path=attachment_path)
    
    if success:
        # Log to 'Sent' folder
        conn = get_db(); cur = conn.cursor()
        try:
            # Ensure folder column exists
            cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS folder VARCHAR(20) DEFAULT 'Inbox';")
            
            # Try to find client_id
            cur.execute("SELECT id FROM clients WHERE email = %s AND company_id = %s", (to_email, comp_id))
            client_row = cur.fetchone()
            client_id = client_row[0] if client_row else None
            
            from datetime import datetime
            cur.execute("""
                INSERT INTO emails (company_id, msg_id, sender, subject, body, date, client_id, status, folder)
                VALUES (%s, %s, %s, %s, %s, NOW(), %s, 'Read', 'Sent')
            """, (comp_id, f"sent-{datetime.now().timestamp()}", "You", subject, body, client_id))
            conn.commit()
        except Exception as e:
            print(f"Error logging sent email: {e}")
        finally:
            conn.close()
            
        flash("✅ Email sent successfully!", "success")
    else:
        flash(f"❌ {msg}", "error")
        
    return redirect(url_for('office.inbox'))

@office_bp.route('/office/api/email/<int:email_id>/draft')
def api_email_draft(email_id):
    if not check_office_access(): return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db(); cur = conn.cursor()
    try:
        comp_id = session.get('company_id')
        cur.execute("SELECT body FROM emails WHERE id = %s AND company_id = %s", (email_id, comp_id))
        row = cur.fetchone()
        if not row: return jsonify({'error': 'Email not found'}), 404
        
        body = row[0]
        
        # 1. Fetch AI Keys
        cur.execute("SELECT key, value FROM settings WHERE company_id = %s AND key IN ('openai_api_key', 'anthropic_api_key', 'google_ai_key')", (comp_id,))
        keys = {r[0]: r[1] for r in cur.fetchall()}
        
        from utils.encryption import get_encryptor
        encryptor = get_encryptor()
        
        draft = "Thank you for getting in touch. We have received your message and will respond shortly.\n\nBest regards,\nThe Office Team"
        
        system_prompt = f"You are an assistant for a service company named {session.get('company_name', 'our company')}. Draft a professional, polite, and concise reply to the following client email. Only return the email body without subject line."
        
        if keys.get('openai_api_key'):
            try:
                import openai
                client = openai.OpenAI(api_key=encryptor.decrypt(keys['openai_api_key']))
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": body}
                    ]
                )
                draft = resp.choices[0].message.content
            except: pass
                
        elif keys.get('anthropic_api_key'):
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=encryptor.decrypt(keys['anthropic_api_key']))
                resp = client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=300,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": body}
                    ]
                )
                draft = resp.content[0].text
            except: pass
                
        elif keys.get('google_ai_key'):
            try:
                import google.generativeai as genai
                genai.configure(api_key=encryptor.decrypt(keys['google_ai_key']))
                model = genai.GenerativeModel('gemini-1.5-flash')
                resp = model.generate_content(f"{system_prompt}\n\nClient Email:\n{body}")
                draft = resp.text
            except: pass
                
        return jsonify({'draft': draft})
    finally:
        conn.close()

# B. LOAD CALENDAR DATA (Show the bars on the calendar)
@office_bp.route('/office/calendar/data')
def calendar_data():
    if not check_office_access(): return jsonify([])
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    # Fetch Scheduled Jobs
    # We fetch estimated_days to make the bar stretch across multiple days
    cur.execute("""
        SELECT j.id, j.ref, c.name, j.start_date, j.estimated_days, v.reg_plate, j.status
        FROM jobs j
        JOIN clients c ON j.client_id = c.id
        LEFT JOIN vehicles v ON j.vehicle_id = v.id
        WHERE j.company_id = %s 
          AND j.status IN ('Scheduled', 'In Progress', 'Completed')
          AND j.start_date IS NOT NULL
    """, (comp_id,))
    
    events = []
    for row in cur.fetchall():
        # Logic to handle Multi-Day Jobs
        start_date = row[3] # '2026-01-23'
        days = row[4] if row[4] and row[4] > 0 else 1
        
        # Calculate End Date for FullCalendar (Start + Days)
        try:
            dt_start = datetime.strptime(start_date, '%Y-%m-%d')
            dt_end = dt_start + timedelta(days=int(days))
            end_date = dt_end.strftime('%Y-%m-%d')
        except:
            end_date = start_date # Fallback if date is invalid

        # Color Coding
        color = '#0d6efd' # Blue (Scheduled)
        if row[6] == 'In Progress': color = '#ffc107' # Orange
        if row[6] == 'Completed': color = '#198754' # Green

        events.append({
            'id': row[0],
            'title': f"{row[1]} - {row[2]} ({row[5] or 'No Van'})",
            'start': start_date,
            'end': end_date,
            'color': color,
            'allDay': True,
            'url': f"/office/job/{row[0]}" # Click to open job
        })
        
    conn.close()
    return jsonify(events)

# C. HANDLE DRAG-TO-MOVE (Reschedule logic)
@office_bp.route('/office/calendar/reschedule-job', methods=['POST'])
def reschedule_job_drag():
    if not check_office_access(): return jsonify({'status': 'error'}), 401
    
    data = request.get_json()
    job_id = data.get('job_id')
    new_date = data.get('date') # '2026-01-25'
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("UPDATE jobs SET start_date = %s WHERE id = %s AND company_id = %s", 
                   (new_date, job_id, session.get('company_id')))
        conn.commit()
        return jsonify({'status': 'success'})
    except:
        return jsonify({'status': 'error'})
    finally:
        conn.close()

    # =========================================================
# FLEET MANAGEMENT (Office Side)
# =========================================================
@office_bp.route('/office/fleet', methods=['GET', 'POST'])
def office_fleet():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    # --- HANDLE POST ACTIONS (Assign Crew / Add Receipt) ---
    if request.method == 'POST':
        action = request.form.get('action')
        
        try:
            if action == 'assign_crew':
                veh_id = request.form.get('vehicle_id')
                driver_id = request.form.get('driver_id')
                if driver_id == 'None': driver_id = None
                
                # 1. Update Driver
                cur.execute("UPDATE vehicles SET assigned_driver_id = %s WHERE id = %s AND company_id = %s", (driver_id, veh_id, comp_id))
                
                # 2. Update Crew (Plural Table)
                crew_ids = request.form.getlist('crew_ids')
                cur.execute("DELETE FROM vehicle_crews WHERE vehicle_id = %s", (veh_id,))
                for staff_id in crew_ids:
                    if str(staff_id) != str(driver_id):
                        cur.execute("INSERT INTO vehicle_crews (company_id, vehicle_id, staff_id) VALUES (%s, %s, %s)", (comp_id, veh_id, staff_id))
                flash("✅ Crew updated.")

            elif action == 'add_log':
                # Logic for the "Receipts & Logs" tab in fleet_management.html
                veh_id = request.form.get('vehicle_id')
                l_type = request.form.get('log_type')
                desc = request.form.get('description')
                cost = request.form.get('cost') or 0
                l_date = request.form.get('date')
                
                # File Upload
                file_path = None
                if 'receipt_file' in request.files:
                    f = request.files['receipt_file']
                    if f and f.filename != '':
                        from werkzeug.utils import secure_filename
                        import os
                        # Ensure folder exists
                        save_dir = os.path.join('static', 'uploads', f"company_{comp_id}", 'fleet')
                        os.makedirs(save_dir, exist_ok=True)
                        
                        fname = secure_filename(f"LOG_{veh_id}_{f.filename}")
                        f.save(os.path.join(save_dir, fname))
                        file_path = f"/uploads/company_{comp_id}/fleet/{fname}"

                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, date, type, description, cost, receipt_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (comp_id, veh_id, l_date, l_type, desc, cost, file_path))
                flash("✅ Log entry added.")

            conn.commit()
        except Exception as e:
            conn.rollback()
            flash(f"Error: {e}", "error")

    # --- FETCH DATA ---
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.status, 
               v.assigned_driver_id, s.name, 
               v.mot_expiry, v.tax_expiry, v.ins_expiry, v.service_expiry
        FROM vehicles v
        LEFT JOIN staff s ON v.assigned_driver_id = s.id
        WHERE v.company_id = %s
        ORDER BY v.reg_plate
    """, (comp_id,))
    
    vehicles_raw = cur.fetchall()
    vehicles = []
    
    # Fetch All Staff for Dropdowns
    cur.execute("SELECT id, name FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    all_staff = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]

    for r in vehicles_raw:
        v_id = r[0]
        
        # 1. Fetch Crew
        cur.execute("""
            SELECT s.name FROM vehicle_crews vc
            JOIN staff s ON vc.staff_id = s.id
            WHERE vc.vehicle_id = %s
        """, (v_id,))
        crew = [{'name': row[0]} for row in cur.fetchall()]

        # 2. Fetch History (Logs) - Required for Office View
        cur.execute("""
            SELECT date, type, description, cost, receipt_path 
            FROM maintenance_logs 
            WHERE vehicle_id = %s 
            ORDER BY date DESC LIMIT 5
        """, (v_id,))
        history = [{'date': h[0], 'type': h[1], 'desc': h[2], 'cost': h[3], 'receipt': h[4]} for h in cur.fetchall()]

        vehicles.append({
            'id': v_id,
            'reg_number': r[1],  # Using reg_number here because your fleet_management.html might still use it (check below)
            'reg_plate': r[1],   # sending both to be safe
            'make_model': r[2],
            'status': r[3],
            'assigned_driver_id': r[4],
            'driver_name': r[5],
            'mot_expiry': r[6], 'tax_expiry': r[7], 'ins_expiry': r[8], 'service_expiry': r[9],
            'crew': crew,
            'history': history
        })

    conn.close()
    
    # Note: Ensure this matches the file you uploaded: 'office/fleet_management.html'
    return render_template('office/fleet_management.html', 
                           vehicles=vehicles, 
                           staff=all_staff,  # Template expects 'staff' loop for dropdowns
                           all_staff=all_staff, # Sending both just in case
                           today=date.today())

# 2. FIX: API FOR PROPERTIES (Dropdown Population)
# =========================================================
@office_bp.route('/api/client/<int:client_id>/properties')
def get_client_properties(client_id):
    if not check_office_access(): return jsonify([])
    
    conn = get_db(); cur = conn.cursor()
    # Fetch properties for this client
    cur.execute("""
        SELECT id, address_line1, postcode 
        FROM properties 
        WHERE client_id = %s AND status = 'Active'
        ORDER BY address_line1
    """, (client_id,))
    
    props = [{'id': r[0], 'address': f"{r[1]}, {r[2]}"} for r in cur.fetchall()]
    conn.close()
    
    return jsonify(props)

# =========================================================
# 3. FIX: RAMS PDF GENERATION
# =========================================================
@office_bp.route('/office/job/<int:job_id>/rams/pdf')
def generate_job_rams(job_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    # Check if a RAMS exists
    conn = get_db(); cur = conn.cursor()
    comp_id = session.get('company_id')
    cur.execute("SELECT pdf_path FROM job_rams WHERE job_id = %s AND company_id = %s ORDER BY created_at DESC LIMIT 1", (job_id, comp_id))
    rams_row = cur.fetchone()
    conn.close()
    
    if rams_row and rams_row[0]:
        # Existing PDF
        import os
        from flask import current_app, send_from_directory
        file_path = os.path.join(current_app.static_folder, 'uploads', 'documents')
        return send_from_directory(file_path, rams_row[0])
    
    # Generate new style via the create route
    return redirect(url_for('pdf.create_rams_form', job_id=job_id))

@office_bp.route('/office/job/<int:job_id>/materials/pdf')
def job_materials_pdf(job_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Job Details + Property Address
    cur.execute("""
        SELECT j.ref, p.address_line1, p.postcode, j.site_address, c.name 
        FROM jobs j 
        LEFT JOIN properties p ON j.property_id = p.id 
        LEFT JOIN clients c ON j.client_id = c.id
        WHERE j.id = %s AND j.company_id = %s
    """, (job_id, comp_id))
    job = cur.fetchone()
    if not job: 
        conn.close()
        return "Job not found", 404
        
    delivery_address = f"{job[1]}, {job[2]}" if job[1] else (job[3] or "No delivery address logged")
    
    # 2. Fetch Materials
    cur.execute("SELECT description, quantity FROM job_materials WHERE job_id = %s", (job_id,))
    rows = cur.fetchall()
    
    # 3. Format items
    items = [{'desc': r[0], 'qty': r[1], 'supplier': 'General'} for r in rows]
    conn.close()
    
    # 4. Prepare Data for PDF
    context = {
        'config': config,
        'ref': job[0],
        'date': date.today().strftime('%d/%m/%Y'),
        'address': delivery_address,
        'client_name': job[4],
        'items': items,
        'grouped_items': None
    }
    
    # 5. Generate and Return PDF
    from services.pdf_generator import generate_pdf
    return generate_pdf('office/pdf_materials.html', context, f"Materials_Delivery_{job[0]}.pdf")

@office_bp.route('/office/job/<int:job_id>/materials/email', methods=['POST'])
def email_materials_supplier(job_id):
    if not check_office_access(): return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    supplier_email = data.get('email')
    if not supplier_email: return jsonify({'error': 'No email provided'}), 400
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    try:
        cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
        settings = {row[0]: row[1] for row in cur.fetchall()}
        
        if 'smtp_host' not in settings:
            return jsonify({'error': 'SMTP not configured'}), 400

        cur.execute("""
            SELECT j.ref, p.address_line1, p.postcode, j.site_address, c.name 
            FROM jobs j 
            LEFT JOIN properties p ON j.property_id = p.id 
            LEFT JOIN clients c ON j.client_id = c.id
            WHERE j.id = %s AND j.company_id = %s
        """, (job_id, comp_id))
        job = cur.fetchone()
        delivery_address = f"{job[1]}, {job[2]}" if job[1] else (job[3] or "No delivery address logged")

        cur.execute("SELECT description, quantity FROM job_materials WHERE job_id = %s", (job_id,))
        items = [{'desc': r[0], 'qty': r[1], 'supplier': 'General'} for r in cur.fetchall()]
        
        config = get_site_config(comp_id)
        context = {
            'config': config,
            'ref': job[0],
            'date': date.today().strftime('%d/%m/%Y'),
            'address': delivery_address,
            'client_name': job[4],
            'items': items,
            'grouped_items': None
        }
        
        from services.pdf_generator import generate_pdf
        filename = f"Materials_{job[0]}.pdf"
        pdf_path = generate_pdf('office/pdf_materials.html', context, filename)

        import base64
        attachment_b64 = None
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as pdf_file:
                attachment_b64 = base64.b64encode(pdf_file.read()).decode('utf-8')

        from tasks import send_tenant_email_task

        subject = f"Material Order - Ref: {job[0]}"
        body_html = f"Please find attached the material order for delivery.<br><br>Delivery Address:<br>{delivery_address}<br><br>Thank you,<br>{session.get('company_name')}"

        send_tenant_email_task.delay(
            company_id=comp_id,
            recipient_email=supplier_email,
            subject=subject,
            body_html=body_html,
            attachment_path=pdf_path,
            attachment_b64=attachment_b64,
            attachment_name=filename
        )
        
        return jsonify({'success': 'Email queued successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
