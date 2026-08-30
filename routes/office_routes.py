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

from utils.date_utils import format_date

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
    # Modified to show if it's from a partner, with tenant & client contact details and booked job schedule info
    cur.execute("""
        SELECT sr.id, sr.priority, 
               COALESCE(p.address_line1, sr.partner_address_snapshot), 
               sr.issue_description, 
               COALESCE(c.name, 'Partner Network Job'), 
               sr.status, sr.photo_path, sr.created_at,
               sr.partner_company_id,
               sr.parent_request_id,
               c.phone,
               p.tenant_name,
               p.tenant_phone,
               p.key_code,
               j.id as job_id,
               j.ref as job_ref,
               j.start_date as scheduled_date,
               st.name as engineer_name
        FROM service_requests sr
        LEFT JOIN properties p ON sr.property_id = p.id
        LEFT JOIN clients c ON sr.client_id = c.id
        LEFT JOIN LATERAL (
            SELECT id, ref, start_date, engineer_id 
            FROM jobs 
            WHERE service_request_id = sr.id 
            ORDER BY id DESC LIMIT 1
        ) j ON true
        LEFT JOIN staff st ON j.engineer_id = st.id
        WHERE sr.company_id = %s AND sr.status != 'Completed'
        ORDER BY sr.created_at DESC
    """, (comp_id,))
    
    raw_reqs = cur.fetchall()
    requests = []
    for r in raw_reqs:
        sched_date_str = format_date(r[16]) if r[16] else ''
        requests.append({
            'id': r[0], 'severity': r[1], 'property_address': r[2],
            'issue_description': r[3], 'client_name': r[4], 'status': r[5],
            'photo_path': r[6], 'date': r[7].strftime('%d/%m/%Y %H:%M') if r[7] else '',
            'client_phone': r[10] or '',
            'tenant_name': r[11] or '',
            'tenant_phone': r[12] or '',
            'key_code': r[13] or '',
            'job_id': r[14],
            'job_ref': r[15],
            'scheduled_date': sched_date_str,
            'engineer_name': r[17] or ''
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

    pass
    
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

@office_bp.route('/office/create-work-order', methods=['POST'])
def create_work_order():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    req_id = request.form.get('request_id')
    staff_id = request.form.get('assigned_staff_id')
    schedule_date = request.form.get('schedule_date')
    
    if not req_id or not staff_id or not schedule_date:
        flash("❌ Missing required fields for dispatch.", "error")
        return redirect(url_for('office.service_desk'))
        
    from utils.db_utils import db_transaction
    with db_transaction() as cur:
        # 1. Update the Service Request status
        cur.execute("UPDATE service_requests SET status = 'Scheduled' WHERE id = %s AND company_id = %s", (req_id, comp_id))
        
        # 2. Get details from the service request to create a job
        cur.execute("""
            SELECT client_id, property_id, issue_description, priority 
            FROM service_requests 
            WHERE id = %s AND company_id = %s
        """, (req_id, comp_id))
        row = cur.fetchone()
        
        if row:
            client_id, prop_id, desc, priority = row
            
            # Cross-reference Pricing Engine to calculate realistic initial budget
            from services.pricing_engine import calculate_service_request_estimate, get_effective_vehicle_gang_cost
            est_data = calculate_service_request_estimate(cur, comp_id, desc, prop_id)
            initial_budget = est_data.get('estimated_price', 0.0)
            
            # Find assigned vehicle for this engineer / company
            veh_id, _, _ = get_effective_vehicle_gang_cost(cur, comp_id, engineer_id=staff_id)

            # Generate a JOB reference
            cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id = %s", (comp_id,))
            job_count = cur.fetchone()[0] + 1000
            job_ref = f"JOB-{job_count}"
            
            # 3. Create the Job with pre-populated budget & assigned gang vehicle
            cur.execute("""
                INSERT INTO jobs (
                    company_id, client_id, property_id, ref, description, 
                    status, start_date, engineer_id, vehicle_id, quote_total, estimated_days, service_request_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, 'Scheduled', %s, %s, %s, %s, 1, %s, NOW())
            """, (comp_id, client_id, prop_id, job_ref, desc, schedule_date, staff_id, veh_id, initial_budget, req_id))
            
            flash(f"✅ Job '{job_ref}' scheduled with estimated budget £{initial_budget:.2f}!", "success")
        else:
            flash("❌ Original request not found.", "error")
            
    return redirect(url_for('office.service_desk'))

@office_bp.route('/office/dispatch-to-partner', methods=['POST'])
def dispatch_to_partner():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    req_id = request.form.get('request_id')
    partner_id = request.form.get('partner_company_id')
    
    if not partner_id:
        flash("❌ No partner selected.", "error")
        return redirect(url_for('office.service_desk'))
        
    from utils.db_utils import db_transaction
    with db_transaction() as cur:
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

        flash("✅ Job successfully dispatched to partner network!", "success")
        
    return redirect(url_for('office.service_desk'))

@office_bp.route('/office-hub')
def office_dashboard():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    
    from utils.date_utils import get_date_fmt_str
    user_date_fmt = get_date_fmt_str(comp_id)

    from services.dashboard_service import get_office_dashboard_data
    data = get_office_dashboard_data(comp_id, user_date_fmt)

    return render_template('office/office_dashboard.html',
                           leads_count=data.get('leads_count', 0),
                           pending_quotes=data.get('pending_quotes', 0),
                           active_jobs=data.get('active_jobs', 0),
                           unpaid_inv=data.get('unpaid_inv', 0),
                           incoming_requests=data.get('incoming_requests', []),
                           upcoming_jobs=data.get('upcoming_jobs', []),
                           uninvoiced_jobs=data.get('uninvoiced_jobs', []),
                           recent_quotes=data.get('recent_quotes', []),
                           pipeline=data.get('pipeline', {}),
                           clients=data.get('clients', []),
                           vehicles=data.get('vehicles', []))

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

    pass
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
        SELECT j.id, j.ref, c.name, COALESCE(q.job_title, j.description, 'Job') as title, 
               COALESCE(p.postcode, p.address_line1, j.site_address, 'No Address') as location, 
               j.vehicle_id, j.estimated_days, j.description
        FROM jobs j
        JOIN clients c ON j.client_id = c.id
        LEFT JOIN quotes q ON j.quote_id = q.id
        LEFT JOIN properties p ON j.property_id = p.id
        WHERE j.company_id = %s 
          AND (j.start_date IS NULL OR j.status IN ('Pending', 'Accepted'))
          AND j.status NOT IN ('Completed', 'Cancelled')
        ORDER BY j.created_at DESC
    """, (comp_id,))
    
    unscheduled = []
    for j in cur.fetchall():
        days = j[6] if j[6] and j[6] > 0 else 1
        title = j[3] or f"Job {j[1]}"
        desc_preview = j[7] or ""
        if desc_preview == title: desc_preview = ""
        unscheduled.append({
            'id': j[0],
            'ref': j[1],
            'client': j[2],
            'title': title,
            'desc': (desc_preview[:60] + "...") if len(desc_preview) > 60 else desc_preview, 
            'postcode': j[4] or "No Address",
            'pre_vehicle_id': j[5],
            'days': days,
            'duration_iso': f"P{int(round(days))}D" if days >= 1 else "PT4H"
        })

    pass

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
        
    pass
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

        clean_date = date_str[:10] if date_str else None
        conn = get_db(); cur = conn.cursor()
        
        # Conflict Checking Logic
        if not force:
            # Check if this job has estimated_days
            cur.execute("SELECT estimated_days FROM jobs WHERE id = %s", (job_id,))
            j_row = cur.fetchone()
            j_days = int(j_row[0] or 1) if j_row else 1
            new_start = datetime.strptime(clean_date, '%Y-%m-%d').date()
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
                    elif isinstance(ex_start, str): ex_start = datetime.strptime(ex_start[:10], '%Y-%m-%d').date()
                    ex_end = ex_start + timedelta(days=int(r[3] or 1) - 1)
                    if (new_start <= ex_end) and (ex_start <= new_end):
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
                    elif isinstance(ex_start, str): ex_start = datetime.strptime(ex_start[:10], '%Y-%m-%d').date()
                    ex_end = ex_start + timedelta(days=int(r[3] or 1) - 1)
                    if (new_start <= ex_end) and (ex_start <= new_end):
                        return jsonify({'status': 'conflict', 'message': f'Engineer is already assigned to {r[1]} on these dates.'})

                # Check Leave Conflicts
                cur.execute("""
                    SELECT start_date, end_date, reason
                    FROM staff_leave
                    WHERE company_id = %s AND staff_id = %s AND status = 'Approved'
                """, (comp_id, lead_id))
                for r in cur.fetchall():
                    l_start = r[0]
                    if isinstance(l_start, str): l_start = datetime.strptime(l_start[:10], '%Y-%m-%d').date()
                    l_end = r[1]
                    if isinstance(l_end, str): l_end = datetime.strptime(l_end[:10], '%Y-%m-%d').date()
                    if (new_start <= l_end) and (l_start <= new_end):
                        return jsonify({'status': 'conflict', 'message': f'Engineer is on leave ({r[2]}) during these dates.'})
        
        # 1. Update Job
        cur.execute("""
            UPDATE jobs 
            SET start_date = %s, vehicle_id = %s, engineer_id = %s, status = 'Scheduled'
            WHERE id = %s AND company_id = %s
        """, (clean_date, vehicle_id or None, lead_id or None, job_id, comp_id))
        
        conn.commit()
        return jsonify({'status': 'success'})

    except Exception as e:
        print(f"ERROR in schedule_job: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
        print(f"ERROR in schedule_job: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@office_bp.route('/office/inbox')
def inbox():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    folder = request.args.get('folder', 'Inbox')
    
    conn = get_db(); cur = conn.cursor()
    
    try:
        # Ensure table and columns exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS emails (
                id SERIAL PRIMARY KEY,
                company_id INTEGER,
                msg_id VARCHAR(255),
                sender VARCHAR(255),
                recipient VARCHAR(255),
                subject VARCHAR(255),
                body TEXT,
                date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                client_id INTEGER,
                status VARCHAR(50) DEFAULT 'Unread',
                folder VARCHAR(20) DEFAULT 'Inbox',
                UNIQUE(company_id, msg_id)
            )
        """)
        cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS folder VARCHAR(20) DEFAULT 'Inbox';")
        cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS recipient VARCHAR(255);")
        conn.commit()
        
        cur.execute("""
            SELECT e.id, e.msg_id, e.sender, e.recipient, e.subject, e.body, e.date, e.client_id, e.status, e.folder, c.name as client_name
            FROM emails e
            LEFT JOIN clients c ON e.client_id = c.id
            WHERE e.company_id = %s AND e.folder = %s 
            ORDER BY e.date DESC LIMIT 100
        """, (comp_id, folder))
        
        emails = []
        for r in cur.fetchall():
            emails.append({
                'id': r[0], 'msg_id': r[1], 'sender': r[2], 'recipient': r[3], 'subject': r[4],
                'body': r[5], 'date': r[6], 'client_id': r[7], 'status': r[8], 'folder': r[9],
                'client_name': r[10]
            })
            
        # Get folder counts
        cur.execute("SELECT COUNT(*) FROM emails WHERE company_id = %s AND folder = 'Inbox'", (comp_id,))
        inbox_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM emails WHERE company_id = %s AND folder = 'Sent'", (comp_id,))
        sent_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM emails WHERE company_id = %s AND folder = 'Drafts'", (comp_id,))
        drafts_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM emails WHERE company_id = %s AND folder = 'Trash'", (comp_id,))
        trash_count = cur.fetchone()[0]
    except Exception as e:
        print(f"Error in office.inbox: {e}")
        emails = []
        inbox_count = sent_count = drafts_count = trash_count = 0
    finally:
        pass
        
    return render_template(
        'office/inbox.html',
        emails=emails,
        current_folder=folder,
        inbox_count=inbox_count,
        sent_count=sent_count,
        drafts_count=drafts_count,
        trash_count=trash_count
    )

@office_bp.route('/office/api/client_files')
def api_client_files():
    if not check_office_access(): return jsonify({'error': 'Unauthorized'}), 401
    
    email = request.args.get('email')
    if not email: return jsonify([])
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    try:
        # Find client_id by email
        cur.execute("SELECT id FROM clients WHERE LOWER(email) = LOWER(%s) AND company_id = %s", (email.strip(), comp_id))
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
        pass

@office_bp.route('/office/inbox/sync')
def sync_emails():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    from services.imap_engine import fetch_emails
    result = fetch_emails(comp_id)
    if result.get('success'):
        if result.get('count', 0) > 0:
            flash(f"✅ Successfully synced {result['count']} new email(s) from IMAP.", "success")
        else:
            flash("Inbox is up to date (no new unread emails found).", "info")
    else:
        flash(f"⚠️ {result.get('message', 'IMAP sync failed.')}", "warning")
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
        pass

@office_bp.route('/office/inbox/send', methods=['POST'])
def send_office_email():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    to_email = (request.form.get('to_email') or '').strip()
    subject = (request.form.get('subject') or '').strip()
    body = (request.form.get('body') or '').strip()
    action = request.form.get('action', 'send')
    
    if not to_email:
        flash("❌ Recipient email address is required.", "error")
        return redirect(url_for('office.inbox'))

    # If user wants to save as draft
    if action == 'save_draft':
        conn = get_db(); cur = conn.cursor()
        try:
            import time, uuid
            msg_id = f"draft-{int(time.time())}-{uuid.uuid4().hex[:8]}"
            cur.execute("""
                INSERT INTO emails (company_id, msg_id, sender, recipient, subject, body, date, status, folder)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), 'Read', 'Drafts')
            """, (comp_id, msg_id, "You", to_email, subject or "(No Subject)", body))
            conn.commit()
            flash("📝 Draft saved successfully.", "success")
        except Exception as e:
            flash(f"Error saving draft: {e}", "error")
        return redirect(url_for('office.inbox', folder='Drafts'))
        
    if not subject or not body:
        flash("❌ Subject and message body are required to send an email.", "error")
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
        clean_path = db_file_path.lstrip('/')
        if clean_path.startswith('static/'):
            clean_path = clean_path.replace('static/', '', 1)
        attachment_path = os.path.join(current_app.static_folder, clean_path)
        
    from email_service import send_company_email
    success, msg = send_company_email(comp_id, to_email, subject, body, pdf_path=attachment_path)
    
    if success:
        flash("✅ Email sent successfully!", "success")
    else:
        flash(f"❌ {msg}", "error")
        
    return redirect(url_for('office.inbox'))

@office_bp.route('/office/api/email/<int:email_id>/move', methods=['POST'])
def api_email_move(email_id):
    if not check_office_access(): return jsonify({'error': 'Unauthorized'}), 401
    comp_id = session.get('company_id')
    data = request.get_json(silent=True) or {}
    target_folder = data.get('folder', 'Trash')
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT folder FROM emails WHERE id = %s AND company_id = %s", (email_id, comp_id))
        row = cur.fetchone()
        if not row:
            return jsonify({'error': 'Email not found'}), 404
            
        current_f = row[0]
        if target_folder == 'delete_permanent' or (current_f == 'Trash' and target_folder == 'Trash'):
            cur.execute("DELETE FROM emails WHERE id = %s AND company_id = %s", (email_id, comp_id))
            conn.commit()
            return jsonify({'success': True, 'action': 'deleted'})
        else:
            cur.execute("UPDATE emails SET folder = %s WHERE id = %s AND company_id = %s", (target_folder, email_id, comp_id))
            conn.commit()
            return jsonify({'success': True, 'action': 'moved', 'folder': target_folder})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500

@office_bp.route('/office/api/email/<int:email_id>/status', methods=['POST'])
def api_email_status(email_id):
    if not check_office_access(): return jsonify({'error': 'Unauthorized'}), 401
    comp_id = session.get('company_id')
    data = request.get_json(silent=True) or {}
    new_status = data.get('status', 'Read')
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("UPDATE emails SET status = %s WHERE id = %s AND company_id = %s", (new_status, email_id, comp_id))
        conn.commit()
        return jsonify({'success': True, 'status': new_status})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500

@office_bp.route('/api/document/<string:table_name>/<int:doc_id>/toggle-visibility', methods=['POST'])
def api_toggle_document_visibility(table_name, doc_id):
    if not check_office_access(): return jsonify({'error': 'Unauthorized'}), 401
    
    valid_tables = {'job_evidence', 'property_documents', 'quote_documents'}
    if table_name not in valid_tables:
        return jsonify({'error': 'Invalid table'}), 400
        
    comp_id = session.get('company_id')
    
    conn = get_db(); cur = conn.cursor()
    try:
        # Check current state
        if table_name == 'job_evidence':
            cur.execute("SELECT visible_to_client FROM job_evidence WHERE id = %s", (doc_id,))
        else:
            cur.execute(f"SELECT visible_to_client FROM {table_name} WHERE id = %s AND company_id = %s", (doc_id, comp_id))
            
        row = cur.fetchone()
        if not row:
            pass
            return jsonify({'error': 'Document not found'}), 404
            
        new_state = not row[0]
        
        if table_name == 'job_evidence':
            cur.execute("UPDATE job_evidence SET visible_to_client = %s WHERE id = %s", (new_state, doc_id))
        else:
            cur.execute(f"UPDATE {table_name} SET visible_to_client = %s WHERE id = %s AND company_id = %s", (new_state, doc_id, comp_id))
            
        conn.commit()
        return jsonify({'success': True, 'new_state': new_state})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        pass

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
        pass

# B. LOAD CALENDAR DATA (Show the bars on the calendar)
@office_bp.route('/office/calendar/data')
def calendar_data():
    if not check_office_access(): return jsonify([])
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    # Fetch Scheduled Jobs
    cur.execute("""
        SELECT j.id, j.ref, c.name, j.start_date, j.estimated_days, v.reg_plate, j.status,
               COALESCE(q.job_title, j.description, 'Job') as title,
               COALESCE(p.address_line1, j.site_address, '') as location,
               s.name as engineer_name
        FROM jobs j
        JOIN clients c ON j.client_id = c.id
        LEFT JOIN quotes q ON j.quote_id = q.id
        LEFT JOIN properties p ON j.property_id = p.id
        LEFT JOIN vehicles v ON j.vehicle_id = v.id
        LEFT JOIN staff s ON j.engineer_id = s.id
        WHERE j.company_id = %s 
          AND j.status IN ('Scheduled', 'In Progress', 'Completed', 'Accepted')
          AND j.start_date IS NOT NULL
    """, (comp_id,))
    
    events = []
    for row in cur.fetchall():
        start_date_val = row[3]
        if not start_date_val: continue
        
        if isinstance(start_date_val, (datetime, date)):
            start_str = start_date_val.strftime('%Y-%m-%d')
            dt_start = start_date_val if isinstance(start_date_val, date) else start_date_val.date()
        else:
            start_str = str(start_date_val)[:10]
            try:
                dt_start = datetime.strptime(start_str, '%Y-%m-%d').date()
            except:
                dt_start = date.today()

        days = float(row[4] or 1)
        int_days = max(int(round(days)), 1)
        
        try:
            dt_end = dt_start + timedelta(days=int_days)
            end_date = dt_end.strftime('%Y-%m-%d')
        except:
            end_date = start_str

        # Color Coding
        color = '#0d6efd' # Blue (Scheduled)
        if row[6] == 'In Progress': color = '#ffc107' # Warning Orange
        elif row[6] == 'Completed': color = '#198754' # Green

        title_display = f"{row[1]} - {row[7]} ({row[2]})"

        events.append({
            'id': row[0],
            'title': title_display,
            'client': row[2],
            'ref': row[1],
            'van': row[5] or 'No Van',
            'engineer': row[9] or 'Unassigned',
            'location': row[8],
            'status': row[6],
            'start': start_str,
            'end': end_date,
            'color': color,
            'allDay': True,
            'url': f"/office/job/{row[0]}/files"
        })
        
    return jsonify(events)

# C. HANDLE DRAG-TO-MOVE (Reschedule logic)
@office_bp.route('/office/calendar/reschedule-job', methods=['POST'])
def reschedule_job_drag():
    if not check_office_access(): return jsonify({'status': 'error'}), 401
    
    data = request.get_json()
    job_id = data.get('job_id')
    new_date = data.get('date') # '2026-01-25'
    clean_date = new_date[:10] if new_date else None
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("UPDATE jobs SET start_date = %s, status = 'Scheduled' WHERE id = %s AND company_id = %s", 
                   (clean_date, job_id, session.get('company_id')))
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

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

    pass
    
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
    pass
    
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
    pass
    
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
        pass
        return "Job not found", 404
        
    delivery_address = f"{job[1]}, {job[2]}" if job[1] else (job[3] or "No delivery address logged")
    
    # 2. Fetch Materials
    cur.execute("SELECT description, quantity FROM job_materials WHERE job_id = %s", (job_id,))
    rows = cur.fetchall()
    
    # 3. Format items
    items = [{'desc': r[0], 'qty': r[1], 'supplier': 'General'} for r in rows]
    pass
    
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
        pass

# =========================================================
# 6. SALES & INVOICING (UNIFIED DASHBOARD)
# =========================================================

@office_bp.route('/office/sales')
def office_sales_dashboard():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    cur.execute("SELECT value FROM settings WHERE key='currency_symbol' AND company_id=%s", (comp_id,))
    res = cur.fetchone(); currency = res[0] if res else '£'
    
    # 1. Fetch Quotes (Including new columns)
    cur.execute("""
        SELECT q.id, q.reference, c.name, q.date, q.total, q.status, q.needs_followup, q.client_response
        FROM quotes q
        LEFT JOIN clients c ON q.client_id = c.id
        WHERE q.company_id = %s
        ORDER BY q.date DESC
    """, (comp_id,))
    
    quotes = []
    for r in cur.fetchall():
        quotes.append({
            'id': r[0], 'ref': r[1], 'client': r[2], 'date': r[3], 'total': r[4], 
            'status': r[5], 'needs_followup': r[6], 'client_response': r[7]
        })
        
    # 2. Fetch Invoices (Including new columns)
    cur.execute("""
        SELECT i.id, i.reference, c.name, i.date, i.total, i.status, i.needs_followup, i.client_response, i.due_date
        FROM invoices i
        LEFT JOIN clients c ON i.client_id = c.id
        WHERE i.company_id = %s
        ORDER BY i.date DESC
    """, (comp_id,))
    
    invoices = []
    for r in cur.fetchall():
        invoices.append({
            'id': r[0], 'ref': r[1], 'client': r[2], 'date': r[3], 'total': r[4], 
            'status': r[5], 'needs_followup': r[6], 'client_response': r[7], 'due_date': r[8]
        })
        
    pass
    
    return render_template('office/sales_dashboard.html', 
                           quotes=quotes, invoices=invoices,
                           currency=currency, brand_color=config['color'], logo_url=config['logo'])

@office_bp.route('/office/sales/update', methods=['POST'])
def update_sales_record():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    record_type = request.form.get('record_type') # 'quote' or 'invoice'
    record_id = request.form.get('record_id')
    
    new_status = request.form.get('status')
    client_response = request.form.get('client_response')
    needs_followup = 1 if request.form.get('needs_followup') == 'on' else 0
    
    conn = get_db(); cur = conn.cursor()
    try:
        if record_type == 'quote':
            cur.execute("""
                UPDATE quotes SET status = %s, client_response = %s, needs_followup = %s
                WHERE id = %s AND company_id = %s
            """, (new_status, client_response, needs_followup, record_id, comp_id))
        elif record_type == 'invoice':
            cur.execute("""
                UPDATE invoices SET status = %s, client_response = %s, needs_followup = %s
                WHERE id = %s AND company_id = %s
            """, (new_status, client_response, needs_followup, record_id, comp_id))
            
            if new_status == 'Paid':
                user_name = session.get('user_name', session.get('username', 'Office User'))
                cur.execute("""
                    INSERT INTO audit_logs (company_id, admin_email, action, target, details, ip_address, created_at)
                    VALUES (%s, %s, 'INVOICE_PAID', %s, %s, %s, CURRENT_TIMESTAMP)
                """, (comp_id, user_name, f"Invoice #{record_id}", f"Status set to Paid from Sales Dashboard ({client_response or 'No notes'})", request.remote_addr))
        
        conn.commit()
        flash("✅ Record updated successfully.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error updating record: {e}", "error")
    finally:
        pass
        
    return redirect(url_for('office.office_sales_dashboard'))

@office_bp.route('/office/api/sidebar-alerts')
def api_sidebar_alerts():
    if not check_office_access(): 
        return jsonify({'pending_tickets': 0, 'unread_emails': 0})
        
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    try:
        # Only count new/raised/open tickets that haven't been scheduled, booked or in progress
        cur.execute("SELECT COUNT(*) FROM service_requests WHERE company_id = %s AND status IN ('Pending', 'New', 'Open', 'Raised')", (comp_id,))
        pending_tickets = cur.fetchone()[0] or 0
        
        cur.execute("SELECT COUNT(*) FROM emails WHERE company_id = %s AND folder = 'Inbox' AND status = 'Unread'", (comp_id,))
        unread_emails = cur.fetchone()[0] or 0
        
        return jsonify({
            'pending_tickets': pending_tickets,
            'unread_emails': unread_emails
        })
    except Exception:
        return jsonify({'pending_tickets': 0, 'unread_emails': 0})
    finally:
        pass
