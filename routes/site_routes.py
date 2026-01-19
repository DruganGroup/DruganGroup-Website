from flask import Blueprint, render_template, session, redirect, url_for, flash, request, current_app
from db import get_db, get_site_config
from werkzeug.utils import secure_filename
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, date

# Safe Import for AI Service
try:
    from services.ai_assistant import scan_receipt
except ImportError:
    scan_receipt = None 

site_bp = Blueprint('site', __name__)
UPLOAD_FOLDER = 'static/uploads/van_checks'
JOB_EVIDENCE_FOLDER = 'static/uploads/job_evidence'

# --- HELPER: CHECK ACCESS ---
def check_site_access():
    if 'user_id' not in session: return False
    return True

# --- HELPER: GET STAFF IDENTITY ---
def get_staff_identity(user_id, cur):
    """
    Returns: (staff_id, staff_name, company_id, assigned_vehicle_id)
    """
    # 1. Try to find matching Staff record
    cur.execute("""
        SELECT s.id, s.name, u.company_id, s.assigned_vehicle_id 
        FROM users u
        JOIN staff s ON LOWER(u.email) = LOWER(s.email) AND u.company_id = s.company_id
        WHERE u.id = %s
    """, (user_id,))
    match = cur.fetchone()
    
    if match: return match[0], match[1], match[2], match[3]
    
    # 2. Fallback
    return None, "Unknown", None, None

# --- HELPER: SEND EMAIL ---
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

# =========================================================
# 1. SITE DASHBOARD (With Crew Logic Fix)
# =========================================================
@site_bp.route('/site-hub')
@site_bp.route('/site-companion')
def site_dashboard():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. IDENTIFY STAFF & VEHICLE
    staff_id, staff_name, comp_id, vehicle_id = get_staff_identity(session['user_id'], cur)
    
    # 2. CHECK STATUSES
    is_at_work = False    
    active_job = None     
    
    if staff_id:
        # Check Day Clock (Payroll)
        cur.execute("SELECT id FROM staff_attendance WHERE staff_id = %s AND clock_out IS NULL", (staff_id,))
        is_at_work = cur.fetchone() is not None
        
        # Check Job Clock (Costing)
        cur.execute("""
            SELECT t.job_id, COALESCE(p.address_line1, j.site_address, 'No Address') as addr
            FROM staff_timesheets t
            JOIN jobs j ON t.job_id = j.id
            LEFT JOIN properties p ON j.property_id = p.id
            WHERE t.staff_id = %s AND t.clock_out IS NULL
        """, (staff_id,))
        row = cur.fetchone()
        if row:
            active_job = {'id': row[0], 'name': row[1]}

    # 3. FETCH ASSIGNED JOBS (THE FIX: Check Engineer OR Vehicle)
    jobs = []
    if staff_id:
        cur.execute("""
            SELECT 
                j.id, 
                j.ref, 
                COALESCE(p.address_line1, j.site_address, 'No Address Logged') as address, 
                c.name, 
                j.description, 
                j.start_date, 
                j.status 
            FROM jobs j 
            LEFT JOIN clients c ON j.client_id = c.id 
            LEFT JOIN properties p ON j.property_id = p.id
            WHERE j.company_id = %s
            AND j.status != 'Completed'
            AND (j.engineer_id = %s OR j.vehicle_id = %s) -- <--- CREW LOGIC FIX
            ORDER BY j.status ASC, j.start_date ASC
        """, (comp_id, staff_id, vehicle_id)) # Pass vehicle_id here
        jobs = cur.fetchall()
    
    conn.close()
    return render_template('site/site_dashboard.html', 
                           jobs=jobs, 
                           is_at_work=is_at_work, 
                           active_job=active_job,
                           staff_name=staff_name)

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
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                filename = secure_filename(f"{date.today()}_{reg}_{file.filename}")
                file.save(os.path.join(UPLOAD_FOLDER, filename))

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

@site_bp.route('/site/job/<int:job_id>/update', methods=['POST'])
def update_job(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    action = request.form.get('action')
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    user_name = session.get('user_name', 'Engineer')
    
    try:
        # A. COMPLETE JOB (With Auto-Invoice)
        if action == 'complete':
            work_summary = request.form.get('work_summary')
            private_notes = request.form.get('private_notes')
            signature = request.form.get('signature')
            
            # Fetch Job Data
            cur.execute("SELECT client_id, ref, quote_id FROM jobs WHERE id = %s", (job_id,))
            job_data = cur.fetchone()
            client_id, job_ref, linked_quote_id = job_data
            
            # Mark Complete
            cur.execute("UPDATE jobs SET status = 'Completed', end_date = CURRENT_TIMESTAMP, work_summary = %s, private_notes = %s WHERE id = %s", (work_summary, private_notes, job_id))

            # --- INVOICE GENERATION ---
            cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id = %s", (comp_id,))
            inv_ref = f"INV-{1000 + cur.fetchone()[0] + 1}"

            # Create Invoice Header
            cur.execute("""
                INSERT INTO invoices (company_id, client_id, reference, date, due_date, status, subtotal, tax, total, job_id, notes) 
                VALUES (%s, %s, %s, CURRENT_DATE, CURRENT_DATE + 14, 'Unpaid', 0, 0, 0, %s, %s) 
                RETURNING id
            """, (comp_id, client_id, inv_ref, job_id, f"Signed by: {signature}"))
            inv_id = cur.fetchone()[0]

            # Logic: If Quote exists, copy items. Else, add labour.
            if linked_quote_id:
                cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (linked_quote_id,))
                for item in cur.fetchall():
                    cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) VALUES (%s, %s, %s, %s, %s)", (inv_id, item[0], item[1], item[2], item[3]))
            else:
                cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) VALUES (%s, %s, 1, 0, 0)", (inv_id, f"Labour: {work_summary}"))

            # Add Materials from Site
            cur.execute("SELECT description, quantity, unit_price FROM job_materials WHERE job_id = %s", (job_id,))
            for mat in cur.fetchall():
                total = float(mat[1]) * float(mat[2])
                cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) VALUES (%s, %s, %s, %s, %s)", (inv_id, f"Material: {mat[0]}", mat[1], mat[2], total))

            # --- DYNAMIC TAX CALCULATION (THE FIX) ---
            # Re-Calculate Subtotal
            cur.execute("SELECT SUM(total) FROM invoice_items WHERE invoice_id = %s", (inv_id,))
            subtotal = cur.fetchone()[0] or 0.0

            # Get Tax Settings from DB
            cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'vat_registered'", (comp_id,))
            is_vat = (cur.fetchone()[0] == 'yes') if cur.rowcount > 0 else False
            
            tax_rate = 0.20 # Default
            if is_vat:
                cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'country_code'", (comp_id,))
                country_row = cur.fetchone()
                country = country_row[0] if country_row else 'UK'
                if country == 'US': tax_rate = 0.08
                elif country == 'IE': tax_rate = 0.23
                elif country == 'AUS': tax_rate = 0.10
            else:
                tax_rate = 0.0 # No VAT if not registered

            new_tax = float(subtotal) * tax_rate
            new_total = float(subtotal) + new_tax
            
            cur.execute("UPDATE invoices SET subtotal = %s, tax = %s, total = %s WHERE id = %s", (subtotal, new_tax, new_total, inv_id))
            flash(f"🎉 Job Completed & Invoice {inv_ref} Generated.")

        # B. UPLOAD PHOTO
        elif action == 'upload_photo':
            if 'photo' in request.files:
                file = request.files['photo']
                if file.filename != '':
                    os.makedirs(JOB_EVIDENCE_FOLDER, exist_ok=True)
                    filename = secure_filename(f"JOB_{job_id}_{int(datetime.now().timestamp())}_{file.filename}")
                    
                    # Fix: Store relative path
                    db_path = f"uploads/job_evidence/{filename}"
                    file.save(os.path.join(JOB_EVIDENCE_FOLDER, filename))
                    
                    cur.execute("INSERT INTO job_evidence (job_id, filepath, uploaded_by) VALUES (%s, %s, %s)", (job_id, db_path, session['user_id']))
                    flash("📷 Photo Uploaded")

        conn.commit()
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error")
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