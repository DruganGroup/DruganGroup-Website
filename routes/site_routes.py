from flask import Blueprint, render_template, session, redirect, url_for, flash, request
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

# --- HELPER: GET STAFF ID FROM USER ID (The Source of Truth) ---
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
    
    if match: return match[0], match[1], match[2]
    
    # 2. Fallback: Just return User info
    cur.execute("SELECT company_id, name, username FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if user: return None, (user[1] or user[2]), user[0]
    return None, "Unknown", None

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

@site_bp.route('/site-hub')
@site_bp.route('/site-companion')
def site_dashboard():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. IDENTIFY STAFF
    staff_id, staff_name, _ = get_staff_identity(session['user_id'], cur)
    
    # 2. CHECK STATUSES
    is_at_work = False   
    active_job = None    
    
    if staff_id:
        # Check Day Clock
        cur.execute("SELECT id FROM staff_attendance WHERE staff_id = %s AND clock_out IS NULL", (staff_id,))
        is_at_work = cur.fetchone() is not None
        
        # Check Job Clock (Fixing the address here too)
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

    # 3. FETCH ASSIGNED JOBS (The Fix for the List)
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
            WHERE j.engineer_id = %s 
            AND j.status != 'Completed'
            ORDER BY j.status ASC, j.start_date ASC
        """, (staff_id,))
        jobs = cur.fetchall()
    
    conn.close()
    return render_template('site/site_dashboard.html', 
                           jobs=jobs, 
                           is_at_work=is_at_work, 
                           active_job=active_job,
                           staff_name=staff_name)
                           
# --- 2. CLOCK IN ---
@site_bp.route('/site/clock-in', methods=['POST'])
def clock_in():
    if 'user_id' not in session: return redirect('/login')
    
    conn = get_db(); cur = conn.cursor()
    # USE HELPER
    staff_id, _, comp_id = get_staff_identity(session['user_id'], cur)
    
    if not staff_id:
        flash("❌ Error: Not linked to Staff Profile.", "error")
        return redirect('/site-hub')

    try:
        cur.execute("SELECT id FROM staff_timesheets WHERE staff_id = %s AND clock_out IS NULL", (staff_id,))
        if cur.fetchone():
            flash("⚠️ Already clocked in!", "warning")
        else:
            cur.execute("INSERT INTO staff_timesheets (staff_id, company_id, clock_in, date) VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_DATE)", (staff_id, comp_id))
            # --- AUDIT LOG (CLOCK IN) ---
            try:
                # We need to fetch the staff name for the log
                cur.execute("SELECT name FROM staff WHERE id = %s", (staff_id,))
                s_name = cur.fetchone()[0]
                
                cur.execute("""
                    INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                    VALUES (%s, 'CLOCK_IN', %s, 'Started Shift', %s, CURRENT_TIMESTAMP)
                """, (comp_id, s_name, s_name))
            except Exception as e:
                print(f"Audit Log Error: {e}")
            # ----------------------------
            conn.commit(); flash("🕒 Clocked In Successfully!")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect('/site-hub')

# --- 3. CLOCK OUT ---
@site_bp.route('/site/clock-out', methods=['POST'])
def clock_out():
    if 'user_id' not in session: return redirect('/login')
    
    conn = get_db(); cur = conn.cursor()
    # USE HELPER
    staff_id, _, comp_id = get_staff_identity(session['user_id'], cur)
    
    try:
        cur.execute("SELECT id, clock_in FROM staff_timesheets WHERE staff_id = %s AND clock_out IS NULL ORDER BY id DESC LIMIT 1", (staff_id,))
        row = cur.fetchone()
        if row:
            sheet_id, start_time = row
            diff = datetime.now() - start_time
            hours = diff.total_seconds() / 3600
            
            cur.execute("UPDATE staff_timesheets SET clock_out = CURRENT_TIMESTAMP, total_hours = %s WHERE id = %s", (round(hours, 2), sheet_id))
        # --- AUDIT LOG (CLOCK OUT) ---
            try:
                # Get Staff Name
                cur.execute("SELECT name FROM staff WHERE id = %s", (staff_id,))
                s_name = cur.fetchone()[0]

                cur.execute("""
                    INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                    VALUES (%s, 'CLOCK_OUT', %s, %s, %s, CURRENT_TIMESTAMP)
                """, (comp_id, s_name, f"Shift Finished ({round(hours, 2)} hrs)", s_name))
            except Exception as e:
                print(f"Audit Log Error: {e}")
            # -----------------------------
            conn.commit(); flash(f"🕒 Clocked Out. Shift: {round(hours, 2)} hrs.")
        else:
            flash("⚠️ No active shift found.", "warning")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect('/site-hub')
                          
# --- 4. VAN CHECK (Smart Link) ---
@site_bp.route('/site/van-check', methods=['GET', 'POST'])
def van_check_page():
    if not check_site_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    # 1. Identify Driver & Assigned Van
    staff_id, _, _ = get_staff_identity(session['user_id'], cur)
    search_id = staff_id if staff_id else session['user_id']
    
    cur.execute("SELECT id, reg_plate FROM vehicles WHERE assigned_driver_id = %s", (search_id,))
    assigned_van = cur.fetchone() # Returns (id, 'AB12 CDE') or None

    if request.method == 'POST':
        # If locked to a van, use that. Otherwise, take from form.
        reg = assigned_van[1] if assigned_van else request.form.get('reg_plate')
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
            # Re-verify ID (Safe check)
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
                return redirect(url_for('site.site_dashboard'))
            else:
                flash("❌ Vehicle not found.")
        except Exception as e: conn.rollback(); flash(f"Error: {e}")

    # If no assigned van, fetch list for dropdown fallback
    vehicles = []
    if not assigned_van:
        cur.execute("SELECT reg_plate FROM vehicles WHERE company_id = %s AND status='Active' ORDER BY reg_plate", (comp_id,))
        vehicles = [r[0] for r in cur.fetchall()]
    
    conn.close()
    
    # Pass 'assigned_van' (tuple) or 'vehicles' (list)
    return render_template('site/van_check_form.html', vehicles=vehicles, assigned_van=assigned_van)
                           
# --- NEW: ADD MATERIAL TO JOB ---
@site_bp.route('/site/job/<int:job_id>/add-material', methods=['POST'])
def add_job_material(job_id):
    if 'user_id' not in session: return redirect('/login')
    
    description = request.form.get('description')
    quantity = request.form.get('quantity')
    
    # Optional: If your staff knows the price, they enter it. If not, default to 0 for Office to fix.
    price = request.form.get('price') or 0 

    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO job_materials (job_id, description, quantity, unit_price)
            VALUES (%s, %s, %s, %s)
        """, (job_id, description, quantity, price))
        conn.commit()
        flash("✅ Item Added")
    except Exception as e:
        conn.rollback()
        flash(f"Error adding item: {e}")
    finally:
        conn.close()
    
    return redirect(url_for('site.job_details', job_id=job_id))

# --- 6. UPDATE JOB (With Auto-Billing) ---
@site_bp.route('/site/job/<int:job_id>/update', methods=['POST'])
def update_job(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    action = request.form.get('action')
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    user_name = session.get('user_name', 'Engineer') # Get name for the log
    
    try:
        # A. START JOB
        if action == 'start':
            cur.execute("UPDATE jobs SET status = 'In Progress', start_date = CURRENT_TIMESTAMP WHERE id = %s", (job_id,))
            # --- AUDIT LOG ---
            try:
                cur.execute("""
                    INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                    VALUES (%s, 'JOB_COMPLETED', %s, %s, %s, CURRENT_TIMESTAMP)
                """, (comp_id, f"Job #{job_id}", f"Completed by {user_name}", user_name))
            except Exception as e:
                print(f"Audit Log Error: {e}")
            # Send Notification
            cur.execute("SELECT c.id, c.name, c.email, j.ref, j.site_address FROM jobs j LEFT JOIN clients c ON j.client_id = c.id WHERE j.id = %s", (job_id,))
            job_data = cur.fetchone()
            if job_data and job_data[2]: 
                c_id, c_name, c_email, j_ref, j_addr = job_data
                sent = send_email_notification(comp_id, c_email, c_name, j_ref, j_addr)
                flash("✅ Job Started." + (" Client Notified." if sent else ""))
            else:
                flash("✅ Job Started.")

# B. COMPLETE JOB (With Auto-Material Billing)
        elif action == 'complete':
            signature = request.form.get('signature')
            work_summary = request.form.get('work_summary')
            private_notes = request.form.get('private_notes')
            
            # 1. Fetch Job Data (NOW INCLUDING quote_id)
            cur.execute("""
                SELECT client_id, ref, description, start_date, property_id, quote_id 
                FROM jobs WHERE id = %s AND company_id = %s
            """, (job_id, comp_id))
            job_data = cur.fetchone()
            
            if not job_data:
                flash("❌ Job not found.", "error")
                return redirect(url_for('site.site_dashboard'))

            client_id, job_ref, job_desc, job_date, prop_id, linked_quote_id = job_data
            
            # 2. Update Job Record
            cur.execute("""
                UPDATE jobs 
                SET status = 'Completed', end_date = CURRENT_TIMESTAMP, 
                    work_summary = %s, private_notes = %s 
                WHERE id = %s
            """, (work_summary, private_notes, job_id))

            # Generate Invoice Reference
            cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id = %s", (comp_id,))
            inv_ref = f"INV-{1000 + cur.fetchone()[0] + 1}"
            
            inv_id = None

            # --- PATH A: QUOTED JOB (ROBUST LINK) ---
            # We now check linked_quote_id directly, instead of searching by text string
            if linked_quote_id:
                # Create Invoice from Quote
                cur.execute("""
                    INSERT INTO invoices (company_id, client_id, quote_ref, reference, date, due_date, status, subtotal, tax, total, job_id, notes) 
                    VALUES (%s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + 14, 'Unpaid', 0, 0, 0, %s, %s) 
                    RETURNING id
                """, (comp_id, client_id, job_ref, inv_ref, job_id, f"Signed by: {signature}"))
                inv_id = cur.fetchone()[0]
                
                # Copy Items from the SPECIFIC Quote ID
                cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (linked_quote_id,))
                quote_items = cur.fetchall()
                
                for item in quote_items:
                    cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) VALUES (%s, %s, %s, %s, %s)",
                               (inv_id, item[0], item[1], item[2], item[3]))
                
                flash(f"🎉 Quoted Invoice {inv_ref} Generated.")

            # --- PATH B: DO & CHARGE (DRAFT) ---
            else:
                # Create Invoice Shell
                cur.execute("""
                    INSERT INTO invoices (company_id, client_id, reference, date, due_date, status, subtotal, tax, total, job_id, notes) 
                    VALUES (%s, %s, %s, CURRENT_DATE, CURRENT_DATE + 14, 'Draft', 0, 0, 0, %s, %s) 
                    RETURNING id
                """, (comp_id, client_id, inv_ref, job_id, f"Pending Pricing. Work: {work_summary}"))
                inv_id = cur.fetchone()[0]
                
                # Add Labour Line
                cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) VALUES (%s, %s, 1, 0, 0)", 
                           (inv_id, f"Labour: {work_summary}"))
                
                flash(f"✅ Draft Invoice {inv_ref} Created.")

            # --- 4. THE MAGIC: ADD TRACKED MATERIALS (Common to BOTH Paths) ---
            # This looks up the materials your driver added and puts them on the invoice automatically
            cur.execute("SELECT description, quantity, unit_price FROM job_materials WHERE job_id = %s", (job_id,))
            materials = cur.fetchall()
            
            if materials:
                for mat in materials:
                    desc = mat[0]
                    qty = mat[1]
                    price = float(mat[2])
                    total = price * qty
                    
                    # Insert as Invoice Item (Marked as Material)
                    cur.execute("""
                        INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) 
                        VALUES (%s, %s, %s, %s, %s)
                    """, (inv_id, f"Material: {desc}", qty, price, total))
            
            # --- 5. RE-CALCULATE TOTALS ---
            # We must re-sum the total because we just added extra lines (Materials)
            cur.execute("SELECT SUM(total) FROM invoice_items WHERE invoice_id = %s", (inv_id,))
            new_subtotal = cur.fetchone()[0] or 0.0
            
            # --- SMART TAX CALCULATION (Updated) ---
            # 1. Get All Settings
            cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
            settings = {row[0]: row[1] for row in cur.fetchall()}
            
            is_vat = settings.get('vat_registered') == 'yes'
            country = settings.get('country_code', 'UK')

            # 2. Determine Rate
            tax_rate = 0.0
            if is_vat:
                if country == 'UK': tax_rate = 0.20
                elif country == 'US': tax_rate = 0.08    # Avg Sales Tax
                elif country == 'IE': tax_rate = 0.23    # VAT
                elif country == 'AUS': tax_rate = 0.10
                elif country == 'NZ': tax_rate = 0.15
                elif country == 'CAN': tax_rate = 0.05
                elif country == 'EU': tax_rate = 0.21
                else: tax_rate = 0.20

            # 3. Apply Tax
            new_tax = float(new_subtotal) * tax_rate
            new_total = float(new_subtotal) + new_tax
            
            cur.execute("UPDATE invoices SET subtotal = %s, tax = %s, total = %s WHERE id = %s", 
                       (new_subtotal, new_tax, new_total, inv_id))

            # Close Service Ticket
            cur.execute("UPDATE service_requests SET status = 'Completed' WHERE property_id = %s AND status = 'In Progress'", (prop_id,))

        # C. UPLOAD PHOTO
        elif action == 'upload_photo':
            if 'photo' in request.files:
                file = request.files['photo']
                if file.filename != '':
                    os.makedirs(JOB_EVIDENCE_FOLDER, exist_ok=True)
                    filename = secure_filename(f"JOB_{job_id}_{int(datetime.now().timestamp())}_{file.filename}")
                    
                    # --- THE FIX: ADD 'static/' TO THE DB PATH ---
                    db_path = f"static/uploads/job_evidence/{filename}"
                    # ---------------------------------------------
                    
                    file.save(os.path.join(JOB_EVIDENCE_FOLDER, filename))
                    cur.execute("INSERT INTO job_evidence (job_id, filepath, uploaded_by) VALUES (%s, %s, %s)", (job_id, db_path, session['user_id']))
                    flash("📷 Photo Uploaded")
                    
                    # --- AUDIT LOG ---
                    cur.execute("""
                        INSERT INTO audit_logs (company_id, action, target, details, admin_email)
                        VALUES (%s, 'PHOTO_UPLOAD', %s, %s, %s)
                    """, (comp_id, f"Job #{job_id}", "Site Photo Added", user_name))
            conn.commit()
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    if action == 'complete': return redirect(url_for('site.site_dashboard'))
    return redirect(url_for('site.job_details', job_id=job_id))

# --- PUBLIC PAGES ---
@site_bp.route('/advertise')
@site_bp.route('/business-better')
def advertise_page(): return render_template('public/advert-bb.html')

# --- NEW: API FOR JS AUTO-FILL ---
@site_bp.route('/site/api/scan-receipt', methods=['POST'])
def api_scan_receipt():
    # 1. Check Login & AI Access
    if 'user_id' not in session: return {"success": False, "error": "Login required"}, 401
    if not scan_receipt: return {"success": False, "error": "AI Service not available"}, 503

    # 2. Get File
    file = request.files.get('receipt')
    if not file: return {"success": False, "error": "No file uploaded"}, 400

    try:
        # 3. Save Temp File
        filename = secure_filename(f"TEMP_SCAN_{int(datetime.now().timestamp())}_{file.filename}")
        full_path = os.path.join(UPLOAD_FOLDER, filename)
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        file.save(full_path)

        # 4. Run AI
        scan_result = scan_receipt(full_path)
        
        # 5. Clean up (Delete temp file to save space, or keep it if you prefer)
        # os.remove(full_path) 

        return scan_result # Returns {success: true, data: {total_cost: 50.00, ...}}
    except Exception as e:
        return {"success": False, "error": str(e)}, 500

# --- 7. LOG FUEL (Final Logic) ---
@site_bp.route('/site/log-fuel', methods=['GET', 'POST'])
def log_fuel():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    # Identity Check
    staff_id, _, _ = get_staff_identity(session['user_id'], cur)
    search_id = staff_id if staff_id else session['user_id']

    cur.execute("SELECT id, reg_plate FROM vehicles WHERE assigned_driver_id = %s", (search_id,))
    vehicle = cur.fetchone()

    if not vehicle:
        flash("❌ No vehicle assigned. Contact Office.")
        return redirect(url_for('site.site_dashboard'))
    
    v_id, v_reg = vehicle

    if request.method == 'POST':
        mileage = request.form.get('mileage')
        litres = request.form.get('litres')
        total_cost = request.form.get('total_cost')
        fuel_type = request.form.get('fuel_type')
        file = request.files.get('receipt') # Re-upload not needed if JS handled it, but Flask needs it for the final save path
        
        if file and file.filename != '':
            try:
                filename = secure_filename(f"FUEL_{v_reg}_{int(datetime.now().timestamp())}_{file.filename}")
                full_path = os.path.join(UPLOAD_FOLDER, filename)
                os.makedirs(UPLOAD_FOLDER, exist_ok=True) 
                # Save the file permanently now (The JS scan was just temporary/preview)
                file.save(full_path)
                db_path = f"uploads/van_checks/{filename}"

                # Data Formatting
                final_cost = float(total_cost) if total_cost else 0.0
                final_litres = float(litres) if litres else 0.0
                desc = f"{fuel_type} ({final_litres}L) for {v_reg}. Mileage: {mileage}"
                
                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, date, type, description, cost, receipt_path, litres, fuel_type) 
                    VALUES (%s, %s, CURRENT_DATE, 'Fuel', %s, %s, %s, %s, %s)
                """, (comp_id, v_id, desc, final_cost, db_path, final_litres, fuel_type))

                if mileage:
                    cur.execute("UPDATE vehicles SET mileage = %s WHERE id = %s", (mileage, v_id))
                
                conn.commit()
                flash("✅ Fuel Logged!")
                return redirect(url_for('site.site_dashboard'))
            except Exception as e:
                conn.rollback(); flash(f"Error: {e}")

    return render_template('site/fuel_form.html', reg=v_reg)
    
@site_bp.route('/site/fix-audit-table')
def fix_audit_table():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Unauthorized"
    conn = get_db()
    cur = conn.cursor()
    try:
        # 1. Ensure Table Exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                company_id INTEGER,
                action TEXT,
                target TEXT,
                details TEXT,
                admin_email TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 2. Add columns if they are missing (Safe Patch)
        cur.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS admin_email TEXT;")
        cur.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS target TEXT;")
        cur.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
        
        # 3. Create a Test Entry
        cur.execute("""
            INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
            VALUES (%s, 'TEST_ENTRY', 'System', 'Verifying Audit Log works', 'System', CURRENT_TIMESTAMP)
        """, (session.get('company_id'),))
        
        conn.commit()
        return "<h1>✅ Audit Table Repaired & Test Entry Added</h1><p>Go check the Finance Dashboard now.</p>"
    except Exception as e:
        conn.rollback()
        return f"<h1>Error</h1><p>{e}</p>"
    finally:
        conn.close()
        # =========================================================
# 8. SITE SYSTEM INSTALLER (Run this once)
# =========================================================
@site_bp.route('/site/setup-db')
def setup_site_db():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Unauthorized"
    
    conn = get_db()
    cur = conn.cursor()
    log = []
    
    try:
        # 1. Staff Timesheets (Clock In/Out)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS staff_timesheets (
                id SERIAL PRIMARY KEY,
                company_id INTEGER,
                staff_id INTEGER,
                date DATE DEFAULT CURRENT_DATE,
                clock_in TIMESTAMP,
                clock_out TIMESTAMP,
                total_hours NUMERIC(5,2),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        log.append("✅ Timesheets Table Created")

        # 2. Job Materials (Used on Site)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS job_materials (
                id SERIAL PRIMARY KEY,
                job_id INTEGER,
                description TEXT,
                quantity INTEGER,
                unit_price NUMERIC(10,2),
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        log.append("✅ Job Materials Table Created")

        # 3. Job Evidence (Photos)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS job_evidence (
                id SERIAL PRIMARY KEY,
                job_id INTEGER,
                filepath TEXT,
                uploaded_by INTEGER,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        log.append("✅ Job Evidence Table Created")

        conn.commit()
        return f"<h1>Site System Ready</h1><br>{'<br>'.join(log)}<br><br><a href='/site-hub'>Go to Site Hub</a>"
        
    except Exception as e:
        conn.rollback()
        return f"<h1>Error</h1><p>{e}</p>"
    finally:
        conn.close()
        
# UPDATE THIS FUNCTION IN routes/site_routes.py

@site_bp.route('/site/job/<int:job_id>/toggle-site-time', methods=['POST'])
def toggle_site_time(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. IDENTIFY THE INDIVIDUAL USER
    staff_id, staff_name, _ = get_staff_identity(session['user_id'], cur)
    action = request.form.get('action') # 'start' or 'stop'
    
    try:
        if action == 'start':
            # Check if THIS PERSON is already clocked in
            cur.execute("SELECT id FROM staff_timesheets WHERE staff_id = %s AND clock_out IS NULL", (staff_id,))
            if cur.fetchone():
                flash("⚠️ You are already clocked in!", "warning")
            else:
                # Clock in ONLY this person (Using CURRENT_TIMESTAMP)
                cur.execute("""
                    INSERT INTO staff_timesheets (company_id, staff_id, job_id, date, clock_in)
                    VALUES (%s, %s, %s, CURRENT_DATE, CURRENT_TIMESTAMP)
                """, (session['company_id'], staff_id, job_id))
                flash(f"✅ Clocked IN: {staff_name}", "success")

        elif action == 'stop':
            # Clock out ONLY this person (Using CURRENT_TIMESTAMP for math)
            # We calculate hours by subtracting the stored timestamp from NOW
            cur.execute("""
                UPDATE staff_timesheets 
                SET clock_out = CURRENT_TIMESTAMP, 
                    hours = EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - clock_in))/3600 
                WHERE staff_id = %s AND job_id = %s AND clock_out IS NULL
            """, (staff_id, job_id))
            flash(f"🛑 Clocked OUT: {staff_name}", "success")
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('site.job_details', job_id=job_id))

@site_bp.route('/site/job/<int:job_id>')
def job_details(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. IDENTIFY STAFF
    staff_id, staff_name, _ = get_staff_identity(session['user_id'], cur)
    
    # 2. GET JOB DETAILS (Fixed Address Query)
    # We now JOIN 'properties' so we can fetch the real address
    cur.execute("""
        SELECT j.id, j.ref, j.status, c.name, c.phone, 
               COALESCE(p.address_line1, j.site_address, 'No Address Logged') as address,
               p.postcode, 
               j.description, c.gate_code
        FROM jobs j
        LEFT JOIN clients c ON j.client_id = c.id
        LEFT JOIN properties p ON j.property_id = p.id
        WHERE j.id = %s
    """, (job_id,))
    row = cur.fetchone()
    
    if not row: conn.close(); return "Job not found", 404

    # 3. CONVERT TO SAFE DICTIONARY
    # Format the address nicely to include postcode if available
    addr_line = row[5]
    postcode = row[6]
    full_address = f"{addr_line}, {postcode}" if postcode else addr_line

    job = {
        'id': row[0],
        'ref': row[1],
        'status': row[2],
        'client_name': row[3] or "Unknown Client",
        'client_phone': row[4] or "No Phone",
        'address': full_address, 
        'description': row[7] or "No Description",
        'gate_code': row[8]
    }

    # 4. CHECK IF CLOCKED IN
    user_is_clocked_in = False
    if staff_id:
        cur.execute("""
            SELECT id FROM staff_timesheets 
            WHERE staff_id = %s AND job_id = %s AND clock_out IS NULL
        """, (staff_id, job_id))
        if cur.fetchone():
            user_is_clocked_in = True

    # 5. FETCH MATERIALS & PHOTOS
    cur.execute("SELECT description, quantity, unit_price FROM job_materials WHERE job_id = %s", (job_id,))
    materials = cur.fetchall()

    cur.execute("SELECT filepath FROM job_evidence WHERE job_id = %s", (job_id,))
    photos = [row[0] for row in cur.fetchall()]

    # 6. FETCH BRANDING
    comp_id = session.get('company_id')
    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'logo'", (comp_id,))
    logo_row = cur.fetchone()
    logo_url = logo_row[0] if logo_row else None
    
    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'brand_color'", (comp_id,))
    color_row = cur.fetchone()
    brand_color = color_row[0] if color_row else '#333333'

    conn.close()
    
    return render_template('site/job_details.html', 
                           job=job, 
                           materials=materials, 
                           photos=photos, 
                           user_is_clocked_in=user_is_clocked_in, 
                           logo_url=logo_url,
                           brand_color=brand_color)
                           
@site_bp.route('/site/toggle-day-clock', methods=['POST'])
def toggle_day_clock():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    staff_id, _, _ = get_staff_identity(session['user_id'], cur)
    action = request.form.get('action')
    
    try:
        if action == 'start':
            # Start Day
            cur.execute("SELECT id FROM staff_attendance WHERE staff_id = %s AND clock_out IS NULL", (staff_id,))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO staff_attendance (company_id, staff_id, date, clock_in)
                    VALUES (%s, %s, CURRENT_DATE, CURRENT_TIMESTAMP)
                """, (session['company_id'], staff_id))
                flash("☀️ Good Morning! You are clocked in for PAYROLL.", "success")

        elif action == 'stop':
            # End Day
            cur.execute("""
                UPDATE staff_attendance 
                SET clock_out = CURRENT_TIMESTAMP, 
                    total_hours = EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - clock_in))/3600 
                WHERE staff_id = %s AND clock_out IS NULL
            """, (staff_id,))
            flash("🌙 Shift Ended. See you tomorrow!", "success")
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('site.site_dashboard'))
    
@site_bp.route('/site/unify-database')
def unify_database():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Unauthorized"
    conn = get_db(); cur = conn.cursor()
    log = []
    try:
        # 1. Ensure Target NEW Columns Exist
        cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS reference TEXT;")
        cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS total NUMERIC(10,2) DEFAULT 0;")
        cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS date DATE;")
        log.append("✅ Target columns (reference, total, date) checked.")

        # 2. Sync REFERENCE (Try 'ref' first)
        try:
            # We only try to read 'ref', ignoring 'invoice_number' since it crashed
            cur.execute("UPDATE invoices SET reference = ref WHERE reference IS NULL AND ref IS NOT NULL")
            log.append("✅ Synced 'ref' -> 'reference'")
        except Exception as e:
            conn.rollback()
            log.append(f"⚠️ Could not sync Ref: {e}")

        # 3. Sync TOTAL (Try 'total_amount')
        try:
            cur.execute("UPDATE invoices SET total = total_amount WHERE (total IS NULL OR total = 0) AND total_amount > 0")
            log.append("✅ Synced 'total_amount' -> 'total'")
        except Exception as e:
            conn.rollback()
            log.append(f"⚠️ Could not sync Total: {e}")

        # 4. Sync DATE (Try 'date_created' or 'date_issue')
        try:
            # Try date_created first (standard)
            cur.execute("UPDATE invoices SET date = date_created WHERE date IS NULL AND date_created IS NOT NULL")
            log.append("✅ Synced 'date_created' -> 'date'")
        except:
            conn.rollback()
            try:
                # Fallback to date_issue (portal style)
                cur.execute("UPDATE invoices SET date = date_issue WHERE date IS NULL AND date_issue IS NOT NULL")
                log.append("✅ Synced 'date_issue' -> 'date'")
            except:
                conn.rollback()

        conn.commit()
        return f"<h1>Database Unified</h1><br>{'<br>'.join(log)}"
    except Exception as e:
        conn.rollback(); return f"Error: {e}"
    finally:
        conn.close()