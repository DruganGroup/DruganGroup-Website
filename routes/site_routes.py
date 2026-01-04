from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from werkzeug.utils import secure_filename
from services.ai_assistant import scan_receipt
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, date

site_bp = Blueprint('site', __name__)
UPLOAD_FOLDER = 'static/uploads/van_checks'
JOB_EVIDENCE_FOLDER = 'static/uploads/job_evidence'

# --- HELPER: CHECK ACCESS ---
def check_site_access():
    if 'user_id' not in session: return False
    return True

# --- HELPER: GET STAFF ID FROM USER ID ---
def get_staff_identity(user_id, cur):
    """
    Links the logged-in User to their Staff Profile via Email.
    Returns: (staff_id, staff_name, company_id)
    """
    # 1. Try to find matching Staff record
    cur.execute("""
        SELECT s.id, s.name, u.company_id 
        FROM users u
        JOIN staff s ON LOWER(u.email) = LOWER(s.email) AND u.company_id = s.company_id
        WHERE u.id = %s
    """, (user_id,))
    match = cur.fetchone()
    
    if match:
        return match[0], match[1], match[2]
    
    # 2. Fallback: Just return User info (if they are Admin but not in Staff table)
    cur.execute("SELECT company_id, name, username FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if user:
        return None, (user[1] or user[2]), user[0]
    return None, "Unknown", None

# --- HELPER: SEND EMAIL (SAAS VERSION - DYNAMIC SMTP) ---
def send_email_notification(company_id, to_email, client_name, job_ref, address):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT key, value FROM settings 
            WHERE company_id = %s AND key IN ('smtp_host', 'smtp_port', 'smtp_email', 'smtp_password')
        """, (company_id,))
        settings = {row[0]: row[1] for row in cur.fetchall()}
        
        required_keys = ['smtp_host', 'smtp_port', 'smtp_email', 'smtp_password']
        if not all(k in settings for k in required_keys):
            return False

        msg = MIMEMultipart()
        msg['From'] = settings['smtp_email']
        msg['To'] = to_email
        msg['Subject'] = f"✅ Engineer Arrived: {job_ref}"

        body = f"""
        <h3>Hello {client_name},</h3>
        <p>This is an automated update regarding your job reference <strong>{job_ref}</strong>.</p>
        <p>Our engineer has arrived at <strong>{address}</strong> and work is starting now.</p>
        <p>You will receive another update when the work is complete.</p>
        <br>
        <p>Best Regards,</p>
        """
        msg.attach(MIMEText(body, 'html'))

        server = smtplib.SMTP(settings['smtp_host'], int(settings['smtp_port']))
        server.starttls()
        server.login(settings['smtp_email'], settings['smtp_password'])
        server.send_message(msg)
        server.quit()
        return True
    except Exception:
        return False
    finally:
        conn.close()

@site_bp.route('/site-hub')
@site_bp.route('/site-companion') 
def site_dashboard():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # Resolves your ID correctly so the Clock In works
    staff_id = None
    cur.execute("SELECT s.id FROM staff s JOIN users u ON LOWER(u.email) = LOWER(s.email) WHERE u.id = %s", (session['user_id'],))
    match = cur.fetchone()
    if match: staff_id = match[0]
    
    # A. CLOCK STATUS
    is_clocked_in = False
    if staff_id:
        cur.execute("SELECT id FROM staff_timesheets WHERE staff_id = %s AND clock_out IS NULL", (staff_id,))
        is_clocked_in = cur.fetchone() is not None
    
    # B. 7-DAY CALENDAR SCHEDULE
    jobs = []
    if staff_id:
        cur.execute("""
            SELECT j.id, j.ref, j.site_address, c.name, j.description, j.start_date, j.status 
            FROM jobs j 
            LEFT JOIN clients c ON j.client_id = c.id 
            WHERE j.engineer_id = %s 
            AND j.status != 'Completed'
            AND j.start_date >= CURRENT_DATE 
            AND j.start_date <= CURRENT_DATE + INTERVAL '7 days'
            ORDER BY j.start_date ASC
        """, (staff_id,))
        jobs = cur.fetchall()
    
    conn.close()
    return render_template('site/site_dashboard.html', jobs=jobs, is_clocked_in=is_clocked_in)  

# --- NEW: CLOCK IN ROUTE ---
@site_bp.route('/site/clock-in', methods=['POST'])
def clock_in():
    if 'user_id' not in session: return redirect('/login')
    staff_id = session.get('staff_id'); comp_id = session.get('company_id')
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM staff_timesheets WHERE staff_id = %s AND clock_out IS NULL AND date = CURRENT_DATE", (staff_id,))
        if cur.fetchone():
            flash("⚠️ You are already clocked in!", "warning")
        else:
            cur.execute("INSERT INTO staff_timesheets (staff_id, company_id, clock_in, date) VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_DATE)", (staff_id, comp_id))
            conn.commit(); flash("🕒 Clocked In Successfully!")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect('/site-hub')

# --- NEW: CLOCK OUT ROUTE ---
@site_bp.route('/site/clock-out', methods=['POST'])
def clock_out():
    if 'user_id' not in session: return redirect('/login')
    staff_id = session.get('staff_id')
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT id, clock_in FROM staff_timesheets WHERE staff_id = %s AND clock_out IS NULL ORDER BY id DESC LIMIT 1", (staff_id,))
        row = cur.fetchone()
        if row:
            sheet_id = row[0]; start_time = row[1]
            # Calculate hours worked (simple subtraction)
            diff = datetime.now() - start_time
            hours = diff.total_seconds() / 3600
            
            cur.execute("UPDATE staff_timesheets SET clock_out = CURRENT_TIMESTAMP, total_hours = %s WHERE id = %s", (round(hours, 2), sheet_id))
            conn.commit(); flash(f"🕒 Clocked Out. Shift: {round(hours, 2)} hrs.")
        else:
            flash("⚠️ Error: No active shift found.", "warning")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect('/site-hub')
                          
# --- 2. DEDICATED VAN CHECK PAGE ---
@site_bp.route('/site/van-check', methods=['GET', 'POST'])
def van_check_page():
    if not check_site_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        reg = request.form.get('reg_plate')
        mileage = request.form.get('mileage')
        defects = request.form.get('defects') or "No Defects Reported"
        signature = request.form.get('signature')
        
        if 'photo' in request.files:
            file = request.files['photo']
            if file.filename != '':
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                filename = secure_filename(f"{date.today()}_{reg}_{file.filename}")
                file.save(os.path.join(UPLOAD_FOLDER, filename))

        try:
            cur.execute("SELECT id FROM vehicles WHERE reg_plate = %s", (reg,))
            v_row = cur.fetchone()
            if v_row:
                v_id = v_row[0]
                is_safe = False if (defects and defects != "No Defects Reported") else True
                status_log = 'Check Failed' if not is_safe else 'Daily Check'
                full_desc = f"Walkaround Complete. Signed by: {signature}. Mileage: {mileage}. Notes: {defects}"
                
                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, date, type, description, cost) 
                    VALUES (%s, %s, CURRENT_DATE, %s, %s, 0)
                """, (comp_id, v_id, status_log, full_desc))
                conn.commit()
                flash("✅ Safety Check Logged Successfully!")
                return redirect(url_for('site.site_dashboard'))
            else:
                flash("❌ Vehicle not found.")
        except Exception as e:
            conn.rollback(); flash(f"Error: {e}")

    cur.execute("SELECT reg_plate FROM vehicles WHERE company_id = %s AND status='Active' ORDER BY reg_plate", (comp_id,))
    vehicles = [r[0] for r in cur.fetchall()]
    conn.close()

    return render_template('site/van_check_form.html', vehicles=vehicles)

# --- 3. VIEW SINGLE JOB ---
@site_bp.route('/site/job/<int:job_id>')
def view_job(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); conn = get_db(); cur = conn.cursor()
    
    cur.execute("""
        SELECT j.id, j.ref, j.status, j.start_date, j.description, 
               c.name, c.phone, j.site_address, j.description, j.id
        FROM jobs j
        LEFT JOIN clients c ON j.client_id = c.id
        WHERE j.id = %s AND j.company_id = %s
    """, (job_id, comp_id))
    job = cur.fetchone()

    cur.execute("SELECT filepath FROM job_evidence WHERE job_id = %s ORDER BY uploaded_at DESC", (job_id,))
    photos = [r[0] for r in cur.fetchall()]
    
    conn.close()
    if not job: return "Job not found", 404
    return render_template('site/job_details.html', job=job, photos=photos)

# --- 4. UPDATE JOB (SAAS EMAIL & AUTO-INVOICE) ---
@site_bp.route('/site/job/<int:job_id>/update', methods=['POST'])
def update_job(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    action = request.form.get('action')
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    try:
        # --- A. START JOB ---
        if action == 'start':
            cur.execute("UPDATE jobs SET status = 'In Progress', start_date = CURRENT_TIMESTAMP WHERE id = %s AND company_id = %s", (job_id, comp_id))
            
            cur.execute("""
                SELECT c.id, c.name, c.email, j.ref, j.site_address 
                FROM jobs j 
                LEFT JOIN clients c ON j.client_id = c.id 
                WHERE j.id = %s
            """, (job_id,))
            job_data = cur.fetchone()
            
            if job_data and job_data[2]: 
                c_id, c_name, c_email, j_ref, j_addr = job_data
                email_sent = send_email_notification(comp_id, c_email, c_name, j_ref, j_addr)
                
                status_msg = "Sent" if email_sent else "Failed (Check Settings)"
                cur.execute("INSERT INTO client_notifications (job_id, client_id, message, status) VALUES (%s, %s, %s, %s)", 
                           (job_id, c_id, f"Start Notification to {c_email}", status_msg))
                flash("✅ Job Started." + (" Client notified." if email_sent else ""))
            else:
                flash("✅ Job Started.")

       # --- B. COMPLETE JOB (Two-Lane Workflow) ---
        elif action == 'complete':
            signature = request.form.get('signature')
            work_summary = request.form.get('work_summary')
            private_notes = request.form.get('private_notes')
            
            # Fetch Job Data
            cur.execute("SELECT client_id, ref, description, start_date, property_id FROM jobs WHERE id = %s", (job_id,))
            job_data = cur.fetchone()
            client_id, job_ref, job_desc, job_date, prop_id = job_data
            clean_ref = job_ref.replace("Ref: ", "").replace("Quote Work: ", "").strip()

            # 1. Update Job Record with Time & Notes
            cur.execute("""
                UPDATE jobs 
                SET status = 'Completed', end_date = CURRENT_TIMESTAMP, 
                    work_summary = %s, private_notes = %s 
                WHERE id = %s
            """, (work_summary, private_notes, job_id))

            # 2. Check for Quote (Lane 1 vs Lane 2)
            cur.execute("SELECT id FROM quotes WHERE reference = %s AND company_id = %s", (clean_ref, comp_id))
            quote_row = cur.fetchone()

            # Generate Invoice Ref
            cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id = %s", (comp_id,))
            inv_ref = f"INV-{1000 + cur.fetchone()[0] + 1}"

            # LANE 1: QUOTED JOB (Auto-Invoice)
            if quote_row:
                quote_id = quote_row[0]
                
                # Fetch Tax Settings
                cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
                settings = {row[0]: row[1] for row in cur.fetchall()}
                vat_enabled = settings.get('vat_registered') == 'yes'
                country = settings.get('country_code', 'UK')
                
                tax_rate = 0.0
                if vat_enabled:
                    if country == 'UK': tax_rate = 0.20
                    elif country == 'AUS': tax_rate = 0.10
                    elif country == 'NZ': tax_rate = 0.15
                    elif country == 'CAN': tax_rate = 0.05
                    elif country == 'EU': tax_rate = 0.21

                # Create Invoice Shell
                cur.execute("""
                    INSERT INTO invoices (company_id, client_id, quote_ref, reference, date, due_date, status, subtotal, tax, total, notes) 
                    VALUES (%s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + 14, 'Unpaid', 0, 0, 0, %s) 
                    RETURNING id
                """, (comp_id, client_id, clean_ref, inv_ref, f"Job Signed by: {signature}"))
                inv_id = cur.fetchone()[0]

                # Transfer Items
                cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
                items = cur.fetchall()
                subtotal = 0.0
                for item in items:
                    cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) VALUES (%s, %s, %s, %s, %s)",
                               (inv_id, item[0], item[1], item[2], item[3]))
                    subtotal += float(item[3])
                
                # Calc Tax
                tax_amount = subtotal * tax_rate
                grand_total = subtotal + tax_amount
                cur.execute("UPDATE invoices SET subtotal = %s, tax = %s, total = %s WHERE id = %s", (subtotal, tax_amount, grand_total, inv_id))
                
                flash(f"🎉 Job Completed. Quoted Invoice {inv_ref} generated automatically.")

            # LANE 2: EMERGENCY JOB (Draft Invoice)
            else:
                # Create 'Draft' Invoice with 0 Total
                cur.execute("""
                    INSERT INTO invoices (company_id, client_id, reference, date, due_date, status, subtotal, tax, total, notes) 
                    VALUES (%s, %s, %s, CURRENT_DATE, CURRENT_DATE + 14, 'Draft', 0, 0, 0, %s) 
                    RETURNING id
                """, (comp_id, client_id, inv_ref, f"Pending Pricing. Work Done: {work_summary}. Signed: {signature}"))
                inv_id = cur.fetchone()[0]
                
                # Add Placeholder Item
                cur.execute("""
                    INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) 
                    VALUES (%s, %s, 1, 0, 0)
                """, (inv_id, f"Work Completed: {work_summary}"))
                
                flash(f"✅ Job Completed. Draft Invoice {inv_ref} sent to Office for pricing.")

            # Close Linked Service Ticket
            cur.execute("UPDATE service_requests SET status = 'Completed' WHERE property_id = %s AND status = 'In Progress'", (prop_id,))
            
        # --- C. UPLOAD PHOTO ---
        elif action == 'upload_photo':
            if 'photo' in request.files:
                file = request.files['photo']
                if file.filename != '':
                    os.makedirs(JOB_EVIDENCE_FOLDER, exist_ok=True)
                    filename = secure_filename(f"JOB_{job_id}_{int(datetime.now().timestamp())}_{file.filename}")
                    db_path = f"uploads/job_evidence/{filename}"
                    file.save(os.path.join(JOB_EVIDENCE_FOLDER, filename))
                    cur.execute("INSERT INTO job_evidence (job_id, filepath, uploaded_by) VALUES (%s, %s, %s)", (job_id, db_path, session['user_id']))
                    flash("📷 Photo Uploaded")

        conn.commit()
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()

    if action == 'complete': return redirect(url_for('site.site_dashboard'))
    return redirect(url_for('site.view_job', job_id=job_id))

# --- PUBLIC PAGES ---
@site_bp.route('/advertise')
@site_bp.route('/business-better')
def advertise_page(): return render_template('public/advert-bb.html')

@site_bp.route('/site/log-fuel', methods=['GET', 'POST'])
def log_fuel():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    # Get Staff ID
    staff_id = None
    cur.execute("SELECT s.id FROM staff s JOIN users u ON LOWER(u.email) = LOWER(s.email) WHERE u.id = %s", (session['user_id'],))
    match = cur.fetchone()
    search_id = match[0] if match else session['user_id']

    # Find Van
    cur.execute("SELECT id, reg_plate FROM vehicles WHERE assigned_driver_id = %s", (search_id,))
    vehicle = cur.fetchone()

    if not vehicle:
        flash("❌ No vehicle assigned to you.")
        return redirect(url_for('site.site_dashboard'))
    
    v_id, v_reg = vehicle

    if request.method == 'POST':
        file = request.files.get('receipt')
        if file and file.filename != '':
            try:
                filename = secure_filename(f"FUEL_{v_reg}_{int(datetime.now().timestamp())}_{file.filename}")
                full_path = os.path.join(UPLOAD_FOLDER, filename)
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(full_path)
                db_path = f"uploads/van_checks/{filename}"

                cost = 0.0
                desc = f"Fuel for {v_reg}"
                
                # AI Scan (Wrapped in Try/Except to stop 502 Crashes)
                try:
                    from services.ai_assistant import scan_receipt
                    scan = scan_receipt(full_path)
                    if scan['success']:
                        data = scan['data']
                        cost = float(data.get('total_cost', 0))
                        if data.get('vendor'): desc = f"Fuel: {data.get('vendor')} ({v_reg})"
                        flash(f"✨ Receipt Scanned: £{cost}")
                except Exception as ai_error:
                    print(f"AI Error: {ai_error}") # Log it but don't crash the page
                    flash("⚠️ AI failed to read receipt. Please check amount manually.")

                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, date, type, description, cost, receipt_path) 
                    VALUES (%s, %s, CURRENT_DATE, 'Fuel', %s, %s, %s)
                """, (comp_id, v_id, desc, cost, db_path))
                
                conn.commit()
                return redirect(url_for('site.site_dashboard'))
            except Exception as e:
                conn.rollback()
                flash(f"Error saving log: {e}")

    return render_template('site/fuel_form.html', reg=v_reg)