from flask import Blueprint, render_template, session, redirect, url_for, flash, request, current_app
from db import get_db, get_site_config
from werkzeug.utils import secure_filename
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, date
try:
    from services.ai_assistant import scan_receipt
except ImportError:
    scan_receipt = None 

site_bp = Blueprint('site', __name__)
UPLOAD_FOLDER = 'static/uploads/van_checks'
JOB_EVIDENCE_FOLDER = 'static/uploads/job_evidence'


def check_site_access():
    if 'user_id' not in session: return False
    return True
    
def get_staff_identity(user_id, cur):
    """
    Returns: (staff_id, staff_name, company_id, assigned_vehicle_id)
    Logic: Checks if user is a DRIVER (vehicles table) OR CREW (vehicle_crews table).
    """
    # 1. Get Basic Staff Info & Company
    cur.execute("""
        SELECT s.id, s.name, u.company_id
        FROM users u
        JOIN staff s ON LOWER(u.email) = LOWER(s.email) AND u.company_id = s.company_id
        WHERE u.id = %s
    """, (user_id,))
    match = cur.fetchone()
    
    if not match: return None, "Unknown", None, None
    
    staff_id, staff_name, comp_id = match
    vehicle_id = None

    # 2. Check if they are the DRIVER (Priority Check)
    cur.execute("SELECT id FROM vehicles WHERE assigned_driver_id = %s", (staff_id,))
    driver_row = cur.fetchone()
    
    if driver_row:
        vehicle_id = driver_row[0]
    else:
        # 3. If not driver, check if they are CREW/PASSENGER
        cur.execute("SELECT vehicle_id FROM vehicle_crews WHERE staff_id = %s", (staff_id,))
        crew_row = cur.fetchone()
        if crew_row:
            vehicle_id = crew_row[0]

    return staff_id, staff_name, comp_id, vehicle_id

def send_email_notification(company_id, to_email, client_name, job_ref, address):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM settings WHERE company_id = %s AND key IN ('smtp_host', 'smtp_port', 'smtp_email', 'smtp_password')", (company_id,))
        settings = {row[0]: row[1] for row in cur.fetchall()}
        
        required = ['smtp_host', 'smtp_port', 'smtp_email', 'smtp_password']
        if not all(k in settings for k in required): return False

        msg = MIMEMultipart()
        msg['From'] = settings['smtp_email']
        msg['To'] = to_email
        msg['Subject'] = f"✅ Engineer Arrived: {job_ref}"
        body = f"<h3>Hello {client_name},</h3><p>Our engineer has arrived at {address} and work is starting now.</p>"
        msg.attach(MIMEText(body, 'html'))

        server = smtplib.SMTP(settings['smtp_host'], int(settings['smtp_port']))
        server.starttls()
        server.login(settings['smtp_email'], settings['smtp_password'])
        server.send_message(msg)
        server.quit()
        return True
    except Exception: return False
    finally: conn.close()

# --- ROUTE: SITE DASHBOARD ---
@site_bp.route('/site-hub')
@site_bp.route('/site-companion')
def site_dashboard():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. IDENTIFY STAFF & GET PROFILE PIC
    staff_id, staff_name, comp_id, vehicle_id = get_staff_identity(session['user_id'], cur)
    
    # Fetch Profile Photo from 'staff' table (Table 33)
    profile_pic = None
    if staff_id:
        cur.execute("SELECT profile_photo FROM staff WHERE id = %s", (staff_id,))
        row = cur.fetchone()
        if row and row[0]: profile_pic = row[0]

    # 2. GET LIVE SETTINGS (Table 28)
    # We fetch Date Format, Brand Color, and Logo directly from the DB
    cur.execute("""
        SELECT key, value FROM settings 
        WHERE company_id = %s 
        AND key IN ('date_format', 'brand_color', 'logo')
    """, (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    date_fmt = settings.get('date_format', '%d/%m/%Y')
    brand_color = settings.get('brand_color') # No hardcoded default, template handles None
    logo_url = settings.get('logo')

    # 3. CHECK STATUSES (Attendance & Active Jobs)
    is_at_work = False    
    active_job = None     
    
    if staff_id:
        cur.execute("SELECT id FROM staff_attendance WHERE staff_id = %s AND clock_out IS NULL", (staff_id,))
        is_at_work = cur.fetchone() is not None
        
        cur.execute("""
            SELECT t.job_id, COALESCE(p.address_line1, j.site_address, 'No Address') as addr
            FROM staff_timesheets t
            JOIN jobs j ON t.job_id = j.id
            LEFT JOIN properties p ON j.property_id = p.id
            WHERE t.staff_id = %s AND t.clock_out IS NULL
        """, (staff_id,))
        row = cur.fetchone()
        if row: active_job = {'id': row[0], 'name': row[1]}

    # 4. FETCH ASSIGNED JOBS
    formatted_jobs = []
    if staff_id:
        cur.execute("""
            SELECT 
                j.id, j.ref, 
                COALESCE(p.address_line1, j.site_address, 'No Address Logged') as address, 
                c.name, j.description, j.start_date, j.status 
            FROM jobs j 
            LEFT JOIN clients c ON j.client_id = c.id 
            LEFT JOIN properties p ON j.property_id = p.id
            WHERE j.company_id = %s
            AND j.status != 'Completed'
            AND (j.engineer_id = %s OR j.vehicle_id = %s)
            ORDER BY j.status ASC, j.start_date ASC
        """, (comp_id, staff_id, vehicle_id))
        
        for job in cur.fetchall():
            j_dict = {
                'id': job[0], 'ref': job[1], 'address': job[2], 'client': job[3],
                'desc': job[4], 'status': job[6], 'raw_date': job[5], 'display_date': 'Unscheduled'
            }
            # Apply Date Format from Settings
            if job[5]:
                try:
                    str_val = str(job[5])[:10]
                    dt_obj = datetime.strptime(str_val, '%Y-%m-%d')
                    j_dict['display_date'] = dt_obj.strftime(date_fmt)
                except Exception:
                    j_dict['display_date'] = str(job[5])

            formatted_jobs.append(j_dict)
    
    conn.close()
    
    # Pass 'my_profile' dictionary so the HTML can read the picture
    return render_template('site/site_dashboard.html', 
                           jobs=formatted_jobs,
                           is_at_work=is_at_work, 
                           active_job=active_job,
                           staff_name=staff_name,
                           now_ymd=date.today().strftime(date_fmt),
                           brand_color=brand_color,
                           logo_url=logo_url,
                           my_profile={'profile_pic': profile_pic})

# =========================================================
# 2. DAY CLOCK (For Payroll - On Launcher)
# =========================================================
@site_bp.route('/site/toggle-day-clock', methods=['POST'])
def toggle_day_clock():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    staff_id, _, _, _ = get_staff_identity(session['user_id'], cur)
    
    if not staff_id:
        flash("❌ Error: Not linked to Staff Profile.", "error")
        return redirect('/launcher')

    action = request.form.get('action')

    try:
        if action == 'start':
            # Prevent double clock-in
            cur.execute("SELECT id FROM staff_attendance WHERE staff_id = %s AND clock_out IS NULL", (staff_id,))
            if not cur.fetchone():
                cur.execute("INSERT INTO staff_attendance (staff_id, date, clock_in) VALUES (%s, CURRENT_DATE, CURRENT_TIMESTAMP)", (staff_id,))
                flash("✅ Clocked In", "success")

        elif action == 'stop':
            cur.execute("""
                UPDATE staff_attendance 
                SET clock_out = CURRENT_TIMESTAMP,
                    total_hours = ROUND(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - clock_in))::numeric / 3600, 2)
                WHERE staff_id = %s AND clock_out IS NULL
            """, (staff_id,))
            flash("👋 Clocked Out", "success")

        conn.commit()
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error")
    finally:
        conn.close()

    return redirect('/launcher')

# =========================================================
# 3. JOB CLOCK (For Costing - On Job Page)
# =========================================================
@site_bp.route('/site/job/<int:job_id>/toggle-site-time', methods=['POST'])
def toggle_site_time(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    staff_id, _, comp_id, _ = get_staff_identity(session['user_id'], cur)
    action = request.form.get('action') 
    
    try:
        if action == 'start':
            # 1. Start Timer
            cur.execute("""
                INSERT INTO staff_timesheets (company_id, staff_id, job_id, date, clock_in)
                VALUES (%s, %s, %s, CURRENT_DATE, CURRENT_TIMESTAMP)
            """, (comp_id, staff_id, job_id))
            
            # 2. Update Job Status for Office Map
            cur.execute("UPDATE jobs SET status = 'In Progress', start_date = CURRENT_TIMESTAMP WHERE id = %s", (job_id,))
            flash("✅ Job Started.", "success")

        elif action == 'stop':
            # Stop Timer
            cur.execute("""
                UPDATE staff_timesheets 
                SET clock_out = CURRENT_TIMESTAMP, 
                    total_hours = EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - clock_in))/3600 
                WHERE staff_id = %s AND job_id = %s AND clock_out IS NULL
            """, (staff_id, job_id))
            flash("⏸️ Job Paused.", "success")
            
        conn.commit()
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('site.job_details', job_id=job_id))     

# =========================================================
# 4. VAN CHECK 
# =========================================================
@site_bp.route('/site/van-check', methods=['GET', 'POST'])
def van_check_page():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. Identify Driver & Assigned Van (Using new Helper)
    staff_id, _, comp_id, vehicle_id = get_staff_identity(session['user_id'], cur)
    
    # If vehicle_id found in staff profile, lookup the reg
    assigned_van = None
    if vehicle_id:
        cur.execute("SELECT id, reg_plate FROM vehicles WHERE id = %s", (vehicle_id,))
        assigned_van = cur.fetchone()

    if request.method == 'POST':
        reg = assigned_van[1] if assigned_van else request.form.get('reg_plate')
        mileage = request.form.get('mileage')
        defects = request.form.get('defects') or "No Defects Reported"
        signature = request.form.get('signature')
        
        # Save Photo Logic
        if 'photo' in request.files:
            file = request.files['photo']
            if file.filename != '':
                # SECURITY UPDATE
                save_dir = os.path.join(current_app.static_folder, 'uploads', f"company_{comp_id}", 'van_checks')
                os.makedirs(save_dir, exist_ok=True)
                filename = secure_filename(f"{date.today()}_{reg}_{file.filename}")
                file.save(os.path.join(save_dir, filename))

        try:
            # Re-verify ID
            cur.execute("SELECT id FROM vehicles WHERE reg_plate = %s", (reg,))
            v_row = cur.fetchone()
            
            if v_row:
                v_id = v_row[0]
                is_safe = False if (defects and defects != "No Defects Reported") else True
                status_log = 'Check Failed' if not is_safe else 'Daily Check'
                full_desc = f"Walkaround Complete. Signed: {signature}. Mileage: {mileage}. Notes: {defects}"
                
                cur.execute("INSERT INTO maintenance_logs (company_id, vehicle_id, date, type, description, cost) VALUES (%s, %s, CURRENT_DATE, %s, %s, 0)", (comp_id, v_id, status_log, full_desc))
                conn.commit()
                flash("✅ Safety Check Logged!")
                return redirect(request.referrer or url_for('site.site_dashboard'))
            else:
                flash("❌ Vehicle not found.")
        except Exception as e: conn.rollback(); flash(f"Error: {e}")

    # Dropdown Fallback
    vehicles = []
    if not assigned_van:
        cur.execute("SELECT reg_plate FROM vehicles WHERE company_id = %s AND status='Active' ORDER BY reg_plate", (comp_id,))
        vehicles = [r[0] for r in cur.fetchall()]
    
    conn.close()
    return render_template('site/van_check_form.html', vehicles=vehicles, assigned_van=assigned_van)

# =========================================================
# 5. JOB DETAILS & ACTIONS
# =========================================================
@site_bp.route('/site/job/<int:job_id>')
def job_details(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    staff_id, _, _, _ = get_staff_identity(session['user_id'], cur)
    
    cur.execute("""
        SELECT j.id, j.ref, j.status, c.name, c.phone, 
               COALESCE(p.address_line1, j.site_address, 'No Address Logged') as address,
               p.postcode, 
               j.description, c.gate_code,
               j.property_id
        FROM jobs j
        LEFT JOIN clients c ON j.client_id = c.id
        LEFT JOIN properties p ON j.property_id = p.id
        WHERE j.id = %s
    """, (job_id,))
    row = cur.fetchone()
    
    if not row: conn.close(); return "Job not found", 404

    # Safe Dict
    job = {
        'id': row[0], 'ref': row[1], 'status': row[2],
        'client_name': row[3] or "Unknown", 'client_phone': row[4] or "No Phone",
        'address': f"{row[5]}, {row[6]}" if row[6] else row[5], 
        'description': row[7] or "No Description", 'gate_code': row[8],
        'property_id': row[9]
    }

    # Check Clock Status
    user_is_clocked_in = False
    if staff_id:
        cur.execute("SELECT id FROM staff_timesheets WHERE staff_id = %s AND job_id = %s AND clock_out IS NULL", (staff_id, job_id))
        if cur.fetchone(): user_is_clocked_in = True

    # Materials & Photos
    cur.execute("SELECT description, quantity, unit_price FROM job_materials WHERE job_id = %s", (job_id,))
    materials = cur.fetchall()

    cur.execute("SELECT filepath FROM job_evidence WHERE job_id = %s", (job_id,))
    photos = [row[0] for row in cur.fetchall()]

    # Branding
    comp_id = session.get('company_id')
    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'logo'", (comp_id,))
    logo_url = cur.fetchone()[0] if cur.rowcount > 0 else None
    
    conn.close()
    return render_template('site/job_details.html', job=job, materials=materials, photos=photos, user_is_clocked_in=user_is_clocked_in, logo_url=logo_url)

# --- ROUTE: UPDATE JOB (COMPLETE & INVOICE) ---
@site_bp.route('/site/job/<int:job_id>/update', methods=['POST'])
def update_job(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    action = request.form.get('action')
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    try:
        # --- A. COMPLETE JOB ---
        if action == 'complete':
            work_summary = request.form.get('work_summary')
            private_notes = request.form.get('private_notes')
            signature = request.form.get('signature')
            
            # 1. Mark Job as Completed
            cur.execute("""
                UPDATE jobs 
                SET status = 'Completed', 
                    end_date = CURRENT_TIMESTAMP, 
                    work_summary = %s, 
                    private_notes = %s,
                    client_signature = %s 
                WHERE id = %s RETURNING client_id
            """, (work_summary, private_notes, signature, job_id))
            client_id = cur.fetchone()[0]

            # 2. Create Invoice
            # We put the "Work Summary" in the notes, not as a £0.00 line item
            cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id = %s", (comp_id,))
            inv_count = cur.fetchone()[0]
            inv_ref = f"INV-{1000 + inv_count + 1}"
            
            inv_notes = f"Work Summary:\n{work_summary}\n\nSigned by: {signature}"
            
            cur.execute("""
                INSERT INTO invoices (company_id, client_id, reference, date, due_date, status, subtotal, tax, total, job_id, notes) 
                VALUES (%s, %s, %s, CURRENT_DATE, CURRENT_DATE + 14, 'Unpaid', 0, 0, 0, %s, %s) 
                RETURNING id
            """, (comp_id, client_id, inv_ref, job_id, inv_notes))
            inv_id = cur.fetchone()[0]

            # 3. GET FINANCIAL SETTINGS (From DB)
            cur.execute("""
                SELECT key, value FROM settings 
                WHERE company_id = %s 
                AND key IN ('labour_markup_percent', 'material_markup_percent', 'vat_registered', 'country_code')
            """, (comp_id,))
            settings = {row[0]: row[1] for row in cur.fetchall()}
            
            # Calculate Multipliers (Default to 0 if not set in DB)
            labour_markup = float(settings.get('labour_markup_percent', 0)) / 100
            material_markup = float(settings.get('material_markup_percent', 0)) / 100

            # 4. CALCULATE LABOUR (Real Data)
            # Fetch actual hours from timesheets for this job
            cur.execute("""
                SELECT t.staff_id, SUM(t.total_hours) 
                FROM staff_timesheets t 
                WHERE t.job_id = %s 
                GROUP BY t.staff_id
            """, (job_id,))
            time_entries = cur.fetchall()

            for s_id, hours in time_entries:
                if not hours: continue
                hours = float(hours)
                
                # Fetch Pay Rate from Staff Table
                cur.execute("SELECT name, pay_rate FROM staff WHERE id = %s", (s_id,))
                staff_row = cur.fetchone()
                s_name = staff_row[0]
                base_rate = float(staff_row[1] or 0) # Wages
                
                # Apply Profit Markup
                charge_rate = base_rate + (base_rate * labour_markup)
                line_total = hours * charge_rate
                
                cur.execute("""
                    INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) 
                    VALUES (%s, %s, %s, %s, %s)
                """, (inv_id, f"Labour: {s_name}", hours, charge_rate, line_total))

            # 5. CALCULATE MATERIALS (Real Data)
            cur.execute("SELECT description, quantity, unit_price FROM job_materials WHERE job_id = %s", (job_id,))
            for mat in cur.fetchall():
                qty = float(mat[1] or 0)
                cost_price = float(mat[2] or 0)
                
                # Apply Material Markup
                sell_price = cost_price + (cost_price * material_markup)
                line_total = qty * sell_price
                
                cur.execute("""
                    INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) 
                    VALUES (%s, %s, %s, %s, %s)
                """, (inv_id, f"Material: {mat[0]}", qty, sell_price, line_total))

            # 6. FINAL TOTALS & TAX
            cur.execute("SELECT SUM(total) FROM invoice_items WHERE invoice_id = %s", (inv_id,))
            subtotal = cur.fetchone()[0] or 0.0
            
            is_vat = (settings.get('vat_registered') == 'yes')
            tax_rate = 0.20 if (is_vat and settings.get('country_code', 'UK') == 'UK') else 0.0
            
            tax_amt = float(subtotal) * tax_rate
            final_total = float(subtotal) + tax_amt
            
            cur.execute("UPDATE invoices SET subtotal = %s, tax = %s, total = %s WHERE id = %s", (subtotal, tax_amt, final_total, inv_id))
            flash(f"✅ Job Completed. Invoice {inv_ref} Generated.")

        # --- B. UPLOAD PHOTO ---
        elif action == 'upload_photo':
            if 'photo' in request.files:
                file = request.files['photo']
                if file.filename != '':
                    # SECURITY UPDATE: Use company_{id} folder
                    relative_path = f"company_{comp_id}/job_evidence"
                    save_dir = os.path.join(current_app.static_folder, 'uploads', relative_path)
                    os.makedirs(save_dir, exist_ok=True)
                    
                    filename = secure_filename(f"JOB_{job_id}_{int(datetime.now().timestamp())}_{file.filename}")
                    file.save(os.path.join(save_dir, filename))
                    
                    # DB Path must match app.py bouncer logic
                    db_path = f"/uploads/{relative_folder}/{filename}"
                    cur.execute("INSERT INTO job_evidence (job_id, filepath, uploaded_by, file_type) VALUES (%s, %s, %s, 'Site Photo')", (job_id, db_path, session['user_id']))
                    flash("📷 Photo Uploaded")

        conn.commit()
    except Exception as e:
        conn.rollback()
        # Log error to system_logs (Table 38)
        cur.execute("INSERT INTO system_logs (level, message, route, created_at) VALUES ('ERROR', %s, 'site/update_job', CURRENT_TIMESTAMP)", (str(e),))
        conn.commit()
        flash(f"Error: {e}", "error")
    finally:
        conn.close()
    
    if action == 'complete': return redirect(url_for('site.site_dashboard'))
    return redirect(url_for('site.job_details', job_id=job_id))
    
# --- ADD MATERIAL ---
@site_bp.route('/site/job/<int:job_id>/add-material', methods=['POST'])
def add_job_material(job_id):
    if 'user_id' not in session: return redirect('/login')
    
    desc = request.form.get('description')
    qty = request.form.get('quantity')
    price = request.form.get('price') or 0

    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO job_materials (job_id, description, quantity, unit_price) VALUES (%s, %s, %s, %s)", (job_id, desc, qty, price))
        conn.commit(); flash("✅ Item Added")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('site.job_details', job_id=job_id))

# --- CERTIFICATES ---
@site_bp.route('/site/cert/cp12/create')
def create_site_cp12():
    return redirect(f"/office/cert/cp12/create?job_id={request.args.get('job_id')}&prop_id={request.args.get('prop_id')}")

@site_bp.route('/site/cert/eicr/create')
def create_site_eicr():
    return redirect(f"/office/cert/eicr/create?job_id={request.args.get('job_id')}&prop_id={request.args.get('prop_id')}")
    
# =========================================================
# LOG FUEL ROUTE (Fixes 404 Error)
# =========================================================
@site_bp.route('/site/log-fuel', methods=['GET', 'POST'])
def site_log_fuel():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    # 1. Identify User & Assigned Vehicle
    staff_id, _, comp_id, vehicle_id = get_staff_identity(session['user_id'], cur)

    # 2. Get Vehicle Reg (for display in the form)
    reg_plate = "Unknown"
    if vehicle_id:
        cur.execute("SELECT reg_plate FROM vehicles WHERE id = %s", (vehicle_id,))
        row = cur.fetchone()
        if row: reg_plate = row[0]

    # 3. Handle Form Submission
    if request.method == 'POST':
        try:
            total_cost = request.form.get('total_cost')
            litres = request.form.get('litres')
            mileage = request.form.get('mileage')
            fuel_type = request.form.get('fuel_type')
            
            # Handle Receipt Upload
            receipt_path = None
            if 'receipt' in request.files:
                f = request.files['receipt']
                if f and f.filename != '':
                    from werkzeug.utils import secure_filename
                    import os
                    # SECURITY UPDATE
                    relative_path = f"company_{comp_id}/fuel"
                    save_dir = os.path.join('static', 'uploads', relative_path)
                    os.makedirs(save_dir, exist_ok=True)
                    
                    fname = secure_filename(f"FUEL_{date.today()}_{f.filename}")
                    f.save(os.path.join(save_dir, fname))
                    receipt_path = f"/uploads/{relative_folder}/{fname}"

            # Save to Database (Maintenance Logs)
            cur.execute("""
                INSERT INTO maintenance_logs 
                (company_id, vehicle_id, date, type, description, cost, receipt_path, mileage)
                VALUES (%s, %s, %s, 'Fuel', %s, %s, %s, %s)
            """, (comp_id, vehicle_id, date.today(), f"Fuel: {litres}L ({fuel_type})", total_cost, receipt_path, mileage))
            
            conn.commit()
            flash("✅ Fuel logged successfully.", "success")
            return redirect(url_for('site.site_dashboard'))

        except Exception as e:
            conn.rollback()
            flash(f"Error logging fuel: {e}", "error")

    conn.close()
    # Ensure this matches the file you uploaded: 'site/fuel_form.html'
    return render_template('site/fuel_form.html', reg=reg_plate)
    
@site_bp.route('/site/van-check', methods=['GET', 'POST'])
def site_van_check():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    staff_id, staff_name, comp_id, vehicle_id = get_staff_identity(session['user_id'], cur)

    # 1. Get Assigned Vehicle Details (If found by helper)
    assigned_van = None
    if vehicle_id:
        cur.execute("SELECT id, reg_plate FROM vehicles WHERE id = %s", (vehicle_id,))
        assigned_van = cur.fetchone()

    # 2. Handle Form Submission
    if request.method == 'POST':
        try:
            # If assigned, force that ID. Else get from dropdown.
            target_veh_id = vehicle_id if vehicle_id else None
            
            # If no assigned van, look up the one selected in dropdown
            if not target_veh_id:
                sel_reg = request.form.get('reg_plate')
                if sel_reg:
                    cur.execute("SELECT id FROM vehicles WHERE reg_plate = %s AND company_id = %s", (sel_reg, comp_id))
                    row = cur.fetchone()
                    if row: target_veh_id = row[0]

            if not target_veh_id:
                raise Exception("No vehicle selected or assigned.")

            mileage = request.form.get('mileage')
            defects = request.form.get('defects')
            signature = request.form.get('signature')
            
            # Determine Check Status
            is_safe = False if (defects and len(defects) > 2) else True
            status_log = 'Check Failed' if not is_safe else 'Daily Check'
            desc = f"Walkaround Complete. Signed: {signature}. Mileage: {mileage}. Notes: {defects}"
            
            # Insert Log
            cur.execute("""
                INSERT INTO maintenance_logs (company_id, vehicle_id, date, type, description, cost, mileage)
                VALUES (%s, %s, CURRENT_DATE, %s, %s, 0, %s)
            """, (comp_id, target_veh_id, status_log, desc, mileage))
            
            conn.commit()
            flash("✅ Safety check submitted.", "success")
            return redirect(url_for('site.site_dashboard'))

        except Exception as e:
            conn.rollback()
            flash(f"Error: {e}", "error")

    # 3. Fallback List (Only used if no van assigned)
    vehicles = []
    if not assigned_van:
        cur.execute("SELECT reg_plate FROM vehicles WHERE company_id = %s AND status='Active' ORDER BY reg_plate ASC", (comp_id,))
        vehicles = [r[0] for r in cur.fetchall()]

    conn.close()
    return render_template('site/van_check_form.html', 
                           assigned_van=assigned_van, 
                           vehicles=vehicles)