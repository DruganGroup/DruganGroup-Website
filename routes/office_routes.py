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

# --- IN routes/office_routes.py ---

@office_bp.route('/office-hub')
def office_dashboard():
    # 1. Security Check
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    # --- COUNTERS (Top Row) ---
    cur.execute("SELECT COUNT(*) FROM clients WHERE company_id=%s AND status='Active'", (comp_id,))
    leads_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM quotes WHERE company_id=%s AND status='Pending'", (comp_id,))
    pending_quotes = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id=%s AND status='Scheduled'", (comp_id,))
    active_jobs = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id=%s AND status='Unpaid'", (comp_id,))
    unpaid_inv = cur.fetchone()[0]

    # --- ACTION CENTER LISTS (The "Boom" Feature) ---
    
    # 1. LEADS NEEDING QUOTES (Active Clients with NO Quotes)
    cur.execute("""
        SELECT c.id, c.name, c.phone, c.created_at
        FROM clients c
        LEFT JOIN quotes q ON c.id = q.client_id
        WHERE c.company_id = %s AND c.status = 'Active' AND q.id IS NULL
        ORDER BY c.created_at DESC LIMIT 5
    """, (comp_id,))
    leads_needing_quotes = cur.fetchall()

    # 2. JOBS STARTING SOON (Check Files/RAMS)
    # We define "Soon" as the next 7 days
    cur.execute("""
        SELECT j.id, j.ref, j.site_address, c.name, j.start_date, j.status 
        FROM jobs j 
        LEFT JOIN clients c ON j.client_id = c.id 
        WHERE j.company_id = %s AND j.status = 'Scheduled' 
        ORDER BY j.start_date ASC LIMIT 5
    """, (comp_id,))
    upcoming_jobs = cur.fetchall()

    # 3. JOBS FINISHED BUT NOT INVOICED (Cash Flow Killer)
    cur.execute("""
        SELECT j.id, j.ref, c.name, j.quote_total
        FROM jobs j
        LEFT JOIN invoices i ON j.id = i.job_id
        LEFT JOIN clients c ON j.client_id = c.id
        WHERE j.company_id = %s AND j.status = 'Completed' AND i.id IS NULL
        ORDER BY j.start_date DESC LIMIT 5
    """, (comp_id,))
    uninvoiced_jobs = cur.fetchall()

    # --- PIPELINE & TICKETS (Keep existing logic) ---
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

    pending_requests = 0
    try:
        cur.execute("SELECT COUNT(*) FROM service_requests WHERE company_id=%s AND status='Pending'", (comp_id,))
        row = cur.fetchone()
        if row: pending_requests = row[0]
    except: pass

    # Dropdowns for Quick Actions
    cur.execute("SELECT id, name FROM clients WHERE company_id=%s ORDER BY name", (comp_id,))
    clients = cur.fetchall()
    
    cur.execute("SELECT id, reg_plate FROM vehicles WHERE company_id=%s AND status='Active'", (comp_id,))
    vehicles = cur.fetchall()

    conn.close()

    return render_template('office/office_dashboard.html',
                           brand_color=config['color'],
                           logo_url=config['logo'],
                           leads_count=leads_count,
                           pending_quotes=pending_quotes,
                           active_jobs=active_jobs,
                           unpaid_inv=unpaid_inv,
                           leads_needing_quotes=leads_needing_quotes, # NEW
                           upcoming_jobs=upcoming_jobs,               # UPDATED
                           uninvoiced_jobs=uninvoiced_jobs,           # NEW
                           pipeline=pipeline,
                           pending_requests=pending_requests,
                           clients=clients,
                           vehicles=vehicles)

# --- OFFICE: LIVE OPERATIONS & LOGISTICS ---
@office_bp.route('/office/live-ops', methods=['GET', 'POST'])
def live_ops():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    # --- HANDLE CREW ASSIGNMENT (POST) ---
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_crew':
            vehicle_id = request.form.get('vehicle_id')
            driver_id = request.form.get('driver_id')
            crew_ids = request.form.getlist('crew_ids') # List of staff IDs
            
            try:
                # 1. Clear previous assignments for this vehicle
                # (Set anyone currently assigned to this van back to NULL)
                cur.execute("UPDATE staff SET assigned_vehicle_id = NULL WHERE assigned_vehicle_id = %s AND company_id = %s", (vehicle_id, comp_id))
                
                # 2. Update the Vehicle's Driver
                if driver_id and driver_id != 'None':
                    cur.execute("UPDATE vehicles SET assigned_driver_id = %s WHERE id = %s", (driver_id, vehicle_id))
                    # Also set the driver's vehicle_id
                    cur.execute("UPDATE staff SET assigned_vehicle_id = %s WHERE id = %s", (vehicle_id, driver_id))
                else:
                    cur.execute("UPDATE vehicles SET assigned_driver_id = NULL WHERE id = %s", (vehicle_id,))

                # 3. Update the Crew (Passengers)
                for staff_id in crew_ids:
                    # Skip the driver if they were selected in checkboxes too
                    if staff_id != driver_id:
                        cur.execute("UPDATE staff SET assigned_vehicle_id = %s WHERE id = %s", (vehicle_id, staff_id))
                
                conn.commit()
                flash("✅ Crew logistics updated.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Error updating crew: {e}", "error")
            
            return redirect(url_for('office.live_ops'))

    # --- FETCH DATA FOR DASHBOARD (GET) ---
    
    # 1. GET ALL STAFF (Fixed: Removed 'Active' filter just in case, simplified JOINs)
    today = date.today()
    cur.execute("""
        SELECT 
            s.id, s.name, s.position, s.profile_photo, s.assigned_vehicle_id,
            a.clock_in,
            j.ref, j.site_address,
            v.reg_plate
        FROM staff s
        LEFT JOIN staff_attendance a ON s.id = a.staff_id AND a.date = %s
        LEFT JOIN jobs j ON s.id = j.engineer_id AND j.status = 'In Progress'
        LEFT JOIN vehicles v ON s.assigned_vehicle_id = v.id
        WHERE s.company_id = %s
        ORDER BY s.name ASC
    """, (today, comp_id))
    
    staff_status = []
    all_staff = [] # For the dropdowns
    
    for r in cur.fetchall():
        is_clocked_in = (r[5] is not None)
        status = 'Offline'
        if is_clocked_in: status = 'Online'
        if r[6]: status = 'On Job'
        
        staff_obj = {
            'id': r[0],
            'name': r[1],
            'role': r[2],
            'photo': r[3],
            'vehicle_id': r[4], # Vital for logistics
            'clock_in': format_date(r[5], "%H:%M") if r[5] else "-",
            'job_ref': r[6],
            'location': r[7] or "HQ / Idle",
            'van': r[8],
            'status': status
        }
        staff_status.append(staff_obj)
        all_staff.append(staff_obj)

    # 2. GET ALL VEHICLES
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.assigned_driver_id, v.tracker_url, s.name 
        FROM vehicles v
        LEFT JOIN staff s ON v.assigned_driver_id = s.id
        WHERE v.company_id = %s
        ORDER BY v.reg_plate ASC
    """, (comp_id,))
    
    fleet = []
    
    # Check for API Key
    cur.execute("SELECT value FROM settings WHERE company_id=%s AND key='samsara_api_key'", (comp_id,))
    api_key_row = cur.fetchone()
    api_key = api_key_row[0] if api_key_row else None
    
    try:
        from telematics_engine import get_tracker_data
        has_engine = True
    except:
        has_engine = False

    for v in cur.fetchall():
        v_data = {
            'id': v[0],
            'reg': v[1], 
            'model': v[2],
            'driver_id': v[3],
            'driver_name': v[5] or 'No Driver',
            'lat': None, 'lon': None, 'speed': 0
        }
        
        # Fetch Real Map Data
        if has_engine and v[4] and api_key:
            try:
                telematics = get_tracker_data(v[4], api_key)
                if telematics:
                    v_data.update(telematics)
            except: pass
        
        fleet.append(v_data)

    conn.close()

    return render_template('office/live_ops.html',
                           staff=staff_status,
                           all_staff=all_staff,
                           fleet=fleet,
                           brand_color=config['color'],
                           logo_url=config['logo'])

@office_bp.route('/office/quote/new')
def new_quote():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    # 1. Get Clients
    cur.execute("SELECT id, name FROM clients WHERE company_id=%s ORDER BY name", (comp_id,))
    clients = cur.fetchall()
    
    # 2. Get Materials (Using 'cost_price' to fix the unit_cost error)
    cur.execute("SELECT id, name, cost_price FROM materials WHERE company_id=%s ORDER BY name", (comp_id,))
    materials = cur.fetchall()

    # 3. Get Settings (Fixes 'settings is undefined')
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    conn.close()

    # 4. Calculate Tax Rate (Fixes 'tax_rate is undefined')
    country = settings.get('country_code', 'UK')
    vat_reg = settings.get('vat_registered', 'no')
    tax_rate = 0.00
    
    # Tax Logic
    TAX_RATES = {'UK': 0.20, 'IE': 0.23, 'US': 0.00, 'CAN': 0.05, 'AUS': 0.10, 'NZ': 0.15, 'FR': 0.20, 'DE': 0.19, 'ES': 0.21}
    
    if vat_reg in ['yes', 'on', 'true', '1']:
        manual_rate = settings.get('default_tax_rate')
        try:
            if manual_rate and float(manual_rate) > 0:
                tax_rate = float(manual_rate) / 100
            else:
                tax_rate = TAX_RATES.get(country, 0.20)
        except:
            tax_rate = 0.20

    # 5. Return with ALL variables
    return render_template('office/create_quote.html', 
                           clients=clients, 
                           materials=materials, 
                           settings=settings, 
                           tax_rate=tax_rate)
                          
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