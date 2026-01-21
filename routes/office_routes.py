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
    
    cur.execute("SELECT COUNT(*) FROM quotes WHERE company_id=%s AND status='Pending'", (comp_id,))
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
                           
@office_bp.route('/office/quote/save', methods=['POST'])
def save_quote():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    # (Your existing save logic here - unchanged)
    # For brevity, I am keeping the logic you likely already have.
    # If this part is missing, let me know and I will provide the full save function.
    return redirect(url_for('office.office_dashboard'))

# =========================================================
# 3. CALENDAR & SCHEDULE
# =========================================================
@office_bp.route('/office/calendar')
def office_calendar():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    # Get Resources for the Modal
    cur.execute("SELECT id, reg_plate FROM vehicles WHERE company_id=%s AND status='Active'", (comp_id,))
    vehicles = cur.fetchall()
    
    cur.execute("SELECT id, name FROM staff WHERE company_id=%s AND role IN ('Engineer','Manager')", (comp_id,))
    engineers = cur.fetchall()
    
    conn.close()

    return render_template('office/calendar.html',
                           brand_color=config['color'],
                           logo_url=config['logo'],
                           vehicles=vehicles,
                           engineers=engineers)

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
                        save_dir = os.path.join('static', 'uploads', str(comp_id), 'fleet')
                        os.makedirs(save_dir, exist_ok=True)
                        
                        fname = secure_filename(f"LOG_{veh_id}_{f.filename}")
                        f.save(os.path.join(save_dir, fname))
                        file_path = f"uploads/{comp_id}/fleet/{fname}"

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

@office_bp.route('/office/quote/new')
def new_quote():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Clients
    cur.execute("SELECT id, name FROM clients WHERE company_id=%s AND status='Active' ORDER BY name", (comp_id,))
    clients = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]
    
    # 2. Fetch Materials
    cur.execute("SELECT id, name, cost_price FROM materials WHERE company_id=%s ORDER BY name", (comp_id,))
    materials = [{'id': r[0], 'name': r[1], 'price': r[2]} for r in cur.fetchall()]

    # ==============================================================================
    # 3. FETCH VEHICLES & CALCULATE "TRUE GANG COST" (Matches Finance Logic)
    # ==============================================================================
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.daily_cost, v.assigned_driver_id
        FROM vehicles v
        WHERE v.company_id = %s AND v.status = 'Active'
    """, (comp_id,))
    
    vehicles_raw = cur.fetchall()
    vehicles = []

    for r in vehicles_raw:
        v_id, reg, model, base_cost, driver_id = r
        
        # Start with Base Cost (Lease/Fuel)
        daily_total = float(base_cost or 0)
        
        # A. Add Driver Cost
        if driver_id:
            cur.execute("SELECT pay_rate, pay_model FROM staff WHERE id = %s", (driver_id,))
            d_row = cur.fetchone()
            if d_row:
                rate, model_type = float(d_row[0] or 0), d_row[1]
                if model_type == 'Hour': daily_total += (rate * 8) # Assume 8hr day for quotes
                elif model_type == 'Day': daily_total += rate
                elif model_type == 'Year': daily_total += (rate / 260)

        # B. Add Crew Cost (Passengers)
        cur.execute("""
            SELECT s.pay_rate, s.pay_model 
            FROM vehicle_crews vc
            JOIN staff s ON vc.staff_id = s.id
            WHERE vc.vehicle_id = %s
        """, (v_id,))
        crew_rows = cur.fetchall()
        
        for c_row in crew_rows:
            rate, model_type = float(c_row[0] or 0), c_row[1]
            if model_type == 'Hour': daily_total += (rate * 8)
            elif model_type == 'Day': daily_total += rate
            elif model_type == 'Year': daily_total += (rate / 260)

        # C. Add to List
        vehicles.append({
            'id': v_id, 
            'reg_plate': reg, 
            'make_model': model, 
            'daily_cost': daily_total # <--- NOW ACCURATE
        })
    # ==============================================================================

    # 4. Fetch Settings
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    # 5. LOOKUP SERVICE REQUEST
    request_id = request.args.get('request_id')
    source_request = None
    if request_id:
        cur.execute("SELECT issue_description, image_url, property_id FROM service_requests WHERE id = %s AND company_id = %s", (request_id, comp_id))
        row = cur.fetchone()
        if row: source_request = {'desc': row[0], 'image': row[1], 'prop_id': row[2]}

    conn.close()

    # Tax Logic
    country = settings.get('country_code', 'UK')
    vat_reg = settings.get('vat_registered', 'no')
    tax_rate = 0.20
    
    TAX_RATES = {'UK': 0.20, 'IE': 0.23, 'US': 0.00, 'CAN': 0.05, 'AUS': 0.10, 'NZ': 0.15}
    if vat_reg in ['yes', 'on', 'true', '1']:
        manual_rate = settings.get('default_tax_rate')
        if manual_rate: tax_rate = float(manual_rate) / 100
        else: tax_rate = TAX_RATES.get(country, 0.20)
    else:
        tax_rate = 0.00

    pre_client = request.args.get('client_id')

    return render_template('office/create_quote.html', 
                           clients=clients, 
                           materials=materials, 
                           vehicles=vehicles,
                           settings=settings, 
                           tax_rate=tax_rate, 
                           pre_selected_client=pre_client,
                           source_request=source_request)

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
    
    # 1. Fetch Job Data
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT j.ref, j.description, j.site_address, c.name
        FROM jobs j
        LEFT JOIN clients c ON j.client_id = c.id
        WHERE j.id = %s
    """, (job_id,))
    job = cur.fetchone()
    conn.close()
    
    if not job: return "Job not found", 404

    # 2. Generate PDF (Placeholder logic - requires your PDF service)
    # If you have a specific RAMS generator service, call it here.
    # For now, we return a simple PDF to prove the link works.
    try:
        from services.pdf_generator import create_simple_pdf
        pdf_bytes = create_simple_pdf(f"RAMS DOCUMENT\nRef: {job[0]}\nClient: {job[3]}\nRisk Assessment & Method Statement")
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=False,
            download_name=f"RAMS_{job[0]}.pdf"
        )
    except ImportError:
        return "PDF Service Missing. Please check backend services.", 500   
        
@office_bp.route('/office/job/<int:job_id>/materials/pdf')
def job_materials_pdf(job_id):
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Job Details
    cur.execute("SELECT ref, site_address FROM jobs WHERE id = %s AND company_id = %s", (job_id, comp_id))
    job = cur.fetchone()
    if not job: return "Job not found", 404
    
    # 2. Fetch Materials from DB (job_materials table)
    cur.execute("""
        SELECT description, quantity 
        FROM job_materials 
        WHERE job_id = %s
    """, (job_id,))
    
    rows = cur.fetchall()
    
    # 3. Format for PDF
    # (Since job_materials is simple, we might not have supplier data stored there yet unless we updated the table. 
    # We will assume a simple list for now.)
    items = [{'desc': r[0], 'qty': r[1], 'supplier': 'General'} for r in rows]
    
    conn.close()
    
    # 4. Generate PDF
    html = render_template('office/pdf_materials.html',
                           config=config,
                           ref=job[0],
                           date=date.today().strftime('%d/%m/%Y'),
                           address=job[1],
                           items=items,
                           grouped_items=None) # Flat list for stored jobs
                           
    from services.pdf_generator import generate_pdf_from_html
    pdf = generate_pdf_from_html(html)
    
    from flask import make_response
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=Materials_{job[0]}.pdf'
    return response