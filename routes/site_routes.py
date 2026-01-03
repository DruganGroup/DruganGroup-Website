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

# --- HELPER: SEND EMAIL (SAAS VERSION - DYNAMIC SMTP) ---
def send_email_notification(company_id, to_email, client_name, job_ref, address):
    conn = get_db()
    try:
        cur = conn.cursor()
        # 1. Fetch Company Specific SMTP Settings
        cur.execute("""
            SELECT key, value FROM settings 
            WHERE company_id = %s AND key IN ('smtp_host', 'smtp_port', 'smtp_email', 'smtp_password')
        """, (company_id,))
        
        # Convert list of rows to a dictionary
        settings = {row[0]: row[1] for row in cur.fetchall()}
        
        # Check if we have all required settings
        required_keys = ['smtp_host', 'smtp_port', 'smtp_email', 'smtp_password']
        if not all(k in settings for k in required_keys):
            print(f"⚠️ Missing SMTP settings for Company {company_id}")
            return False

        # 2. Configure the Email
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

        # 3. Connect & Send
        server = smtplib.SMTP(settings['smtp_host'], int(settings['smtp_port']))
        server.starttls()
        server.login(settings['smtp_email'], settings['smtp_password'])
        server.send_message(msg)
        server.quit()
        return True

    except Exception as e:
        print(f"❌ Email Failed for Company {company_id}: {e}")
        return False
    finally:
        conn.close()

# --- HELPER: SELF-REPAIR DATABASE ---
def repair_site_tables(conn):
    try:
        cur = conn.cursor()
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS staff_id INTEGER")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS job_evidence (
                id SERIAL PRIMARY KEY,
                job_id INTEGER,
                filepath TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                uploaded_by INTEGER
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS client_notifications (
                id SERIAL PRIMARY KEY,
                job_id INTEGER,
                client_id INTEGER,
                message TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT
            )
        """)
        conn.commit()
    except Exception as e:
        conn.rollback(); print(f"⚠️ Auto-Repair Warning: {e}")

# --- 1. SITE DASHBOARD ---
@site_bp.route('/site-hub')
@site_bp.route('/site-companion') 
def site_dashboard():
    if 'user_id' not in session: return redirect('/')
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch User & Company Config (FIXED NAME LOGIC)
    # Checks Staff table first (Real Name), then Users table (Username), then defaults.
    cur.execute("""
        SELECT u.company_id, COALESCE(s.name, u.name, u.username) 
        FROM users u 
        LEFT JOIN staff s ON u.email = s.email 
        WHERE u.id = %s
    """, (session['user_id'],))
    
    user = cur.fetchone()
    comp_id = user[0]
    staff_name = user[1] if user and user[1] else "Staff Member"
    
    config = get_site_config(comp_id)
    
    # SYSTEM: Prepare for Universal Date Format (Default to UK if missing)
    user_date_format = config.get('date_format', '%d/%m/%Y') 
    
    today = datetime.now().date()

    # 2. TODAY'S SCHEDULE (FIXED: LEFT JOINs to ensure jobs show up even if data missing)
    cur.execute("""
        SELECT j.id, j.status, j.ref, 
               COALESCE(p.address_line1, 'Address Not Set'), 
               COALESCE(p.postcode, ''), 
               j.description, j.start_date
        FROM jobs j
        LEFT JOIN properties p ON j.property_id = p.id
        WHERE j.engineer_id = %s AND j.start_date::DATE = %s AND j.status != 'Completed'
    """, (session['user_id'], today))
    
    my_jobs = []
    for row in cur.fetchall():
        my_jobs.append({
            'id': row[0], 'status': row[1], 'reference': row[2],
            'address': row[3], 'postcode': row[4], 'notes': row[5],
            'date_obj': row[6]
        })

    # 3. 7-DAY AGENDA CALENDAR (FIXED: LEFT JOINs)
    calendar = []
    for i in range(7):
        check_date = today + timedelta(days=i)
        
        cur.execute("""
            SELECT j.id, COALESCE(c.name, 'Client'), COALESCE(p.postcode, 'N/A'), j.status, j.start_date
            FROM jobs j
            LEFT JOIN clients c ON j.client_id = c.id
            LEFT JOIN properties p ON j.property_id = p.id
            WHERE j.engineer_id = %s AND j.start_date::DATE = %s
        """, (session['user_id'], check_date))
        daily_jobs = cur.fetchall()
        
        calendar.append({
            'date': check_date,
            'day_name': check_date.strftime('%a'),
            'day_num': check_date.strftime('%d'),
            'jobs': daily_jobs
        })

    conn.close()
    
    return render_template('site/site_dashboard.html', 
                         staff_name=staff_name,
                         my_jobs=my_jobs,
                         calendar=calendar, 
                         brand_color=config.get('color'),
                         logo_url=config.get('logo'),
                         date_format=user_date_format)
                         
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
        
        filename = None
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
               c.name, c.phone, j.site_address, j.description
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
        # --- A. START JOB (Triggers Dynamic Email) ---
        if action == 'start':
            cur.execute("UPDATE jobs SET status = 'In Progress', start_date = CURRENT_TIMESTAMP WHERE id = %s AND company_id = %s", (job_id, comp_id))
            
            # Fetch Client Email
            cur.execute("""
                SELECT c.id, c.name, c.email, j.ref, j.site_address 
                FROM jobs j 
                LEFT JOIN clients c ON j.client_id = c.id 
                WHERE j.id = %s
            """, (job_id,))
            job_data = cur.fetchone()
            
            if job_data and job_data[2]: # If client has email
                c_id, c_name, c_email, j_ref, j_addr = job_data
                
                # SEND EMAIL using Company's Own SMTP Settings
                email_sent = send_email_notification(comp_id, c_email, c_name, j_ref, j_addr)
                
                status_msg = "Sent" if email_sent else "Failed (Check Settings)"
                cur.execute("INSERT INTO client_notifications (job_id, client_id, message, status) VALUES (%s, %s, %s, %s)", 
                           (job_id, c_id, f"Start Notification to {c_email}", status_msg))
                
                if email_sent:
                    flash(f"✅ Job Started. Client notified.")
                else:
                    flash(f"✅ Job Started. (Notification failed - check Finance settings).")
            else:
                flash("✅ Job Started.")

        # --- B. COMPLETE JOB (Triggers Invoice + Smart Tax Logic) ---
        elif action == 'complete':
            signature = request.form.get('signature')
            
            cur.execute("SELECT client_id, ref, description, start_date FROM jobs WHERE id = %s", (job_id,))
            job_data = cur.fetchone()
            client_id, job_ref, job_desc, job_date = job_data
            clean_ref = job_ref.replace("Ref: ", "").replace("Quote Work: ", "").strip()

            cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id = %s", (comp_id,))
            inv_ref = f"INV-{1000 + cur.fetchone()[0] + 1}"
            
            # 1. FETCH TAX SETTINGS
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

            # 2. CREATE INVOICE SHELL
            cur.execute("""
                INSERT INTO invoices (company_id, client_id, quote_ref, reference, date, due_date, status, subtotal, tax, total, notes) 
                VALUES (%s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + 14, 'Unpaid', 0, 0, 0, %s) 
                RETURNING id
            """, (comp_id, client_id, clean_ref, inv_ref, f"Job Signed by: {signature}"))
            inv_id = cur.fetchone()[0]
            
            # 3. CALCULATE ITEMS & SUBTOTAL
            cur.execute("SELECT id FROM quotes WHERE reference = %s AND company_id = %s", (clean_ref, comp_id))
            quote_row = cur.fetchone()
            
            subtotal = 0.0
            
            if quote_row:
                quote_id = quote_row[0]
                cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
                items = cur.fetchall()
                for item in items:
                    cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) VALUES (%s, %s, %s, %s, %s)",
                               (inv_id, item[0], item[1], item[2], item[3]))
                    subtotal += float(item[3])
                flash(f"🎉 Job Completed & Invoice {inv_ref} Generated!")
            else:
                cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) VALUES (%s, %s, 1, 0, 0)",
                           (inv_id, f"Completed: {job_desc}",))
                flash(f"🎉 Job Completed & Blank Invoice {inv_ref} Created.")

            # 4. CALCULATE TAX & GRAND TOTAL
            tax_amount = subtotal * tax_rate
            grand_total = subtotal + tax_amount

            cur.execute("UPDATE invoices SET subtotal = %s, tax = %s, total = %s WHERE id = %s", (subtotal, tax_amount, grand_total, inv_id))
            cur.execute("UPDATE jobs SET status = 'Completed' WHERE id = %s", (job_id,))
            
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

# --- 5. DRIVER FUEL UPLOAD (AI POWERED) ---
@site_bp.route('/site/log-fuel', methods=['GET', 'POST'])
def log_fuel():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    user_id = session.get('user_id')
    conn = get_db(); cur = conn.cursor()

    # 1. Find the Van assigned to this Driver
    cur.execute("SELECT id, reg_plate FROM vehicles WHERE assigned_driver_id = %s", (user_id,))
    vehicle = cur.fetchone()

    if not vehicle:
        flash("❌ You are not assigned to a vehicle.")
        return redirect(url_for('site.site_dashboard'))
    
    v_id, v_reg = vehicle

    if request.method == 'POST':
        file = request.files.get('receipt')
        if file and file.filename != '':
            # Save File
            filename = secure_filename(f"FUEL_{v_reg}_{int(datetime.now().timestamp())}_{file.filename}")
            full_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(full_path)
            db_path = f"uploads/van_checks/{filename}" # Re-using van folder for simplicity

            # --- AI MAGIC ---
            cost = 0
            desc = f"Fuel for {v_reg}"
            scan = scan_receipt(full_path)
            
            if scan['success']:
                data = scan['data']
                cost = data.get('total_cost', 0)
                if data.get('vendor'): desc = f"Fuel: {data.get('vendor')} ({v_reg})"
                flash(f"✨ AI Scanned Receipt: £{cost} logged.")
            else:
                flash("✅ Receipt uploaded (AI could not read text, logged as £0).")

            # Save to DB
            cur.execute("""
                INSERT INTO maintenance_logs (company_id, vehicle_id, date, type, description, cost, receipt_path) 
                VALUES (%s, %s, CURRENT_DATE, 'Fuel', %s, %s, %s)
            """, (comp_id, v_id, desc, cost, db_path))
            
            conn.commit()
            return redirect(url_for('site.site_dashboard'))

    return render_template('site/fuel_form.html', reg=v_reg)